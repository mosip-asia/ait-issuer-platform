"""The Wallet's print, checked end to end on the local stack. Local only; made-up data only.

Run it through scripts/print-check.sh, after scripts/mimoto-up.sh. It plays Inji Web against the real Mimoto:

1. signs a made-up student in at the local Keycloak with the issuers list's client (PKCE), carrying Keycloak's
   cookies by hand because they are marked Secure on plain http, and stops at the redirect to read the code;
2. posts the code to Mimoto's /credentials/download with the form fields Inji Web sends. Mimoto exchanges the code,
   gets the credential from Certify, checks its signature, fetches the template from the VDR and answers with a PDF;
3. checks the PDF: 200 application/pdf, and the student's name in the page text.

It prints twice: with the credential's own template, then with a generic test template swapped onto the VDR under the
same name while Mimoto keeps running, whose marker must show at that print. The original template is always put back.
A failure names its step: sign-in, token exchange, issuance, signature check, template fetch or PDF content; "setup"
means the local stack isn't ready to try.

Inputs are the installation's own files, mounted by print-check.sh: smoke.json (the first entry naming a
mimotoTemplate gives the credential, its scope and the made-up student), the stand-in realm (the student's password),
the issuers list (client and redirect), and the VDR's templates folder (read-write, for the swap).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from pypdf import PdfReader

KEYCLOAK = "http://auth.localhost"
CERTIFY = "http://issuer.localhost"
VDR_TEMPLATES = "http://vdr.localhost/templates"
MIMOTO = "http://mimoto.localhost/v1/mimoto"
ADAPTER = "http://adapter.localhost"
# What Mimoto fetches from its template address besides the template (compose.mimoto.yaml).
MIMOTO_FILES = ("mimoto-issuers-config.json", "mimoto-trusted-verifiers.json", "mosip-cbeff.xsd")
MARKER = "PRINT-CHECK-TEMPLATE"
TIMEOUT = 120


class StepFailed(Exception):
    def __init__(self, step: str, detail: str):
        super().__init__(f"{step}: {detail}")
        self.step = step


def _get(url: str, **kw) -> httpx.Response:
    try:
        return httpx.get(url, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as e:
        raise StepFailed("setup", f"GET {url} failed: {e!r}") from e


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _cookies(resp: httpx.Response) -> str:
    """Every cookie the response sets, as one Cookie header. httpx, like curl, won't send a Secure cookie over http."""
    return "; ".join(c.split(";", 1)[0].strip() for c in resp.headers.get_list("set-cookie"))


def sign_in(auth_server: str, client_id: str, redirect_uri: str, scope: str, student: str, password: str
            ) -> tuple[str, str]:
    """Log the student in at the authorization server's login form; return (code, PKCE verifier)."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    query = urlencode({"client_id": client_id, "response_type": "code", "scope": scope, "redirect_uri": redirect_uri,
                       "code_challenge": challenge, "code_challenge_method": "S256", "state": "print-check"})
    page = _get(f"{auth_server}/protocol/openid-connect/auth?{query}")
    form = re.search(r'<form[^>]*action="([^"]+)"', page.text)
    if page.status_code != 200 or not form:
        raise StepFailed("sign-in", f"no login form (HTTP {page.status_code})")
    try:
        done = httpx.post(html.unescape(form.group(1)), data={"username": student, "password": password},
                          headers={"Cookie": _cookies(page)}, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise StepFailed("sign-in", f"login post failed: {e!r}") from e
    location = done.headers.get("location", "")
    code = parse_qs(urlparse(location).query).get("code", [""])[0]
    if done.status_code != 302 or not code:
        title = re.search(r"<title>([^<]*)", done.text)
        feedback = re.search(r'kc-feedback-text">([^<]*)', done.text) or re.search(r'input-error[^>]*>\s*([^<]+)',
                                                                                   done.text)
        detail = " / ".join(m.group(1).strip() for m in (title, feedback) if m)
        raise StepFailed("sign-in", f"no code (HTTP {done.status_code}, {detail or location.split('?')[0]})")
    return code, verifier


# Mimoto 0.21's error codes on /credentials/download, by the step that failed.
ERROR_STEPS = {
    "signature_verification_failed": "signature check",
}


def download(issuer_id: str, credential: str, redirect_uri: str, code: str, verifier: str) -> bytes:
    """Inji Web's guest download: Mimoto answers with the PDF, or with an error naming what failed."""
    form = {"issuer": issuer_id, "credential": credential, "grant_type": "authorization_code", "code": code,
            "redirect_uri": redirect_uri, "code_verifier": verifier, "locale": "en",
            "vcStorageExpiryLimitInTimes": "-1"}
    try:
        resp = httpx.post(f"{MIMOTO}/credentials/download", data=form, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise StepFailed("setup", f"Mimoto didn't answer: {e!r}") from e
    if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("application/pdf"):
        return resp.content
    try:
        errors = resp.json().get("errors") or []
    except ValueError:
        errors = []
    code = errors[0].get("errorCode", "") if errors else ""
    step = ERROR_STEPS.get(code, "issuance")
    raise StepFailed(step, f"Mimoto answered {resp.status_code} {resp.headers.get('content-type', '')}: "
                           f"{resp.text[:400]}")


def page_text(pdf: bytes) -> str:
    """The PDF's text with whitespace collapsed, so a value broken over lines still matches."""
    try:
        reader = PdfReader(io.BytesIO(pdf))
        return " ".join(" ".join((p.extract_text() or "").split()) for p in reader.pages)
    except Exception as e:  # noqa: BLE001 - any parse error is a PDF content failure
        raise StepFailed("PDF content", f"not a readable PDF: {e!r}") from e


def print_once(label: str, ctx: dict, out: Path) -> str:
    code, verifier = sign_in(ctx["auth_server"], ctx["client_id"], ctx["redirect_uri"], ctx["scope"],
                             ctx["student"], ctx["password"])
    print(f"PASS sign-in ({label}): {ctx['student']} got a code")
    pdf = download(ctx["issuer_id"], ctx["credential"], ctx["redirect_uri"], code, verifier)
    (out / f"{label}.pdf").write_bytes(pdf)
    print(f"PASS token exchange, issuance, signature check ({label}): 200 application/pdf, {len(pdf)} bytes, "
          f"saved {label}.pdf")
    text = page_text(pdf)
    if ctx["name"] not in text:
        raise StepFailed("PDF content", f"the student's name isn't in the page text ({label})")
    print(f"PASS PDF content ({label}): the student's name is on the page")
    return text


def context(installation: Path, student: str | None) -> dict:
    """What to print and as whom, from the installation's files and the running stack."""
    entry = next((e for e in json.loads((installation / "smoke.json").read_text(encoding="utf-8"))
                  if e.get("mimotoTemplate")), None)
    if entry is None:
        raise StepFailed("setup", "the installation's smoke.json names no mimotoTemplate")
    eligible = entry["eligible"]
    student = student or (eligible if isinstance(eligible, str) else eligible[0])
    realm = json.loads((installation / "mock" / "keycloak-realm.json").read_text(encoding="utf-8"))
    user = next((u for u in realm["users"] if u["username"] == student), None)
    if user is None:
        raise StepFailed("setup", f"{student} isn't a user of the stand-in realm")
    issuer = json.loads((installation / "vcga" / "issuers.json").read_text(encoding="utf-8"))["issuers"][0]

    meta = _get(f"{CERTIFY}/.well-known/openid-credential-issuer")
    if meta.status_code != 200:
        raise StepFailed("setup", f"Certify's metadata answered {meta.status_code}")
    auth_server = meta.json()["authorization_servers"][0].rstrip("/")
    if not auth_server.startswith(f"{KEYCLOAK}/"):
        raise StepFailed("setup", f"Certify trusts {auth_server}, not the local Keycloak: run scripts/mimoto-up.sh")
    record = _get(f"{ADAPTER}/student/{student}/transcript")
    if record.status_code != 200:
        raise StepFailed("setup", f"the mock Adapter has no record for {student} ({record.status_code})")
    return {
        "auth_server": auth_server,
        "client_id": issuer["client_id"],
        "redirect_uri": issuer["redirect_uri"],
        "issuer_id": issuer["issuer_id"],
        "credential": entry["credentialConfig"],
        "scope": entry["scope"],
        "template": entry["mimotoTemplate"],
        "student": student,
        "password": user["credentials"][0]["value"],
        "name": " ".join(record.json()["fullName"].split()),
    }


def check_vdr(template: str) -> None:
    """The VDR's /templates/ serves the template and Mimoto's own files (ask T2)."""
    for name in (template, *MIMOTO_FILES):
        status = _get(f"{VDR_TEMPLATES}/{name}").status_code
        if status != 200:
            raise StepFailed("template fetch", f"the VDR answers {status} for /templates/{name}")
    print(f"PASS template fetch: the VDR serves {template} and {', '.join(MIMOTO_FILES)}")


def run(installation: Path, templates: Path, test_template: Path, out: Path, student: str | None) -> None:
    ctx = context(installation, student)
    check_vdr(ctx["template"])
    status = _get(f"{MIMOTO}/issuers").status_code
    if status != 200:
        raise StepFailed("setup", f"Mimoto's issuers list answered {status}: run scripts/mimoto-up.sh")

    text = print_once("original", ctx, out)
    if MARKER in text:
        raise StepFailed("template fetch", f"the original print already carries {MARKER}")

    target = templates / ctx["template"]
    original = target.read_bytes()
    try:
        target.write_bytes(test_template.read_bytes())  # in place: the VDR's bind mount keeps the same file
        print(f"swapped the test template onto the VDR as {ctx['template']}; Mimoto keeps running")
        text = print_once("swapped", ctx, out)
        if MARKER not in text:
            raise StepFailed("template fetch", "the print after the swap doesn't carry the test template's marker")
        print(f"PASS template fetch: the swapped template printed at the next print ({MARKER})")
    finally:
        target.write_bytes(original)
    if target.read_bytes() != original:
        raise StepFailed("setup", f"{ctx['template']} wasn't restored: git checkout it")
    print(f"restored the original {ctx['template']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True, help="the VDR's templates folder (read-write)")
    parser.add_argument("--test-template", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--student")
    args = parser.parse_args()
    try:
        run(args.installation, args.templates, args.test_template, args.out, args.student)
    except StepFailed as e:
        print(f"FAIL {e}")
        return 1
    print("print check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
