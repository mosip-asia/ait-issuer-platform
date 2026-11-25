"""VC Lab's web API, driven the way the dashboard drives it, with a small made-up set.

Run:
    python3 src/vc-lab/test_main.py

The preview tests need the renderer (src/renderer) at RENDERER_URL and skip without it. Inside Compose, VC Lab has
it: `docker compose run --rm vc-lab python src/vc-lab/test_main.py`. The Background tests also need WeasyPrint's
system libraries (Pango) to draw their paper; the ait-vc image has them.
"""

from __future__ import annotations

import base64
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


def _set(**changes: tuple[str, bytes] | None) -> dict[str, tuple[str, bytes]]:
    """The made-up set as the dashboard holds it, {slot: (filename, data)}. A change replaces a slot; None drops it."""
    files: dict[str, tuple[str, bytes] | None] = {
        "template": ("record.html", TEMPLATE.encode()), "credential": ("record.json", _json(CREDENTIAL)),
        "sample": ("adapter-response.json", _json(SAMPLE))}
    files.update(changes)
    return {slot: file for slot, file in files.items() if file is not None}


def _post(path: str, files: dict[str, tuple[str, bytes]]):
    """What the dashboard sends: the whole set, as one multipart form, with every call."""
    return client.post(path, files=files)


def _zip_files(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {name: z.read(name) for name in z.namelist()}


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


def _zip_of(members: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
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


def _pages(files: dict[str, tuple[str, bytes]]) -> list:
    res = _post("/preview.pdf", files)
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


def test_the_server_keeps_no_set() -> None:
    """The set lives in the browser: no endpoint holds, lists or hands back a set."""
    _post("/download", _set())
    for method, path in (("get", "/api/set"), ("post", "/api/set"), ("delete", "/api/set"),
                         ("delete", "/api/set/background"), ("get", "/preview"), ("get", "/preview.pdf"),
                         ("get", "/download")):
        res = getattr(client, method)(path)
        assert res.status_code in (404, 405), (method, path, res.status_code)


def test_every_call_asks_for_what_it_was_not_sent() -> None:
    """Nothing is remembered between calls: a call without the credential file and the sample is asked for them,
    though the full set was sent a moment ago."""
    assert _post("/download", _set()).status_code == 200
    for path in ("/preview", "/preview.pdf"):
        res =_post(path, _set(credential=None, sample=None))
        assert res.status_code == 409, (path, res.status_code)
        assert "credential" in res.json()["detail"] and "sample" in res.json()["detail"]
        assert "template" not in res.json()["detail"]
    assert _post("/download", {}).status_code == 400, "no file sent, no zip"


def test_two_visitors_each_get_their_own_files() -> None:
    mine = _set(template=("mine.html", b"<p>mine</p>"), background=("paper.pdf", _blank_pdf()))
    theirs = _set(template=("theirs.html", b"<p>theirs</p>"))
    first = _post("/download", mine)
    second = _post("/download", theirs)
    again = _post("/download", mine)
    assert first.status_code == second.status_code == again.status_code == 200
    assert sorted(_zip_files(second.content)) == ["credential/record.json", "sample/adapter-response.json",
                                                  "template/theirs.html"], "no file of the other visitor's"
    assert _zip_files(second.content)["template/theirs.html"] == b"<p>theirs</p>"
    assert _zip_files(first.content) == _zip_files(again.content)
    assert "background/paper.pdf" in _zip_files(first.content)


def test_download_and_read_back() -> None:
    paper = _blank_pdf()
    files = _set(background=("../../secret/paper.pdf", paper))
    res = _post("/download", files)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    assert sorted(_zip_files(res.content)) == ["background/paper.pdf", "credential/record.json",
                                               "sample/adapter-response.json", "template/record.html"]
    zipped = _zip_files(res.content)
    assert zipped["background/paper.pdf"] == paper, "each file exactly as uploaded, with no path parts in its name"
    assert zipped["template/record.html"] == TEMPLATE.encode()
    assert json.loads(zipped["credential/record.json"]) == CREDENTIAL

    back = client.post("/api/bundle", files={"bundle": ("vc-lab-set.zip", res.content)})
    assert back.status_code == 200, back.text
    got = {slot: (f["filename"], base64.b64decode(f["data"])) for slot, f in back.json().items()}
    assert got == {"template": ("record.html", TEMPLATE.encode()), "credential": ("record.json", _json(CREDENTIAL)),
                   "sample": ("adapter-response.json", _json(SAMPLE)), "background": ("paper.pdf", paper)}


def test_rejects_wrong_files() -> None:
    no_mapping = {k: v for k, v in CREDENTIAL.items() if k != "vc_template"}
    cases = {
        "background not a PDF": {"background": ("paper.png", b"\x89PNG\r\n\x1a\n not a pdf")},
        "credential without vc_template": {"credential": ("c.json", _json(no_mapping))},
        "credential not JSON": {"credential": ("c.json", b"{oops")},
        "sample not JSON": {"sample": ("s.json", b"{oops")},
        "sample not an object": {"sample": ("s.json", b"[1]")},
        "template with a stray #end": {"template": ("t.html", b"<p>#if($x)a#end#end</p>")},
        "template missing an #end": {"template": ("t.html", b"<p>#foreach($c in $terms)$c</p>")},
        "credential with display not a list": {"credential": ("c.json", _json({**CREDENTIAL, "display": {"name": "x"}}))},
        "credential with a logo not an object": {
            "credential": ("c.json", _json({**CREDENTIAL, "display": [{"name": "x", "logo": "logo.png"}]}))},
        "unknown field": {"stylesheet": ("s.css", b"p {}")},
    }
    for case, changes in cases.items():
        for path in ("/preview", "/preview.pdf", "/download"):
            res = _post(path, _set(**changes))
            assert res.status_code == 400, (case, path, res.status_code, res.text)
            assert isinstance(res.json()["detail"], str) and res.json()["detail"], (case, path)
    ok = _post("/download", _set(template=("t.html", b"## #end in a comment\n#* #foreach *#<p>ok</p>")))
    assert ok.status_code == 200, "Velocity comments don't count"

    for case, bundle in {"not a zip": b"not a zip", "no files": _empty_zip(),
                         "a file in no slot": _zip_of({"notes/readme.txt": b"hi"})}.items():
        res = client.post("/api/bundle", files={"bundle": ("set.zip", bundle)})
        assert res.status_code == 400, (case, res.status_code, res.text)
        assert isinstance(res.json()["detail"], str) and res.json()["detail"], case


def test_a_request_over_20_mb_is_refused() -> None:
    assert vc_lab.MAX_UPLOAD == 20 * 1024 * 1024
    big = b"<p>big</p>" + b" " * (15 * 1024 * 1024)
    assert _post("/download", _set(template=("big.html", big))).status_code == 200, "15 MB fits"
    too_big = b"<p>big</p>" + b" " * (vc_lab.MAX_UPLOAD + 1)
    for path in ("/preview", "/preview.pdf", "/download"):
        res = _post(path, _set(template=("big.html", too_big)))
        assert res.status_code == 400 and "20 MB" in res.json()["detail"], (path, res.status_code)
    res = client.post("/api/bundle", files={"bundle": ("set.zip", _zip_of({"template/big.html": too_big}))})
    assert res.status_code == 400, res.status_code


def test_large_upload_stays_in_memory() -> None:
    """A file over Starlette's 1 MB spool limit (the AIT watermark is about 1 MB) never goes to a temp file."""
    spilled = []
    original = tempfile.SpooledTemporaryFile.rollover
    tempfile.SpooledTemporaryFile.rollover = lambda self: spilled.append(True) or original(self)
    try:
        big = b"<p>big</p>" + b" " * (3 * 1024 * 1024)
        assert _post("/download", _set(template=("big.html", big))).status_code == 200
    finally:
        tempfile.SpooledTemporaryFile.rollover = original
    assert not spilled, "the upload was written to a temporary file on disk"


# ---------------------------------------------------------------------------------------------------------------
# Tests through the renderer


def test_grid_from_credential_subject_in_the_pdf_and_the_quick_view() -> bool:
    if _skip_without("test_grid_from_credential_subject_in_the_pdf_and_the_quick_view", "renderer"):
        return False
    page = _post("/preview", _set())
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html"), page.text
    quick = html.unescape(page.text)
    pdf = _pages(_set())
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


def test_two_visitors_each_preview_their_own_set() -> bool:
    if _skip_without("test_two_visitors_each_preview_their_own_set", "renderer"):
        return False
    mine = _set(sample=("mine.json", _json({**SAMPLE, "credentialSubject": {**SUBJECT, "name": "Ada Mine"}})))
    theirs = _set(sample=("theirs.json", _json({**SAMPLE, "credentialSubject": {**SUBJECT, "name": "Bo Theirs"}})))
    for _ in range(2):  # interleaved, twice, so the second call of each would show a remembered set
        for files, name, other in ((mine, "Ada Mine", "Bo Theirs"), (theirs, "Bo Theirs", "Ada Mine")):
            quick = html.unescape(_post("/preview", files).text)
            printed = _pages(files)[0].extract_text()
            for shown in (quick, printed):
                assert name in shown and other not in shown, (name, other)
    return True


def test_velocity_and_mapping_errors_answer_422_with_the_engines_message() -> bool:
    if _skip_without("test_velocity_and_mapping_errors_answer_422_with_the_engines_message", "renderer"):
        return False
    bad = _set(template=("bad.html", b"<p>ok</p>\n<p>#set($x = )</p>"))  # balanced, so it passes the checks
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, bad)
        assert res.status_code == 422, (path, res.status_code, res.text)
        assert "line 2" in res.json()["detail"], (path, "Velocity names the line", res.json())

    null = _set(sample=("null.json", _json({**SUBJECT, "thesisTitle": None})))
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, null)
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
        for path in ("/preview", "/preview.pdf"):
            res = _post(path, _set(sample=("refused.json", sample)))
            assert res.status_code == 422, (case, path, res.status_code, res.text)
            assert "adapter_error" in res.json()["detail"] and reason in res.json()["detail"], (case, res.json())
    return True


def test_a_template_named_in_any_script_previews() -> bool:
    if _skip_without("test_a_template_named_in_any_script_previews", "renderer"):
        return False
    res = _post("/preview.pdf", _set(template=("ใบรับรอง.html", TEMPLATE.encode())))
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "filename*=UTF-8''" + quote("ใบรับรอง.pdf") in disposition, disposition
    assert "Ada Example" in PdfReader(io.BytesIO(res.content)).pages[0].extract_text()
    return True


def test_sample_without_credential_subject() -> bool:
    if _skip_without("test_sample_without_credential_subject", "renderer"):
        return False
    with_envelope = _post("/preview", _set()).text
    assert _post("/preview", _set(sample=("bare.json", _json(SUBJECT)))).text == with_envelope, \
        "a bare record renders the same"
    return True


def test_pdf_lays_the_background_under_page_one() -> bool:
    if _skip_without("test_pdf_lays_the_background_under_page_one", "renderer", "weasyprint"):
        return False
    plain = _pages(_set())
    assert "PAPERMARK" not in plain[0].extract_text()

    with_paper = _set(background=("paper.pdf", _paper_pdf("PAPERMARK")))
    layered = _pages(with_paper)
    assert len(layered) == 2
    assert "PAPERMARK" in layered[0].extract_text(), "the background is under page 1"
    assert "Ada Example" in layered[0].extract_text(), "with the record over it"
    assert layered[1].extract_text() == plain[1].extract_text(), "page 2 prints clean"
    assert "PAPERMARK" not in _post("/preview", with_paper).text
    return True


def test_background_with_its_own_rotation_comes_out_portrait() -> bool:
    if _skip_without("test_background_with_its_own_rotation_comes_out_portrait", "renderer", "weasyprint"):
        return False
    paper = _paper_pdf("UPRIGHT")
    assert PdfReader(io.BytesIO(paper)).pages[0].rotation == 90
    page = _pages(_set(background=("paper.pdf", paper)))[0]
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
        test_the_server_keeps_no_set,
        test_every_call_asks_for_what_it_was_not_sent,
        test_two_visitors_each_get_their_own_files,
        test_download_and_read_back,
        test_rejects_wrong_files,
        test_a_request_over_20_mb_is_refused,
        test_large_upload_stays_in_memory,
        test_grid_from_credential_subject_in_the_pdf_and_the_quick_view,
        test_two_visitors_each_preview_their_own_set,
        test_velocity_and_mapping_errors_answer_422_with_the_engines_message,
        test_a_record_certify_refuses_answers_422_with_the_plugins_reason,
        test_a_template_named_in_any_script_previews,
        test_sample_without_credential_subject,
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
