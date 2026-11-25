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
        test_grid_from_credential_subject_in_the_pdf_and_the_quick_view,
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
