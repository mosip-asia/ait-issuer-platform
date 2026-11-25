"""VC Lab's web API, driven the way the dashboard drives it, with a small made-up set.

Run:
    python3 src/vc-lab/test_main.py

The preview tests need the renderer (src/renderer) at RENDERER_URL and skip without it. Inside Compose, VC Lab has
it: `docker compose run --rm vc-lab python src/vc-lab/test_main.py`. The Background tests also need WeasyPrint's
system libraries (Pango) to draw their paper; the ait-vc image has them.
"""

from __future__ import annotations

import html
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable
from urllib.parse import quote

VC_LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = VC_LAB_DIR.parent.parent
sys.path[:0] = [str(VC_LAB_DIR), str(VC_LAB_DIR.parent)]  # VC Lab, and src/ for template-sync

import main as vc_lab  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader, PdfWriter, Transformation  # noqa: E402

client = TestClient(vc_lab.app)

# ---------------------------------------------------------------------------------------------------------------
# The made-up set

# Reads one claim from $rowProperties, as the Wallet's templates do, and draws the course grid from
# $credentialSubject, which only ait-mimoto gives.
TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>$titleName</title>
<style>@page { size: A4 portrait; margin: 20mm; } .page + .page { page-break-before: always; }</style></head>
<body>
#macro(claimValue $claimName)
#set($__claim = $rowProperties.get($claimName))
#if($__claim && $__claim.size() > 0)
#foreach($__entry in $__claim.entrySet())$__entry.value#break#end
#end
#end
<div class="page">
  <h1 style="color: $textColor">$titleName</h1>
  <p>Holder: #claimValue("holderName")</p>
  <p>Thesis: #claimValue("thesisTitle")</p>
  <table>
#if($credentialSubject.courses)
#foreach($t in $credentialSubject.courses)
    <tr><th colspan="3">$t.label</th></tr>
#foreach($c in $t.items)
    <tr><td>$c.code</td><td>$c.title</td><td>$c.grade</td></tr>
#end
#end
#else
    <tr><td>Courses are not listed in this copy.</td></tr>
#end
  </table>
</div>
<div class="page">
  <img src="data:image/png;base64,$qrCodeImage" alt="QR" />
  <p>Scan the QR code to verify.</p>
</div>
</body></html>
"""

CREDENTIAL = {
    "credential_config_key_id": "example-record",
    "credential_type": "ExampleRecord,VerifiableCredential",
    "display": [{"name": "Example Record", "locale": "en", "background_color": "#ffffff", "text_color": "#123456"}],
    "vc_template": {
        "@context": ["https://www.w3.org/ns/credentials/v2"],
        "issuer": "${_issuer}",
        "type": ["VerifiableCredential", "ExampleRecord"],
        "credentialSubject": {
            "id": "${_holderId}",
            "holderName": "${name}",
            "thesisTitle": "${thesisTitle}",
            "courses": "${courses}",  # template-sync unquotes it, so Certify signs a list
        },
    },
}

TRICKY_TITLE = "Costs in $titleName & #if($x)loops#end"
SUBJECT = {
    "name": "Ada Example",
    "thesisTitle": "On Small Fixtures",
    "courses": [
        {"label": "Term One", "items": [{"code": "XY101", "title": "Fixture Design", "grade": "A"},
                                        {"code": "XY102", "title": TRICKY_TITLE, "grade": "B+"}]},
        {"label": "Term Two", "items": [{"code": "XY201", "title": "Seams", "grade": "A"}]},
    ],
}
SAMPLE = {"@context": ["https://www.w3.org/ns/credentials/v2"], "type": ["VerifiableCredential"],
          "issuer": "did:example:adapter", "credentialSubject": SUBJECT}


def _json(value: object) -> bytes:
    return json.dumps(value).encode("utf-8")


def _upload(**files: tuple[str, bytes]):
    return client.post("/api/set", files={field: (name, data) for field, (name, data) in files.items()})


def _upload_set() -> None:
    client.delete("/api/set")
    res = _upload(template=("record.html", TEMPLATE.encode()), credential=("record.json", _json(CREDENTIAL)),
                  sample=("adapter-response.json", _json(SAMPLE)))
    assert res.status_code == 200, res.text


def _blank_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=300)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _empty_zip() -> bytes:
    out = io.BytesIO()
    zipfile.ZipFile(out, "w").close()
    return out.getvalue()


def _paper_pdf(word: str) -> bytes:
    """Portrait paper carrying `word`, stored the way the real watermark PDF is: a landscape page, its content
    turned a quarter, and /Rotate 90 so a viewer shows it upright."""
    from weasyprint import HTML

    portrait = PdfReader(io.BytesIO(HTML(string=f"<p style='font-size:30pt'>{word}</p>").write_pdf())).pages[0]
    w, h = float(portrait.mediabox.width), float(portrait.mediabox.height)
    writer = PdfWriter()
    stored = writer.add_blank_page(width=h, height=w)
    stored.merge_transformed_page(portrait, Transformation().rotate(90).translate(h, 0))
    stored.rotate(90)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _pages(path: str) -> list:
    res = client.get(path)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    return PdfReader(io.BytesIO(res.content)).pages


def _skip_without(test: str, *needs: str) -> bool:
    """True, after printing SKIP, when this host lacks what the test needs: the renderer, or WeasyPrint."""
    if "renderer" in needs and not os.environ.get("RENDERER_URL"):
        print(f"SKIP {test} (no RENDERER_URL)")
        return True
    if "weasyprint" in needs:
        try:
            import weasyprint  # noqa: F401
        except Exception as e:  # Pango missing on this host; the ait-vc image has it
            print(f"SKIP {test} ({type(e).__name__})")
            return True
    return False


# ---------------------------------------------------------------------------------------------------------------
# Tests that need no renderer


def test_health_and_dashboard() -> None:
    assert client.get("/health").json() == {"status": "UP", "service": "vc-lab"}
    page = client.get("/")
    assert page.status_code == 200 and "VC Lab" in page.text
    assert "what the Wallet prints" in page.text, "the PDF is named as the reference"
    assert "quick view" in page.text, "the HTML is named as the quick view"


def test_starts_empty_and_asks_for_the_missing_files() -> None:
    client.delete("/api/set")
    status = client.get("/api/set").json()
    assert status["loaded"] == {"template": None, "credential": None, "sample": None, "background": None}
    _upload(template=("record.html", TEMPLATE.encode()))
    for path in ("/preview", "/preview.pdf"):
        res = client.get(path)
        assert res.status_code == 409, (path, res.status_code)
        assert "credential" in res.json()["detail"] and "sample" in res.json()["detail"]
        assert "template" not in res.json()["detail"]


def test_replace_one_slot() -> None:
    _upload_set()
    res = _upload(template=("v2.html", b"<p>v2</p>"))
    assert res.json()["loaded"] == {"template": "v2.html", "credential": "record.json",
                                    "sample": "adapter-response.json", "background": None}


def test_remove_background_then_clear() -> None:
    _upload_set()
    assert _upload(background=("paper.pdf", _blank_pdf())).json()["loaded"]["background"] == "paper.pdf"
    loaded = client.delete("/api/set/background").json()["loaded"]
    assert loaded["background"] is None and loaded["template"] == "record.html" and loaded["sample"]
    cleared = client.delete("/api/set").json()
    assert set(cleared["loaded"].values()) == {None}
    assert cleared["missing"] == ["template", "credential", "sample"]
    assert client.get("/preview").status_code == 409


def test_download_and_upload_back() -> None:
    _upload_set()
    paper = _blank_pdf()
    assert _upload(background=("../../secret/paper.pdf", paper)).status_code == 200
    before = client.get("/api/set").json()
    assert before["loaded"]["background"] == "paper.pdf", "no path parts in a stored name"

    res = client.get("/download")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["background/paper.pdf", "credential/record.json",
                                        "sample/adapter-response.json", "template/record.html"]
        assert z.read("background/paper.pdf") == paper, "each file exactly as uploaded"
        assert z.read("template/record.html") == TEMPLATE.encode()
        assert json.loads(z.read("credential/record.json")) == CREDENTIAL

    client.delete("/api/set")
    assert _upload(bundle=("vc-lab-set.zip", res.content)).status_code == 200
    assert client.get("/api/set").json() == before
    def files(zip_bytes: bytes) -> dict[str, bytes]:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            return {name: z.read(name) for name in z.namelist()}

    assert files(client.get("/download").content) == files(res.content), "the same files come back"


def test_rejects_wrong_files() -> None:
    _upload_set()
    before = client.get("/api/set").json()
    no_mapping = {k: v for k, v in CREDENTIAL.items() if k != "vc_template"}
    cases = {
        "background not a PDF": {"background": ("paper.png", b"\x89PNG\r\n\x1a\n not a pdf")},
        "credential without vc_template": {"credential": ("c.json", _json(no_mapping))},
        "credential not JSON": {"credential": ("c.json", b"{oops")},
        "sample not JSON": {"sample": ("s.json", b"{oops")},
        "template with a stray #end": {"template": ("t.html", b"<p>#if($x)a#end#end</p>")},
        "template missing an #end": {"template": ("t.html", b"<p>#foreach($c in $terms)$c</p>")},
        "credential with display not a list": {"credential": ("c.json", _json({**CREDENTIAL, "display": {"name": "x"}}))},
        "credential with a logo not an object": {
            "credential": ("c.json", _json({**CREDENTIAL, "display": [{"name": "x", "logo": "logo.png"}]}))},
        "bundle not a zip": {"bundle": ("set.zip", b"not a zip")},
        "bundle with no files": {"bundle": ("set.zip", _empty_zip())},
        "too large": {"template": ("big.html", b"x" * (vc_lab.MAX_UPLOAD + 1))},
        "unknown field": {"stylesheet": ("s.css", b"p {}")},
    }
    for case, files in cases.items():
        res = _upload(**files)
        assert res.status_code == 400, (case, res.status_code, res.text)
        assert isinstance(res.json()["detail"], str) and res.json()["detail"], case
    assert client.get("/api/set").json() == before, "a rejected upload leaves the set as it was"
    assert _upload(template=("t.html", b"## #end in a comment\n#* #foreach *#<p>ok</p>")).status_code == 200, \
        "Velocity comments don't count"


def test_large_upload_stays_in_memory() -> None:
    """A file over Starlette's 1 MB spool limit (the AIT watermark is about 1 MB) never goes to a temp file."""
    spilled = []
    original = tempfile.SpooledTemporaryFile.rollover
    tempfile.SpooledTemporaryFile.rollover = lambda self: spilled.append(True) or original(self)
    try:
        _upload_set()
        big = b"<p>big</p>" + b" " * (3 * 1024 * 1024)
        assert _upload(template=("big.html", big)).status_code == 200
    finally:
        tempfile.SpooledTemporaryFile.rollover = original
    assert not spilled, "the upload was written to a temporary file on disk"


# ---------------------------------------------------------------------------------------------------------------
# Tests through the renderer


def test_grid_from_credential_subject_in_the_pdf_and_the_quick_view() -> bool:
    if _skip_without("test_grid_from_credential_subject_in_the_pdf_and_the_quick_view", "renderer"):
        return False
    _upload_set()
    page = client.get("/preview")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html"), page.text
    quick = html.unescape(page.text)
    pdf = _pages("/preview.pdf")
    assert len(pdf) == 2, "page 1 the record, page 2 the QR"
    printed = pdf[0].extract_text()
    for shown, where in ((quick, "quick view"), (printed, "PDF")):
        assert "Ada Example" in shown and "On Small Fixtures" in shown, (where, "claims through $rowProperties")
        assert "Term One" in shown and "XY101" in shown and "XY201" in shown, (where, "the grid from $credentialSubject")
        assert "Courses are not listed" not in shown, where
        assert "Example Record" in shown, (where, "$titleName from the credential file's display")
    assert TRICKY_TITLE in quick, "data with $ and # prints as written"
    assert "#123456" in quick and "data:image/png;base64,iVBOR" in quick, "the text colour and the QR code"
    assert "#claimValue" not in quick and "#foreach" not in quick
    return True


def test_velocity_and_mapping_errors_answer_422_with_the_engines_message() -> bool:
    if _skip_without("test_velocity_and_mapping_errors_answer_422_with_the_engines_message", "renderer"):
        return False
    _upload_set()
    assert _upload(template=("bad.html", b"<p>ok</p>\n<p>#set($x = )</p>")).status_code == 200, "balanced, uploads"
    for path in ("/preview", "/preview.pdf"):
        res = client.get(path)
        assert res.status_code == 422, (path, res.status_code, res.text)
        assert "line 2" in res.json()["detail"], (path, "Velocity names the line", res.json())

    _upload_set()
    assert _upload(sample=("null.json", _json({**SUBJECT, "thesisTitle": None}))).status_code == 200
    for path in ("/preview", "/preview.pdf"):
        res = client.get(path)
        assert res.status_code == 422, (path, res.status_code, res.text)
        assert "null for thesisTitle" in res.json()["detail"], (path, "the plugin's refusal", res.json())
    return True


def test_a_record_certify_refuses_answers_422_with_the_plugins_reason() -> bool:
    if _skip_without("test_a_record_certify_refuses_answers_422_with_the_plugins_reason", "renderer"):
        return False
    cases = {
        "a reserved key": (_json({**SAMPLE, "credentialSubject": {**SUBJECT, "id": "st0001"}}),
                           "the Adapter's record carries the forbidden key id"),
        "a duplicate key": (b'{"name": "Ada Example", "name": "Ada Again", "thesisTitle": "T", "courses": []}',
                            "the Adapter's answer is not the expected JSON"),
    }
    for case, (sample, reason) in cases.items():
        _upload_set()
        assert _upload(sample=("refused.json", sample)).status_code == 200, case
        for path in ("/preview", "/preview.pdf"):
            res = client.get(path)
            assert res.status_code == 422, (case, path, res.status_code, res.text)
            assert "adapter_error" in res.json()["detail"] and reason in res.json()["detail"], (case, res.json())
    return True


def test_a_template_named_in_any_script_previews() -> bool:
    if _skip_without("test_a_template_named_in_any_script_previews", "renderer"):
        return False
    _upload_set()
    assert _upload(template=("ใบรับรอง.html", TEMPLATE.encode())).status_code == 200
    res = client.get("/preview.pdf")
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "filename*=UTF-8''" + quote("ใบรับรอง.pdf") in disposition, disposition
    assert "Ada Example" in PdfReader(io.BytesIO(res.content)).pages[0].extract_text()
    return True


def test_sample_without_credential_subject() -> bool:
    if _skip_without("test_sample_without_credential_subject", "renderer"):
        return False
    _upload_set()
    with_envelope = client.get("/preview").text
    assert _upload(sample=("bare.json", _json(SUBJECT))).status_code == 200
    assert client.get("/preview").text == with_envelope, "a bare record renders the same"
    return True


def _with_body(body: str) -> bytes:
    """TEMPLATE with `body` at the top of page 1."""
    return TEMPLATE.replace('<div class="page">', f'<div class="page">\n{body}', 1).encode()


def test_a_template_reaching_for_an_address_answers_422_naming_it() -> bool:
    if _skip_without("test_a_template_reaching_for_an_address_answers_422_naming_it", "renderer"):
        return False
    cases = {
        "a font": ('<style>@font-face { font-family: "Far"; src: url("https://fonts.example/far.ttf"); }'
                   ' p { font-family: "Far"; }</style>', "https://fonts.example/far.ttf"),
        "an image on another host": ('<img src="http://cdn.example/logo.png">', "http://cdn.example/logo.png"),
        "a file": ('<img src="file:///etc/hostname">', "/etc/hostname"),
        "a VDR file the set doesn't have": ('<img src="http://vdr.localhost/templates/x/1/logo.png">',
                                            "http://vdr.localhost/templates/x/1/logo.png"),
        "the Background's address with no Background loaded": (
            '<img src="http://vdr.localhost/templates/x/1/background.png">',
            "http://vdr.localhost/templates/x/1/background.png"),
    }
    for case, (body, address) in cases.items():
        _upload_set()
        assert _upload(template=("reach.html", _with_body(body))).status_code == 200, case
        for path in ("/preview", "/preview.pdf"):
            res = client.get(path)
            assert res.status_code == 422, (case, path, res.status_code, res.text[:200])
            assert address in res.json()["detail"], (case, path, res.json())
    return True


def test_a_template_that_draws_logo_url_previews_without_a_logo() -> bool:
    if _skip_without("test_a_template_that_draws_logo_url_previews_without_a_logo", "renderer"):
        return False
    _upload_set()
    # As the committed demo template draws it. $logoUrl is "", which Velocity 1.7 counts as true.
    logo = '#if ($logoUrl)\n<img src="$logoUrl" alt="the logo" style="height:56px; width: auto;" />\n#end'
    assert _upload(template=("logo.html", _with_body(logo))).status_code == 200
    page = client.get("/preview")
    assert page.status_code == 200, page.text
    assert '<img src=""' in page.text, "the template draws an empty logo"
    pages = _pages("/preview.pdf")
    assert "Ada Example" in pages[0].extract_text()
    return True


def test_reflection_fails_in_the_print_template_and_the_vc_template() -> bool:
    if _skip_without("test_reflection_fails_in_the_print_template_and_the_vc_template", "renderer"):
        return False
    reach = ".getClass().forName('java.lang.Runtime')"
    mapping = {**CREDENTIAL["vc_template"], "credentialSubject": {
        **CREDENTIAL["vc_template"]["credentialSubject"], "thesisTitle": "MAPPED $name" + reach}}
    _upload_set()
    assert _upload(template=("reflect.html", _with_body(f"<p>PRINTED $titleName{reach}</p>")),
                   credential=("reflect.json", _json({**CREDENTIAL, "vc_template": mapping}))).status_code == 200
    page = client.get("/preview")
    assert page.status_code == 200, page.text
    printed = _pages("/preview.pdf")[0].extract_text()
    for shown, where in ((html.unescape(page.text), "quick view"), (printed, "PDF")):
        for engine in ("PRINTED", "MAPPED"):  # the print template's, the vc_template's
            assert engine in shown, (where, engine, "evaluated")
            assert f"{engine} class java.lang.Runtime" not in shown, (where, engine, "reached java.lang.Runtime")
    return True


def test_pdf_lays_the_background_under_page_one() -> bool:
    if _skip_without("test_pdf_lays_the_background_under_page_one", "renderer", "weasyprint"):
        return False
    _upload_set()
    plain = _pages("/preview.pdf")
    assert "PAPERMARK" not in plain[0].extract_text()

    assert _upload(background=("paper.pdf", _paper_pdf("PAPERMARK"))).status_code == 200
    layered = _pages("/preview.pdf")
    assert len(layered) == 2
    assert "PAPERMARK" in layered[0].extract_text(), "the background is under page 1"
    assert "Ada Example" in layered[0].extract_text(), "with the record over it"
    assert layered[1].extract_text() == plain[1].extract_text(), "page 2 prints clean"
    assert "PAPERMARK" not in client.get("/preview").text
    return True


def test_background_with_its_own_rotation_comes_out_portrait() -> bool:
    if _skip_without("test_background_with_its_own_rotation_comes_out_portrait", "renderer", "weasyprint"):
        return False
    _upload_set()
    paper = _paper_pdf("UPRIGHT")
    assert PdfReader(io.BytesIO(paper)).pages[0].rotation == 90
    assert _upload(background=("paper.pdf", paper)).status_code == 200
    page = _pages("/preview.pdf")[0]
    assert float(page.mediabox.height) > float(page.mediabox.width), "portrait A4"
    assert "UPRIGHT" in page.extract_text(orientations=(0,)), "the paper reads upright, as a viewer shows it"
    return True


def _snapshot() -> dict[str, tuple[int, int]]:
    roots = [REPO_ROOT / "deploy", VC_LAB_DIR]
    return {
        str(p): (p.stat().st_size, p.stat().st_mtime_ns)
        for root in roots for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    }


def main() -> None:
    before = _snapshot()
    tests: list[Callable[[], object]] = [
        test_health_and_dashboard,
        test_starts_empty_and_asks_for_the_missing_files,
        test_replace_one_slot,
        test_remove_background_then_clear,
        test_download_and_upload_back,
        test_rejects_wrong_files,
        test_large_upload_stays_in_memory,
        test_grid_from_credential_subject_in_the_pdf_and_the_quick_view,
        test_velocity_and_mapping_errors_answer_422_with_the_engines_message,
        test_a_record_certify_refuses_answers_422_with_the_plugins_reason,
        test_a_template_named_in_any_script_previews,
        test_sample_without_credential_subject,
        test_a_template_reaching_for_an_address_answers_422_naming_it,
        test_a_template_that_draws_logo_url_previews_without_a_logo,
        test_reflection_fails_in_the_print_template_and_the_vc_template,
        test_pdf_lays_the_background_under_page_one,
        test_background_with_its_own_rotation_comes_out_portrait,
    ]
    passed = skipped = 0
    for test in tests:
        if test() is False:
            skipped += 1
        else:
            passed += 1
            print(f"PASS {test.__name__}")
    assert _snapshot() == before, "VC Lab wrote into the repo's template, VDR or credentials folders"
    passed += 1
    print("PASS test_nothing_written_to_disk")
    print(f"{passed} tests passed" + (f", {skipped} skipped" if skipped else ""))


if __name__ == "__main__":
    main()
