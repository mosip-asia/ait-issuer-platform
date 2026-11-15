"""Inji Web OpenId4VCI readiness — prevents VC download regressions.

Config checks (no Docker): token_endpoint same-origin :4004, Keycloak redirect, Mimoto Keycloak URLs.

Live checks (--live, stack must be up): Mimoto issuers/configuration APIs, that certify-nginx
serves none of Mimoto's config files, and that credentials/download is reachable via the Inji Web
proxy (not blocked with 403).

Full browser OAuth + PDF is still manual; this guards the misconfigurations that
caused empty issuers, Keycloak not loading, and "session is not valid" on download.

Checks the installation INSTALLATION names (default ait), as smoke.sh runs it.

Run:
  python3 vc-stack/test_inji_web_vc_readiness.py
  python3 vc-stack/test_inji_web_vc_readiness.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE_DIR = REPO_ROOT / "deploy" / "base"
MIMOTO_PROPS_DIR = BASE_DIR
INSTALLATION_DIR = REPO_ROOT / "deploy" / os.environ.get("INSTALLATION", "ait")

INJI_WEB_ORIGIN = os.environ.get("INJI_WEB_URL", "http://wallet.localhost")
KEYCLOAK_PUBLIC = os.environ.get("KEYCLOAK_PUBLIC_BASE_URL", "http://auth.localhost")
ISSUER_ID = json.loads((INSTALLATION_DIR / "mimoto-issuers-config.json.template").read_text(encoding="utf-8"))[
    "issuers"][0]["issuer_id"]
CREDENTIAL_CONFIGS = {f["credentialConfig"] for f in json.loads((INSTALLATION_DIR / "smoke.json").read_text(encoding="utf-8"))}
MIMOTO_ISSUERS = f"{INJI_WEB_ORIGIN}/v1/mimoto/issuers"
MIMOTO_CONFIG = f"{INJI_WEB_ORIGIN}/v1/mimoto/issuers/{ISSUER_ID}/configuration"
MIMOTO_DOWNLOAD = f"{INJI_WEB_ORIGIN}/v1/mimoto/credentials/download"
EXPECTED_TOKEN = f"{INJI_WEB_ORIGIN}/v1/mimoto/get-token/{ISSUER_ID}"


def _http_json(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def test_issuers_config_token_endpoint_uses_inji_web_proxy() -> None:
    cfg = json.loads((INSTALLATION_DIR / "mimoto-issuers-config.json").read_text(encoding="utf-8"))
    issuer = cfg["issuers"][0]
    token_ep = issuer["token_endpoint"]
    valid_tokens = {
        f"http://wallet.localhost/v1/mimoto/get-token/{ISSUER_ID}",
        f"http://localhost:4004/v1/mimoto/get-token/{ISSUER_ID}",
        EXPECTED_TOKEN,
    }
    assert token_ep in valid_tokens, (
        f"token_endpoint must be same-origin Inji Web proxy (expected one of {valid_tokens}, got {token_ep}). "
        "Re-run vc-stack/bootstrap.sh to refresh issuer config."
    )
    assert issuer["authorization_audience"].startswith("http://keycloak:8080/"), issuer["authorization_audience"]
    assert issuer["proxy_token_endpoint"].startswith("http://keycloak:8080/"), issuer["proxy_token_endpoint"]
    valid_redirects = {
        f"http://wallet.localhost/redirect",
        f"http://localhost:4004/redirect",
        f"{INJI_WEB_ORIGIN}/redirect",
    }
    assert issuer["redirect_uri"] in valid_redirects


def test_mimoto_cors_allows_inji_web_host_port() -> None:
    props = (MIMOTO_PROPS_DIR / "mimoto-default.properties").read_text(encoding="utf-8")
    assert "mosip.security.origins=" in props and (
        "http://wallet.localhost" in props or "http://localhost:4004" in props
    ), (
        "Mimoto CORS must allow Inji Web or VC download returns 403 "
        "and Inji Web shows 'session is not valid or session is completed'."
    )


def test_mimoto_keycloak_external_is_browser_url() -> None:
    props = (MIMOTO_PROPS_DIR / "mimoto-default.properties").read_text(encoding="utf-8")
    assert "keycloak.external.url=http://auth.localhost" in props or "keycloak.external.url=http://localhost:8080" in props
    assert "keycloak.internal.url=http://keycloak:8080" in props


def test_keycloak_wallet_demo_redirect_includes_inji_web() -> None:
    realm_file = INSTALLATION_DIR / "mock" / "keycloak-realm.json"
    if not realm_file.is_file():
        realm_file = INSTALLATION_DIR / "keycloak-realm.json"
    realm = json.loads(realm_file.read_text(encoding="utf-8"))
    client = next(c for c in realm["clients"] if c["clientId"] == "wallet-demo")
    redirects = client["redirectUris"]
    assert "http://wallet.localhost/redirect" in redirects or "http://localhost:4004/redirect" in redirects


def test_live_issuer_list_and_configuration() -> None:
    status, payload = _http_json(MIMOTO_ISSUERS)
    assert status == 200, f"GET issuers failed: {status} {payload}"
    issuers = payload.get("response", {}).get("issuers", [])
    assert any(i.get("issuer_id") == ISSUER_ID for i in issuers)

    status, payload = _http_json(MIMOTO_CONFIG)
    assert status == 200, f"GET configuration failed: {status} {payload}"
    assert not payload.get("errors"), f"configuration errors (Keycloak well-known?): {payload.get('errors')}"
    resp = payload.get("response") or {}
    auth_ep = resp.get("authorization_endpoint", "")
    assert auth_ep.startswith(f"{KEYCLOAK_PUBLIC}/"), auth_ep
    supported = resp.get("credentials_supported") or []
    assert {c.get("name") for c in supported} >= CREDENTIAL_CONFIGS, supported

    status, payload = _http_json(f"{MIMOTO_ISSUERS}/{ISSUER_ID}")
    assert status == 200
    token_ep = payload.get("response", {}).get("token_endpoint", "")
    assert token_ep == EXPECTED_TOKEN, token_ep


def test_live_download_endpoint_reachable_via_inji_web_proxy() -> None:
    """Without a valid OAuth/PKCE session Mimoto rejects the body — but must not 403 (auth/CORS break)."""
    data = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        MIMOTO_DOWNLOAD,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": INJI_WEB_ORIGIN,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
    assert status != 403, f"credentials/download returned 403 — Inji Web proxy or Mimoto auth misconfigured: {payload}"
    errors = payload.get("errors") or []
    messages = " ".join(str(e.get("errorMessage", "")) for e in errors).lower()
    assert "invalid code verifier" in messages or "session" in messages or status in (400, 500), (
        f"unexpected download error (want PKCE/session rejection, not infra failure): {status} {payload}"
    )


def test_live_certify_nginx_serves_none_of_mimotos_files() -> None:
    """Mimoto's config server is demo's public-gateway; certify-nginx (:9091) serves only Certify."""
    for path in ("/mimoto-issuers-config.json", "/mimoto-default.properties"):
        try:
            with urllib.request.urlopen(f"http://localhost:9091{path}", timeout=15) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 404, f"certify-nginx answered {status} for {path}; Mimoto's files belong to demo's nginx"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="HTTP checks against running stack")
    args = parser.parse_args()

    test_issuers_config_token_endpoint_uses_inji_web_proxy()
    test_mimoto_cors_allows_inji_web_host_port()
    test_mimoto_keycloak_external_is_browser_url()
    test_keycloak_wallet_demo_redirect_includes_inji_web()

    if args.live:
        test_live_issuer_list_and_configuration()
        test_live_certify_nginx_serves_none_of_mimotos_files()
        test_live_download_endpoint_reachable_via_inji_web_proxy()

    mode = "config + live" if args.live else "config"
    print(f"vc-stack/test_inji_web_vc_readiness.py: all checks passed ({mode})")


if __name__ == "__main__":
    main()
