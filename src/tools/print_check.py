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
import signal
import struct
import sys
import zlib
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

try:
    import httpx
    from pypdf import PdfReader
except ImportError as e:  # an ait-vc image older than this script
    print(f"FAIL setup: {e.name} isn't in this ait-vc image: rebuild it with scripts/deploy.sh <installation> --build")
    sys.exit(1)

KEYCLOAK = "http://auth.localhost"
CERTIFY = "http://issuer.localhost"
VDR_TEMPLATES = "http://vdr.localhost/templates"
MIMOTO = "http://mimoto.localhost/v1/mimoto"
ADAPTER = "http://adapter.localhost"
# What Mimoto fetches from its template address besides the template (compose.mimoto.yaml).
MIMOTO_FILES = ("mimoto-issuers-config.json", "mimoto-trusted-verifiers.json", "mosip-cbeff.xsd")
MARKER = "PRINT-CHECK-TEMPLATE"
TIMEOUT = 120
# The font the test template loads through @font-face (scripts/print-check.sh puts it on the VDR for the run) and
# the name it embeds under: TLWG's Loma, from Debian's fonts-tlwg-loma-ttf.
FONT_NAME = "Loma"
# The made-up Background's size in pixels: A4's proportions, so it can't be mistaken for the page.
BACKGROUND_PX = (413, 585)


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


# Mimoto 0.21's error codes on /credentials/download, by the step that failed (each seen on the local stack):
# the authorization server refusing Mimoto's code exchange, Certify refusing the credential request, and the
# credential's signature failing. Any other code is reported under issuance, with Mimoto's body.
ERROR_STEPS = {
    "invalid_request": "token exchange",
    "resource_not_found": "issuance",
    "signature_verification_failed": "signature check",
}
# Mimoto's PDF generation failed. When it got no template from the VDR (neither the credential's nor its fallback
# credential-template.html), the message is a NullPointerException on the missing template string; a template it
# fetched but couldn't render (a Velocity error) carries the error's line instead.
PDF_GENERATION = "RESIDENT-APP-028"


def failed_step(code: str, message: str) -> str:
    if code == PDF_GENERATION:
        return "template fetch" if "is null" in message else "PDF content"
    return ERROR_STEPS.get(code, "issuance")


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
    code, message = (errors[0].get("errorCode", ""), errors[0].get("errorMessage", "")) if errors else ("", "")
    step = failed_step(code, message)
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
    display = meta.json()["credential_configurations_supported"][entry["credentialConfig"]]["display"][0]
    return {
        "background_uri": (display.get("background_image") or {}).get("uri", ""),
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


def make_background_png(width: int, height: int) -> bytes:
    """A made-up Background: white with a light grid and a darker band along the top."""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            v = 170 if y < 30 else 200 if x % 40 == 0 or y % 40 == 0 else 255
            row += bytes([v, v, v])
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def _then(m: list[float], n: list[float]) -> list[float]:
    """The matrix that applies m first, then n, both as PDF's [a b c d e f]."""
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2],
            m[2] * n[1] + m[3] * n[3], m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


def drawn_images(reader: PdfReader) -> list[dict]:
    """Every image the first page draws: its pixel size and the rectangle it covers on the page, in points."""
    from pypdf.generic import ContentStream

    page = reader.pages[0]
    found: list[dict] = []

    def walk(content, resources, base: list[float]) -> None:
        ctm, saved = base, []
        for operands, op in ContentStream(content, reader).operations:
            if op == b"q":
                saved.append(ctm)
            elif op == b"Q" and saved:
                ctm = saved.pop()
            elif op == b"cm":
                ctm = _then([float(v) for v in operands], ctm)
            elif op == b"Do":
                xobject = (resources.get("/XObject") or {}).get(operands[0])
                if xobject is None:
                    continue
                xobject = xobject.get_object()
                if xobject.get("/Subtype") == "/Image":
                    # An image is drawn into the unit square, so the CTM is its rectangle.
                    found.append({"px": (int(xobject["/Width"]), int(xobject["/Height"])),
                                  "x": ctm[4], "y": ctm[5], "w": ctm[0], "h": ctm[3]})
                elif xobject.get("/Subtype") == "/Form":
                    matrix = [float(v) for v in xobject.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                    walk(xobject, xobject.get("/Resources") or resources, _then(matrix, ctm))

    walk(page.get_contents(), page.get("/Resources") or {}, [1, 0, 0, 1, 0, 0])
    return found


def embedded_fonts(reader: PdfReader) -> set[str]:
    """The names of the fonts whose programs the PDF carries, without the subset prefix."""
    names: set[str] = set()
    for page in reader.pages:
        for font in ((page.get("/Resources") or {}).get("/Font") or {}).values():
            font = font.get_object()
            for face in [font, *(d.get_object() for d in font.get("/DescendantFonts", []))]:
                descriptor = face["/FontDescriptor"].get_object() if "/FontDescriptor" in face else {}
                if any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                    names.add(str(face.get("/BaseFont", "")).lstrip("/").split("+")[-1])
    return names


def line_after(text: str, label: str) -> str | None:
    found = re.search(re.escape(label) + r":\s*(.+?)(?=\s+PRINT-CHECK-|\s+\w+:\s|$)", text)
    return found.group(1).strip() if found else None


def check_background_font_and_thai(label: str, pdf: bytes, text: str, ctx: dict) -> None:
    """The swapped print carries the Background at the page's full size, the @font-face font, and Thai text."""
    reader = PdfReader(io.BytesIO(pdf))
    page_w, page_h = (float(v) for v in reader.pages[0].mediabox[2:])
    images = drawn_images(reader)
    full = [i for i in images if i["px"] == BACKGROUND_PX and abs(i["x"]) < 1.5 and abs(i["y"]) < 1.5
            and abs(i["w"] - page_w) < 1.5 and abs(i["h"] - page_h) < 1.5]
    if not full:
        shown = [(i["px"], round(i["x"]), round(i["y"]), round(i["w"]), round(i["h"])) for i in images]
        raise StepFailed("PDF content", f"the Background isn't drawn at the page's full size ({page_w:.0f} x "
                                        f"{page_h:.0f} pt, from {ctx['background_uri']}); the PDF's images (pixels, "
                                        f"x, y, w, h): {shown}")
    print(f"PASS PDF content ({label}): the Background ({BACKGROUND_PX[0]}x{BACKGROUND_PX[1]} px) is drawn at the "
          f"page's full size, {page_w:.0f} x {page_h:.0f} pt")

    fonts = embedded_fonts(reader)
    if FONT_NAME not in fonts:
        raise StepFailed("PDF content", f"the @font-face font {FONT_NAME} isn't embedded; embedded fonts: "
                                        f"{sorted(fonts)}")
    print(f"PASS PDF content ({label}): the @font-face font {FONT_NAME} is embedded")

    entity = line_after(text, "PRINT-CHECK-THAI-ENTITY")
    raw = line_after(text, "PRINT-CHECK-THAI-RAW")
    if not entity or not re.search(r"[฀-๿]", entity):
        raise StepFailed("PDF content", f"Thai written as HTML entities isn't in the page text (got {entity!r})")
    if raw != entity:
        raise StepFailed("template fetch", f"Thai typed into the template prints as {raw!r}, not {entity!r}: "
                                           "the VDR's /templates/ must send charset=utf-8")
    note = ctx["thai_note"]
    if f"notes: {note}" not in text:
        raise StepFailed("PDF content", f"the Thai claim value {note!r} isn't in the page text")
    print(f"PASS PDF content ({label}): Thai text is in the page, typed in the template and as a claim value")


def check_charset(template: str) -> None:
    """The VDR's /templates/ declares UTF-8 for an HTML template, which Mimoto otherwise reads as ISO-8859-1."""
    kind = _get(f"{VDR_TEMPLATES}/{template}").headers.get("content-type", "")
    if kind.replace(" ", "").lower() != "text/html;charset=utf-8":
        raise StepFailed("template fetch", f"the VDR answers Content-Type {kind!r} for /templates/{template}, "
                                           "not 'text/html; charset=utf-8'")
    print(f"PASS template fetch: the VDR sends Content-Type {kind} for the template")


def background_file(templates: Path, uri: str) -> Path:
    """Where the Background goes in the VDR's templates folder, from the address the credential file publishes."""
    if not uri.startswith(f"{VDR_TEMPLATES}/"):
        raise StepFailed("setup", f"the published Background address {uri!r} isn't under {VDR_TEMPLATES}/: run "
                                  "scripts/print-check.sh, which publishes a test address")
    return templates / uri[len(VDR_TEMPLATES) + 1:]


def run(installation: Path, templates: Path, test_template: Path, out: Path, student: str | None,
        templates_shown: str, thai_note: str) -> None:
    ctx = context(installation, student)
    ctx["thai_note"] = " ".join(thai_note.split())
    target = templates / ctx["template"]
    if MARKER.encode() in target.read_bytes():
        shown = f"{templates_shown}/{ctx['template']}"
        raise StepFailed("setup", f"{shown} is still the print check's test template, left by an interrupted run: "
                                  f"restore it with git checkout -- {shown}")
    check_vdr(ctx["template"])
    background = background_file(templates, ctx["background_uri"]) if ctx["background_uri"] else None
    if background is None:
        raise StepFailed("setup", "the published credential file has no display[0].background_image.uri: run "
                                  "scripts/print-check.sh, which publishes a test address for the run")
    made_up = make_background_png(*BACKGROUND_PX)
    kept = background.read_bytes() if background.exists() else None  # a real Background published here stays
    if kept == made_up:
        raise StepFailed("setup", f"{ctx['background_uri']}'s file is still the print check's made-up Background, left "
                                  "by an interrupted run: delete it, and publish the real one again if there was one")
    status = _get(f"{MIMOTO}/issuers").status_code
    if status != 200:
        raise StepFailed("setup", f"Mimoto's issuers list answered {status}: run scripts/mimoto-up.sh")

    text = print_once("original", ctx, out)
    if MARKER in text:
        raise StepFailed("template fetch", f"the original print already carries {MARKER}")

    original = target.read_bytes()
    made_dirs = [d for d in reversed(background.parents) if d != templates and templates in d.parents
                 and not d.exists()]
    try:
        background.parent.mkdir(parents=True, exist_ok=True)
        background.write_bytes(made_up)
        target.write_bytes(test_template.read_bytes())  # in place: the VDR's bind mount keeps the same file
        print(f"swapped the test template onto the VDR as {ctx['template']}, and a made-up Background to "
              f"{ctx['background_uri']}; Mimoto keeps running")
        text = print_once("swapped", ctx, out)
        if MARKER not in text:
            raise StepFailed("template fetch", "the print after the swap doesn't carry the test template's marker")
        print(f"PASS template fetch: the swapped template printed at the next print ({MARKER})")
        check_background_font_and_thai("swapped", (out / "swapped.pdf").read_bytes(), text, ctx)
        check_charset(ctx["template"])
    finally:
        target.write_bytes(original)
        if kept is None:
            background.unlink(missing_ok=True)
        else:
            background.write_bytes(kept)  # exactly as it was: it's git-ignored, so nothing else holds it
        for d in reversed(made_dirs):
            try:
                d.rmdir()
            except OSError:
                pass
    if target.read_bytes() != original:
        raise StepFailed("setup", f"{ctx['template']} wasn't restored: git checkout it")
    print(f"restored the original {ctx['template']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--templates", type=Path, required=True, help="the VDR's templates folder (read-write)")
    parser.add_argument("--test-template", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--templates-shown", default="the VDR's templates folder",
                        help="the templates folder as the repository names it, for messages")
    parser.add_argument("--student")
    parser.add_argument("--thai-note", required=True,
                        help="the made-up Thai text print-check.sh published as the credential's notes claim")
    args = parser.parse_args()
    # As PID 1 in a container Python ignores SIGTERM; exit on it instead, so `docker stop` still restores the
    # template. A SIGKILL can't be caught: the next run notices the leftover (run()).
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    try:
        run(args.installation, args.templates, args.test_template, args.out, args.student, args.templates_shown, args.thai_note)
    except StepFailed as e:
        print(f"FAIL {e}")
        return 1
    print("print check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
