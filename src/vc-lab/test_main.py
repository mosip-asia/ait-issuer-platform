"""VC Lab's web API, driven the way the dashboard drives it, with a small made-up set.

Run:
    python3 src/vc-lab/test_main.py

The PDF tests need WeasyPrint's system libraries (Pango): they run in the ait-vc image and skip on a host
without them.
"""

from __future__ import annotations

import html
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Callable

VC_LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = VC_LAB_DIR.parent.parent
sys.path.insert(0, str(VC_LAB_DIR))

import main as vc_lab  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader, PdfWriter, Transformation  # noqa: E402

client = TestClient(vc_lab.app)

# ---------------------------------------------------------------------------------------------------------------
# The made-up set

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
#if($terms)
#foreach($t in $terms)
    <tr><th colspan="3">$t.label</th></tr>
#foreach($c in $t.courses)
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
    "display": [{"name": "Example Record", "logo": {"url": "https://example.org/logo.png"},
                 "background_color": "#ffffff", "text_color": "#123456"}],
    "vc_template": {
        "@context": ["https://www.w3.org/ns/credentials/v2"],
        "issuer": "${_issuer}",
        "type": ["VerifiableCredential", "ExampleRecord"],
        "credentialSubject": {
            "id": "${_holderId}",
            "holderName": "${name}",
            "thesisTitle": "${thesis.title}",
            "terms": "${records}",
        },
    },
}

TRICKY_TITLE = "Costs in $titleName & #if($terms)loops#end"
SUBJECT = {
    "name": "Ada Example",
    "thesis": {"title": "On Small Fixtures", "grade": "P"},
    "records": [
        {"label": "Term One", "courses": [{"code": "XY101", "title": "Fixture Design", "grade": "A"},
                                          {"code": "XY102", "title": TRICKY_TITLE, "grade": "B+"}]},
        {"label": "Term Two", "courses": [{"code": "XY201", "title": "Seams", "grade": "A"}]},
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


# ---------------------------------------------------------------------------------------------------------------
# Tests


def test_health_and_dashboard() -> None:
    assert client.get("/health").json() == {"status": "UP", "service": "vc-lab"}
    page = client.get("/")
    assert page.status_code == 200 and "VC Lab" in page.text


def test_starts_empty_and_asks_for_the_missing_files() -> None:
    client.delete("/api/set")
    status = client.get("/api/set").json()
    assert status["loaded"] == {"template": None, "credential": None, "sample": None, "background": None}
    _upload(template=("record.html", TEMPLATE.encode()))
    for path in ("/preview", "/preview?view=wallet", "/export.pdf"):
        res = client.get(path)
        assert res.status_code == 409, (path, res.status_code)
        assert "credential" in res.json()["detail"] and "sample" in res.json()["detail"]
        assert "template" not in res.json()["detail"]


def test_preview_shows_mapped_values() -> None:
    _upload_set()
    page = client.get("/preview").text
    assert "Ada Example" in page, "a mapped field"
    assert "On Small Fixtures" in page, "a nested field (${thesis.title})"
    assert "Term One" in page and "XY101" in page and "XY201" in page, "a looped list, with its nested list"
    assert "Courses are not listed" not in page
    assert "Example Record" in page and "#123456" in page, "the title and colours come from the display entry"
    assert "data:image/png;base64,iVBOR" in page, "a mock QR"
    assert TRICKY_TITLE in html.unescape(page), "loop data with $ and # prints as written"
    assert "#claimValue" not in page and "#foreach" not in page and "#end" not in page


def test_wallet_view_drops_the_list() -> None:
    _upload_set()
    page = client.get("/preview?view=wallet").text
    assert "Ada Example" in page and "On Small Fixtures" in page
    assert "XY101" not in page and "Term One" not in page
    assert "Courses are not listed in this copy." in page, "the template's fallback"


def test_sample_without_credential_subject() -> None:
    _upload_set()
    with_envelope = client.get("/preview").text
    assert _upload(sample=("bare.json", _json(SUBJECT))).status_code == 200
    assert client.get("/preview").text == with_envelope, "a bare record renders the same"


def test_replace_one_slot() -> None:
    _upload_set()
    res = _upload(template=("v2.html", b"<p>v2 for #claimValue('holderName')</p>"))
    assert res.json()["loaded"] == {"template": "v2.html", "credential": "record.json",
                                    "sample": "adapter-response.json", "background": None}
    assert client.get("/preview").text == "<p>v2 for Ada Example</p>"


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
    before_status, before_page = client.get("/api/set").json(), client.get("/preview").text
    assert before_status["loaded"]["background"] == "paper.pdf", "no path parts in a stored name"

    res = client.get("/download")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["background/paper.pdf", "credential/record.json",
                                        "sample/adapter-response.json", "template/record.html"]
        assert z.read("background/paper.pdf") == paper, "each file exactly as uploaded"
        assert json.loads(z.read("credential/record.json")) == CREDENTIAL

    client.delete("/api/set")
    assert _upload(bundle=("vc-lab-set.zip", res.content)).status_code == 200
    assert client.get("/api/set").json() == before_status
    assert client.get("/preview").text == before_page


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


def test_large_upload_stays_in_memory() -> None:
    """A file over Starlette's 1 MB spool limit (the AIT watermark is about 1 MB) never goes to a temp file."""
    spilled = []
    original = tempfile.SpooledTemporaryFile.rollover
    tempfile.SpooledTemporaryFile.rollover = lambda self: spilled.append(True) or original(self)
    try:
        _upload_set()
        big = b"<p>#claimValue('holderName')</p>" + b" " * (3 * 1024 * 1024)
        assert _upload(template=("big.html", big)).status_code == 200
    finally:
        tempfile.SpooledTemporaryFile.rollover = original
    assert not spilled, "the upload was written to a temporary file on disk"
    assert "Ada Example" in client.get("/preview").text


def test_export_pdf_lays_the_background_under_page_one() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception as e:  # Pango missing on this host; the ait-vc image has it
        print(f"SKIP test_export_pdf_lays_the_background_under_page_one ({type(e).__name__})")
        return False
    _upload_set()
    plain = _pages("/export.pdf")
    assert len(plain) == 2, "page 1 the record, page 2 the QR"
    assert "Ada Example" in plain[0].extract_text() and "XY101" in plain[0].extract_text()
    assert "PAPERMARK" not in plain[0].extract_text()

    wallet = _pages("/export.pdf?view=wallet")
    assert len(wallet) == 2 and "XY101" not in wallet[0].extract_text()

    assert _upload(background=("paper.pdf", _paper_pdf("PAPERMARK"))).status_code == 200
    layered = _pages("/export.pdf")
    assert len(layered) == 2
    assert "PAPERMARK" in layered[0].extract_text(), "the background is under page 1"
    assert "Ada Example" in layered[0].extract_text(), "with the record over it"
    assert layered[1].extract_text() == plain[1].extract_text(), "page 2 prints clean"
    assert "PAPERMARK" not in client.get("/preview").text
    return True


def test_background_with_its_own_rotation_comes_out_portrait() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception as e:
        print(f"SKIP test_background_with_its_own_rotation_comes_out_portrait ({type(e).__name__})")
        return False
    _upload_set()
    paper = _paper_pdf("UPRIGHT")
    assert PdfReader(io.BytesIO(paper)).pages[0].rotation == 90
    assert _upload(background=("paper.pdf", paper)).status_code == 200
    page = _pages("/export.pdf")[0]
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
        test_preview_shows_mapped_values,
        test_wallet_view_drops_the_list,
        test_sample_without_credential_subject,
        test_replace_one_slot,
        test_remove_background_then_clear,
        test_download_and_upload_back,
        test_rejects_wrong_files,
        test_large_upload_stays_in_memory,
        test_export_pdf_lays_the_background_under_page_one,
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
