"""Publishing a VC Lab set to the local stack: the files it places, and what it refuses.

Host only, no Docker. src/tools/publish_set.py does the file half of scripts/publish-set.sh (the template and the
Background onto the VDR, the credential file into a folder for template-sync); the script's stack half (the refusal,
template-sync, Certify) is shown on the live stack, and only its refusals run here. Each test runs the real tool or
script in a scratch repository root, as the script runs from the repository root.
Run: python3 tests/test_publish_set.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "src" / "tools" / "publish_set.py"
SCRIPT = REPO_ROOT / "scripts" / "publish-set.sh"

TEMPLATES = "deploy/ait/vdr/templates"
TEMPLATE_NAME = "AITUniversity-ait-transcript-template.html"
PNG = b"\x89PNG\r\n\x1a\n" + b"made-up png bytes"
JPEG = b"\xff\xd8\xff\xe0" + b"made-up jpeg bytes" + b"\xff\xd9"
OTHER_CREDENTIAL = {"credential_config_key_id": "ait-student-id", "display": [{"name": "Student ID"}]}
COMMITTED_CREDENTIAL = {"credential_config_key_id": "ait-transcript", "display": [{"name": "Committed transcript"}]}
SET_CREDENTIAL = {"credential_config_key_id": "ait-transcript", "display": [{"name": "Set's transcript"}]}
BACKGROUND_URI = "http://vdr.localhost/templates/ait-transcript/background.png"


def make_zip(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


def a_set(**over: bytes | None) -> dict[str, bytes]:
    """The members of a VC Lab download; a keyword replaces a member by its folder name, or drops it with None."""
    files = {"template/my-template.html": b"<p>the set's template</p>",
             "credential/downloaded.json": json.dumps(SET_CREDENTIAL).encode(),
             "sample/record.json": b"{}",
             "background/paper.jpg": JPEG}
    for folder, data in over.items():
        for name in [n for n in files if n.startswith(folder + "/")]:
            del files[name]
        if data is not None:
            files[f"{folder}/{'paper.jpg' if folder == 'background' else 'x'}"] = data
    return files


class Root:
    """A scratch repository root: an Installation with a committed template and two credential files."""

    def __init__(self, tracked: bool = True) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.templates = self.dir / TEMPLATES
        self.templates.mkdir(parents=True)
        creds = self.dir / "deploy/ait/certify/credentials"
        creds.mkdir(parents=True)
        (creds / "ait-student-id.json").write_text(json.dumps(OTHER_CREDENTIAL), encoding="utf-8")
        (creds / "ait-transcript.json").write_text(json.dumps(COMMITTED_CREDENTIAL), encoding="utf-8")
        (self.templates / TEMPLATE_NAME).write_bytes(b"<p>committed template</p>")
        self.out = self.dir / "creds-out"
        subprocess.run(["git", "init", "-q"], cwd=self.dir, check=True)
        if tracked:
            subprocess.run(["git", "add", "deploy"], cwd=self.dir, check=True)
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], cwd=self.dir, check=True)

    def publish(self, files: dict[str, bytes] | bytes, issuer_id: str = "AITUniversity",
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        zip_path = self.dir / "set.zip"
        zip_path.write_bytes(files if isinstance(files, bytes) else make_zip(files))
        return subprocess.run([sys.executable, str(TOOL), "--set", str(zip_path), f"--issuer-id={issuer_id}",
                               "--installation", "ait", "--credentials-out", str(self.out)],
                              cwd=self.dir, capture_output=True, text=True, env={**os.environ, **(env or {})})

    def tree(self) -> dict[str, str]:
        """Every file under the root (except .git and the zip) and its hash: the state a publish leaves."""
        return {str(p.relative_to(self.dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(self.dir.rglob("*")) if p.is_file() and ".git" not in p.parts and p.name != "set.zip"}

    def close(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def with_root(test):
    def wrapper() -> None:
        root = Root()
        try:
            test(root)
        finally:
            root.close()
    wrapper.__name__ = test.__name__
    return wrapper


@with_root
def test_a_set_lands_as_the_template_the_background_and_a_credentials_folder(root: Root) -> None:
    run = root.publish(a_set())
    assert run.returncode == 0, run.stderr
    # The template under Mimoto's name, <issuer id>-<credential configuration id>-template.html.
    assert (root.templates / TEMPLATE_NAME).read_bytes() == b"<p>the set's template</p>"
    # The Background where display[0].background_image.uri points, as the bytes it came in.
    assert (root.templates / "ait-transcript" / "background.png").read_bytes() == JPEG
    # The credential folder: every credential of the Installation, with the set's file in place of the committed one,
    # named for its credential configuration id (the file's name in the zip doesn't matter).
    assert sorted(p.name for p in root.out.iterdir()) == ["ait-student-id.json", "ait-transcript.json"]
    # The set's credential file, plus what makes the publish work: the live DID, and the Background's address.
    assert json.loads((root.out / "ait-transcript.json").read_text(encoding="utf-8")) == {
        **SET_CREDENTIAL, "did_url": "${CERTIFY_DID}",
        "display": [{"name": "Set's transcript", "background_image": {"uri": BACKGROUND_URI}}]}
    assert json.loads((root.out / "ait-student-id.json").read_text(encoding="utf-8")) == OTHER_CREDENTIAL
    # The committed credential file is untouched.
    committed = root.dir / "deploy/ait/certify/credentials/ait-transcript.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == COMMITTED_CREDENTIAL


@with_root
def test_it_warns_that_git_tracks_the_template_and_the_next_checkout_puts_it_back(root: Root) -> None:
    run = root.publish(a_set())
    assert run.returncode == 0, run.stderr
    out = run.stdout + run.stderr
    assert f"{TEMPLATES}/{TEMPLATE_NAME}" in out and "git tracks" in out and "checkout" in out, out
    assert "warning" in out.lower(), out


def test_it_does_not_warn_about_a_template_git_does_not_track() -> None:
    root = Root(tracked=False)
    try:
        run = root.publish(a_set())
        assert run.returncode == 0, run.stderr
        assert "git tracks" not in run.stdout + run.stderr, run.stdout + run.stderr
    finally:
        root.close()


@with_root
def test_publishing_the_same_set_twice_leaves_the_same_state(root: Root) -> None:
    first = root.publish(a_set())
    state = root.tree()
    second = root.publish(a_set())
    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    assert root.tree() == state
    assert first.stdout == second.stdout


@with_root
def test_a_jpeg_background_keeps_its_bytes_and_takes_the_png_name(root: Root) -> None:
    root.publish(a_set())
    placed = root.templates / "ait-transcript" / "background.png"
    assert placed.read_bytes()[:2] == b"\xff\xd8"  # still a JPEG: the printer reads the type from the bytes
    assert not list((root.templates / "ait-transcript").glob("*.jpg"))
    root.publish(a_set(background=PNG))
    assert placed.read_bytes() == PNG


def written_credential(root: Root) -> dict:
    return json.loads((root.out / "ait-transcript.json").read_text(encoding="utf-8"))


@with_root
def test_a_sets_background_gets_its_address_in_the_credential_the_next_print_fetches_it_from(root: Root) -> None:
    # VC Lab's download holds the credential file as uploaded: no address. Without one Certify publishes nothing for
    # Mimoto to fetch, so the Background would sit on the VDR unprinted. A different address in the file is replaced.
    other = {**SET_CREDENTIAL, "display": [{"name": "x", "background_image": {"uri": "https://elsewhere.example/p.png"}}]}
    for credential in (SET_CREDENTIAL, other, {**SET_CREDENTIAL, "display": []}):
        assert root.publish(a_set(credential=json.dumps(credential).encode())).returncode == 0
        assert written_credential(root)["display"][0]["background_image"] == {"uri": BACKGROUND_URI}, credential


@with_root
def test_a_set_without_a_background_keeps_the_credentials_display_as_it_is(root: Root) -> None:
    assert root.publish(a_set(background=None)).returncode == 0
    assert written_credential(root)["display"] == SET_CREDENTIAL["display"]


@with_root
def test_the_credential_is_always_signed_under_the_live_did(root: Root) -> None:
    # template-sync writes ${CERTIFY_DID} as the live DID; another DID, or none, would sign under a key nobody resolves.
    for credential in ({**SET_CREDENTIAL, "did_url": "did:key:z6MkSomeoneElse"}, SET_CREDENTIAL):
        assert root.publish(a_set(credential=json.dumps(credential).encode())).returncode == 0
        assert written_credential(root)["did_url"] == "${CERTIFY_DID}", credential


@with_root
def test_a_set_without_a_background_removes_the_published_one_and_says_so(root: Root) -> None:
    (root.templates / "ait-transcript").mkdir()
    (root.templates / "ait-transcript" / "background.png").write_bytes(PNG)
    run = root.publish(a_set(background=None))
    assert run.returncode == 0, run.stderr
    assert not (root.templates / "ait-transcript" / "background.png").exists()
    assert "no Background" in run.stdout and "removed" in run.stdout, run.stdout
    again = root.publish(a_set(background=None))  # nothing to remove the second time: the same state, no error
    assert again.returncode == 0, again.stderr


@with_root
def test_a_set_whose_credential_names_the_published_background_keeps_it(root: Root) -> None:
    # An organisation's paper placed by hand, with the credential file's address pointing at it, has no copy in git.
    (root.templates / "ait-transcript").mkdir()
    (root.templates / "ait-transcript" / "background.png").write_bytes(PNG)
    named = {**SET_CREDENTIAL, "display": [{"name": "x", "background_image": {"uri": BACKGROUND_URI}}]}
    run = root.publish(a_set(background=None, credential=json.dumps(named).encode()))
    assert run.returncode == 0, run.stderr
    assert (root.templates / "ait-transcript" / "background.png").read_bytes() == PNG
    assert "keeping" in run.stdout and "names" in run.stdout, run.stdout
    elsewhere = {**SET_CREDENTIAL, "display": [{"name": "x", "background_image": {"uri": "https://elsewhere.example/p.png"}}]}
    assert root.publish(a_set(background=None, credential=json.dumps(elsewhere).encode())).returncode == 0
    assert not (root.templates / "ait-transcript" / "background.png").exists(), "an address elsewhere doesn't keep it"


def kept_or_removed(root: Root, uri: str, env: dict[str, str] | None = None) -> bool:
    """Publish a set without a Background whose credential file names `uri`; True when the placed paper stays."""
    placed = root.templates / "ait-transcript" / "background.png"
    placed.parent.mkdir(exist_ok=True)
    placed.write_bytes(PNG)
    named = {**SET_CREDENTIAL, "display": [{"name": "x", "background_image": {"uri": uri}}]}
    run = root.publish(a_set(background=None, credential=json.dumps(named).encode()), env=env)
    assert run.returncode == 0 and "Traceback" not in run.stderr, (uri, run.stderr)
    assert ("keeping" in run.stdout) == placed.exists() and ("removed" in run.stdout) != placed.exists(), (uri, run.stdout)
    return placed.exists()


@with_root
def test_the_address_template_sync_publishes_for_the_background_keeps_it(root: Root) -> None:
    """Template-sync's own rewrite decides: whatever it turns into this stack's VDR address for the file keeps the
    hand-placed paper, whatever the query or the spaces around it; any other address removes it."""
    path = "/templates/ait-transcript/background.png"
    cases = {
        "http://vdr.localhost" + path: True,
        "http://vdr.localhost" + path + "?v=2": True,
        f" http://vdr.localhost{path} ": True,
        "${VDR_BASE_URL}" + path: True,
        "${CDN_BASE_URL}" + path: True,
        "http://cdn.localhost" + path: True,
        "https://vdr.localhost" + path: False,  # sync leaves it as it is: not this stack's VDR
        "https://evil.example" + path: False,
        "https://evil.example/x" + path: False,
        "http://vdr.localhost/x" + path: False,
        "http://vdr.localhost/templates/ait-student-id/background.png": False,
        "http://[vdr.localhost" + path: False,  # not an address: no error, and the check runs before anything is written
    }
    for uri, kept in cases.items():
        assert kept_or_removed(root, uri) == kept, uri


@with_root
def test_the_stacks_own_vdr_base_decides_what_keeps_the_background(root: Root) -> None:
    base = {"VDR_BASE_URL": "https://vdr.example.test"}
    path = "/templates/ait-transcript/background.png"
    for uri in ("${VDR_BASE_URL}" + path, "http://vdr.localhost" + path, "http://cdn.localhost" + path, "https://vdr.example.test" + path):
        assert kept_or_removed(root, uri, base), uri
    assert not kept_or_removed(root, "https://vdr.localhost" + path, base)


@with_root
def test_a_credential_file_with_a_utf8_bom_is_published_without_one(root: Root) -> None:
    bom = b"\xef\xbb\xbf" + json.dumps(SET_CREDENTIAL).encode()
    run = root.publish(a_set(credential=bom))
    assert run.returncode == 0, run.stderr
    written = (root.out / "ait-transcript.json").read_bytes()
    assert not written.startswith(b"\xef\xbb\xbf") and json.loads(written)["credential_config_key_id"] == "ait-transcript"


def test_what_it_refuses_leaves_everything_as_it_was() -> None:
    cases = {
        "not a zip": (b"this is not a zip", "not a zip"),
        "no template": (a_set(template=None), "template"),
        "two templates": ({**a_set(), "template/second.html": b"<p>2</p>"}, "more than one template"),
        "no credential": (a_set(credential=None), "credential"),
        "credential that isn't JSON": (a_set(credential=b"{not json"), "credential"),
        "credential without an id": (a_set(credential=b'{"display": []}'), "credential_config_key_id"),
        "an id that is a path": (a_set(credential=b'{"credential_config_key_id": "../x"}'), "credential_config_key_id"),
        "a background that is a PDF": (a_set(background=b"%PDF-1.4 not an image"), "PNG or JPEG"),
        "a file outside the set's folders": ({**a_set(), "notes/readme.txt": b"hi"}, "notes/readme.txt"),
    }
    for label, (files, expected) in cases.items():
        root = Root()
        try:
            before = root.tree()
            run = root.publish(files)
            assert run.returncode == 1, (label, run.returncode, run.stdout, run.stderr)
            assert expected in run.stderr and "Traceback" not in run.stderr, (label, run.stderr)
            assert root.tree() == before, label
            assert not root.out.exists(), label
        finally:
            root.close()


@with_root
def test_an_issuer_id_that_is_not_a_plain_name_is_refused(root: Root) -> None:
    before = root.tree()
    for bad in ("../x", "a/b", "", "a b", "-x"):
        run = root.publish(a_set(), issuer_id=bad)
        assert run.returncode == 1 and "issuer id" in run.stderr and "Traceback" not in run.stderr, (bad, run.stderr)
        assert root.tree() == before, bad


def test_the_script_refuses_a_stack_without_the_mock_services_before_touching_anything() -> None:
    """scripts/publish-set.sh runs against the local stack only, as scripts/mimoto-up.sh does: with COMPOSE_FILE lacking
    compose.mock.yaml (a deployment's .env) it refuses, and writes nothing, not even the template."""
    bash = shutil.which("bash")
    assert bash, "bash is needed"
    root = Root()
    try:
        (root.dir / "scripts").mkdir()
        for name in ("publish-set.sh", "local-stack.sh"):
            if (REPO_ROOT / "scripts" / name).exists():
                shutil.copy(REPO_ROOT / "scripts" / name, root.dir / "scripts" / name)
        (root.dir / "src" / "tools").mkdir(parents=True)
        shutil.copy(TOOL, root.dir / "src" / "tools") if TOOL.exists() else None
        (root.dir / ".env").write_text("INSTALLATION=ait" + chr(10) + "COMPOSE_FILE=compose.yaml" + chr(10), encoding="utf-8")
        (root.dir / "set.zip").write_bytes(make_zip(a_set()))
        before = root.tree()
        run = subprocess.run([bash, "scripts/publish-set.sh", "set.zip", "AITUniversity"], cwd=root.dir, capture_output=True, text=True)
        out = run.stdout + run.stderr
        assert run.returncode == 1 and "publish-set: " in out and "compose.mock.yaml" in out and "Traceback" not in out, (run.returncode, out)
        assert root.tree() == before
    finally:
        root.close()


def test_the_script_without_its_two_arguments_prints_its_usage() -> None:
    bash = shutil.which("bash")
    assert bash, "bash is needed"
    run = subprocess.run([bash, str(SCRIPT)], cwd=REPO_ROOT, capture_output=True, text=True)
    out = run.stdout + run.stderr
    assert run.returncode == 1 and "Usage" in out and "<set.zip>" in out and "<issuer id>" in out, (run.returncode, out)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
