"""Plain-assert tests for sync.py: every committed credential's row can be found by Certify.

Certify 0.14 finds an ldp_vc credential's row by its types and its contexts, each sorted and comma-joined
(`CredentialUtils.getTemplateName`), and compares them exactly with the row's `credential_type` and `context`.
A row stored in any other order answers "CredentialConfig not found" for every request.

Host only, no Docker. Run: python3 src/certify_template_sync/test_sync.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from certify_template_sync import sync  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIAL_DIRS = sorted(REPO_ROOT.glob("deploy/*/certify/credentials"))


def certify_lookup(values: list[str]) -> str:
    """How Certify joins the types or contexts it looks a row up by."""
    return ",".join(sorted(values))


def rows_and_lookups(creds_dir: Path) -> list[tuple[str, str, list[str]]]:
    """For each credential file: its key, the SQL template-sync writes, and the strings Certify looks it up by."""
    out = []
    for _, config in sync.load_credential_configs(creds_dir):
        sql = sync.generate_sql_statement(config)
        types = config["credential_type"].split(",")
        out.append((config["credential_config_key_id"], sql, [certify_lookup(types), certify_lookup(config["context"])]))
    return out


def test_every_committed_credential_is_written_in_certifys_lookup_order() -> None:
    assert CREDENTIAL_DIRS, "no deploy/*/certify/credentials found"
    for creds_dir in CREDENTIAL_DIRS:
        for key, sql, lookups in rows_and_lookups(creds_dir):
            for lookup in lookups:
                assert sync.escape_sql_str(lookup) in sql, (creds_dir.parent.parent.name, key, lookup)


def test_the_order_holds_when_the_vdr_address_sorts_after_the_w3c_context() -> None:
    # template-sync rewrites the VDR address before writing the row, so the contexts' order depends on it.
    before = os.environ.get("VDR_BASE_URL")
    os.environ["VDR_BASE_URL"] = "https://x.example"
    try:
        for creds_dir in CREDENTIAL_DIRS:
            for key, sql, lookups in rows_and_lookups(creds_dir):
                assert "https://x.example/contexts/" in lookups[1], (key, lookups[1])
                for lookup in lookups:
                    assert sync.escape_sql_str(lookup) in sql, (creds_dir.parent.parent.name, key, lookup)
    finally:
        if before is None:
            del os.environ["VDR_BASE_URL"]
        else:
            os.environ["VDR_BASE_URL"] = before


def test_the_local_addresses_are_rewritten_to_the_vdr_address_without_its_trailing_slash() -> None:
    text = '{"a": "http://vdr.localhost/contexts/x.json", "b": "http://cdn.localhost/logo.png", "c": "https://other/x"}'
    assert sync.rewrite_local_addresses(text, "https://vdr.example.org/") == (
        '{"a": "https://vdr.example.org/contexts/x.json", "b": "https://vdr.example.org/logo.png", "c": "https://other/x"}')


def test_the_rewrite_leaves_an_address_that_already_starts_with_the_vdr_address_alone() -> None:
    base = "http://vdr.localhost:8088"
    text = '{"a": "http://vdr.localhost:8088/contexts/x.json", "b": "http://vdr.localhost/y", "c": "http://cdn.localhost/z"}'
    once = sync.rewrite_local_addresses(text, base)
    assert once == ('{"a": "http://vdr.localhost:8088/contexts/x.json", "b": "http://vdr.localhost:8088/y", '
                    '"c": "http://vdr.localhost:8088/z"}'), once
    assert sync.rewrite_local_addresses(once, base) == once, "a second pass changes nothing"


def test_a_vdr_address_that_is_the_start_of_a_local_address_still_replaces_it() -> None:
    # http://vdr is the VDR's Compose service name; it is the start of http://vdr.localhost.
    text = '"http://vdr.localhost/contexts/x.json" "http://cdn.localhost/assets/a.png"'
    for base in ("http://vdr", "http://cdn", "http://vdr.local", "http://cdn.localhost", "http://vdr.localhost:8080",
                 "http://vdr.localhost/sub", "http://vdr.localhost.example.org"):
        once = sync.rewrite_local_addresses(text, base)
        assert once == f'"{base}/contexts/x.json" "{base}/assets/a.png"', (base, once)
        assert sync.rewrite_local_addresses(once, base) == once, (base, "a second pass changes nothing")


def test_only_a_whole_local_host_is_a_local_address() -> None:
    text = "http://vdr.localhost.example.org/a http://cdn.localhostx/b http://vdr.localhost:9000/c http://vdr.localhost"
    assert sync.rewrite_local_addresses(text, "https://v.example") == (
        "http://vdr.localhost.example.org/a http://cdn.localhostx/b https://v.example:9000/c https://v.example")


def test_the_committed_credentials_are_rewritten_as_before_for_the_two_addresses_in_use() -> None:
    files = [p for d in CREDENTIAL_DIRS for p in sorted(d.glob("*.json"))]
    assert files, "no committed credential files"
    for base in ("https://vdr.dpi.ait.ac.th", "http://vdr.localhost", "http://vdr.localhost:8080", "http://vdr",
                 "http://cdn"):
        for path in files:
            text = path.read_text(encoding="utf-8")
            plain = text.replace("http://vdr.localhost", base).replace("http://cdn.localhost", base)
            assert sync.rewrite_local_addresses(text, base) == plain, (base, path.name)


def test_load_credential_configs_rewrites_through_the_shared_function() -> None:
    import tempfile
    before = {k: os.environ.get(k) for k in ("VDR_BASE_URL", "CDN_BASE_URL")}
    os.environ["VDR_BASE_URL"] = "https://v.example/"
    os.environ.pop("CDN_BASE_URL", None)
    try:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "c.json").write_text(
                '{"u": "http://vdr.localhost/a", "l": "http://cdn.localhost/b", "v": "${VDR_BASE_URL}/c"}')
            [(_, config)] = sync.load_credential_configs(Path(d))
        assert config == {"u": "https://v.example/a", "l": "https://v.example/b", "v": "https://v.example/c"}
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
