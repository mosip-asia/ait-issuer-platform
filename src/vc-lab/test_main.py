"""VC Lab's web API, driven the way the dashboard drives it, with a small made-up set.

Run, with the renderer beside VC Lab (the /preview.pdf tests need it):
    docker compose build renderer vc-lab && docker compose run --rm vc-lab python src/vc-lab/test_main.py
On a host, without Compose:
    python3 src/vc-lab/test_main.py

The /preview.pdf tests that need a real renderer skip without RENDERER_URL (a host run); they run in the ait-vc
image through Compose. The rest, which use a stand-in renderer, run anywhere.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

VC_LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = VC_LAB_DIR.parent.parent
sys.path.insert(0, str(VC_LAB_DIR))

import main as vc_lab  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402

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


# A set for the Wallet's print (/preview.pdf, through the renderer). The template reads claims only through
# $rowProperties, as Mimoto hands them over.
PRINT_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>$titleName</title>
<style>@page { size: A4 portrait; margin: 20mm; } body { font-family: "Noto Sans", FreeSans, Arial, sans-serif; }</style>
</head>
<body>
#macro(claimValue $claimName)#set($__claim = $rowProperties.get($claimName))#if($__claim)#foreach($__entry in $__claim.entrySet())$__entry.value#end#end#end
<h1>$titleName</h1>
<p>Holder: #claimValue("holderName")</p>
<p>Thesis: #claimValue("thesisTitle")</p>
<p>Records: [#claimValue("terms")]</p>
<p>Majors: [#claimValue("majors")]</p>
<p>Honours: #claimValue("honours")</p>
<p>Note: #claimValue("printNote")</p>
<p>Order: #foreach($e in $rowProperties.entrySet())$e.key #end</p>
<p>Names: #foreach($e in $rowProperties.entrySet())#foreach($n in $e.value.keySet())$n; #end#end</p>
<p>Colours: $textColor on $backgroundColor, logo $logoUrl, validity $credentialValidity</p>
#set($cr = "")
#set($crMap = $rowProperties.get("courseRows"))
#if($crMap)#foreach($e in $crMap.entrySet())#set($cr = $e.value)#end#end
#foreach($row in $cr.split("\\n"))
#set($f = $row.split("\\|", -1))
<p>ROW $f.get(0) / $f.size() fields: $f.get(1) $f.get(2)</p>
#end
<img src="data:image/png;base64,$qrCodeImage" alt="QR" />
</body></html>
"""

PRINT_CREDENTIAL = {
    "credential_config_key_id": "example-record",
    "display": [{"name": "Example Record", "locale": "en",
                 "logo": {"url": "https://example.org/logo.png", "alt_text": "Example logo"},
                 "background_color": "#ffffff", "text_color": "#123456"}],
    "display_order": ["thesisTitle", "holderName"],
    "credential_subject": {  # courseRows and printNote have no display entry
        "holderName": {"display": [{"name": "Holder", "locale": "en"}]},
        "thesisTitle": {"display": [{"name": "Thesis", "locale": "en"}]},
        "terms": {"display": [{"name": "Terms", "locale": "en"}]},
        "majors": {"display": [{"name": "Majors", "locale": "en"}]},
        "honours": {"display": [{"name": "Honours", "locale": "en"}]},
    },
    "vc_template": {
        "@context": ["https://www.w3.org/ns/credentials/v2"],
        "issuer": "${_issuer}",
        "type": ["VerifiableCredential", "ExampleRecord"],
        "credentialSubject": {
            "id": "${_holderId}",
            "holderName": "${name}",
            "thesisTitle": "${thesis.title}",
            "terms": "${records}",
            "majors": "${majors}",
            "honours": "${honours}",
            "courseRows": "${courseRows}",
            "printNote": "${note}",
        },
    },
}

PRINT_SUBJECT = {
    **SUBJECT,
    "majors": ["Fixtures", "Seams"],
    "honours": {"value": "With distinction", "language": "en"},
    # One term heading, a graded course and an ungraded one (its last field is empty).
    "courseRows": "T|Term One|6|3.50|3.50\nC|XY101|Fixture Design|0|45|3|A\nC|XY102|Seams|0|45|3|",
    "note": "Printed from made-up data",
}


STANDARD_FONTS = {
    "Courier", "Courier-Bold", "Courier-Oblique", "Courier-BoldOblique",
    "Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique",
    "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic", "Symbol", "ZapfDingbats",
}


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


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def _png(width: int, height: int, noisy: bool = False, channels: int = 1, depth: int = 8,
         noise_bytes: int | None = None) -> bytes:
    """A made-up PNG, width x height, with 1 (grey), 2, 3 or 4 channels of 8 or 16 bits. Rows are flat grey, except
    that `noisy` makes every row random (incompressible, so a big one stays big), or `noise_bytes` makes as many
    rows random as that many bytes cover, so a huge image can still be a file under the upload cap."""
    row = (width * channels * depth + 7) // 8
    noisy_rows = height if noisy else min(height, (noise_bytes or 0) // row)
    rows = b"".join(b"\x00" + (os.urandom(row) if y < noisy_rows else b"\x80" * row) for y in range(height))
    header = struct.pack(">IIBBBBB", width, height, depth, {1: 0, 2: 4, 3: 2, 4: 6}[channels], 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(rows))
            + _chunk(b"IEND", b""))


def _png_of_size(size: int) -> bytes:
    """A small PNG padded to exactly `size` bytes with random bytes in a private ancillary chunk."""
    small = _png(16, 16)
    pad = size - len(small) - 12  # a chunk's length, type and CRC
    assert pad >= 0
    return small[:-12] + _chunk(b"prVt", os.urandom(pad)) + small[-12:]


# A made-up baseline JPEG, 16 x 24 pixels, flat grey (335 bytes); hard-coded so the tests need no image library.
JPEG_16X24 = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300100b0c0e0c0a100e0d0e1211101318281a181616183123251d283a333d3c3933383740485c4e404457453738506d51575f626768673e4d71797064785c656763ffc0000b080018001001011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f0028a28a28afffd9"
)


def _jpeg_header(width: int, height: int) -> bytes:
    """Only a JPEG's start: SOI, one SOF0 segment saying width x height, EOI. Enough to be read, not to be drawn."""
    sof = bytes([8]) + struct.pack(">HH", height, width) + bytes([1, 1, 0x11, 0])
    return b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def _then(m: list[float], n: list[float]) -> list[float]:
    """The matrix that applies m first, then n, both as PDF's [a b c d e f]."""
    return [m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3], m[2] * n[0] + m[3] * n[2],
            m[2] * n[1] + m[3] * n[3], m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5]]


def _drawn_images(page) -> list[dict]:
    """Each image the page draws, with its rectangle in points. An image is drawn into the unit square, so the
    current transformation matrix is its rectangle. (src/tools/print_check.py's drawn_images, which can't be
    imported: it needs the print check's stack.)"""
    from pypdf.generic import ContentStream

    found: list[dict] = []

    def walk(content, resources, base: list[float]) -> None:
        ctm, saved = base, []
        for operands, op in ContentStream(content, page.pdf).operations:
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
                    found.append({"px": (int(xobject["/Width"]), int(xobject["/Height"])),
                                  "x": ctm[4], "y": ctm[5], "w": ctm[0], "h": ctm[3]})
                elif xobject.get("/Subtype") == "/Form":
                    matrix = [float(v) for v in xobject.get("/Matrix", [1, 0, 0, 1, 0, 0])]
                    walk(xobject, xobject.get("/Resources") or resources, _then(matrix, ctm))

    walk(page.get_contents(), page.get("/Resources") or {}, [1, 0, 0, 1, 0, 0])
    return found


def _pages(path: str) -> list:
    res = client.get(path)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    return PdfReader(io.BytesIO(res.content)).pages


def _no_renderer(test: str) -> bool:
    """True, after printing SKIP, when no renderer is configured (a host run); Compose sets RENDERER_URL."""
    if os.environ.get("RENDERER_URL"):
        return False
    print(f"SKIP {test} (no RENDERER_URL: run it through Compose, see README.md)")
    return True


def _upload_print_set(template: str = PRINT_TEMPLATE) -> None:
    client.delete("/api/set")
    res = _upload(template=("print.html", template.encode()), credential=("print.json", _json(PRINT_CREDENTIAL)),
                  sample=("adapter-response.json", _json({"credentialSubject": PRINT_SUBJECT})))
    assert res.status_code == 200, res.text


def _printed() -> tuple[str, list]:
    """The Wallet's print of the loaded set: its whitespace-normalised text and its pages."""
    pages = _pages("/preview.pdf")
    return " ".join(" ".join(p.extract_text() for p in pages).split()), pages


def _images(page) -> list[tuple[int, int]]:
    """(width, height) of each image the page draws."""
    xobjects = page["/Resources"].get_object().get("/XObject", {})
    return [(int(x["/Width"]), int(x["/Height"])) for x in (o.get_object() for o in xobjects.values())
            if x.get("/Subtype") == "/Image"]


# ---------------------------------------------------------------------------------------------------------------
# Tests


def test_health_and_dashboard() -> None:
    assert client.get("/health").json() == {"status": "UP", "service": "vc-lab"}
    page = client.get("/")
    assert page.status_code == 200 and "VC Lab" in page.text
    assert "/preview.pdf" in page.text, "the dashboard shows the Wallet's print"
    for gone in ('name="view"', "Export PDF", "/export.pdf"):
        assert gone not in page.text, f"the dashboard has no {gone}"
    for kept in ('data-field="template"', 'data-field="credential"', 'data-field="sample"',
                 'data-field="background"', 'data-field="bundle"', 'id="download"', 'id="removeBackground"', 'id="clear"'):
        assert kept in page.text, f"the dashboard keeps {kept}"


def test_the_old_rendering_endpoints_are_gone() -> None:
    _upload_set()  # a complete set: the answer is 404 for the route, not 409 for a missing file
    for path in ("/preview", "/preview?view=lab", "/preview?view=wallet", "/export.pdf", "/export.pdf?view=wallet"):
        assert client.get(path).status_code == 404, path


def test_starts_empty_and_asks_for_the_missing_files() -> None:
    client.delete("/api/set")
    status = client.get("/api/set").json()
    assert status["loaded"] == {"template": None, "credential": None, "sample": None, "background": None}
    _upload(template=("record.html", TEMPLATE.encode()))
    res = client.get("/preview.pdf")
    assert res.status_code == 409, res.status_code
    assert "credential" in res.json()["detail"] and "sample" in res.json()["detail"]
    assert "template" not in res.json()["detail"]


@contextlib.contextmanager
def _renderer_stand_in():
    """Yields a function that gets /preview.pdf from a stand-in renderer and returns the request VC Lab sent it.
    That request is what VC Lab decides (the template as uploaded, the claims the credential file maps, the
    Background); it runs on a host too, without Compose."""
    bodies: list = []
    server = _stand_in_renderer(bodies)
    saved, vc_lab.RENDERER_URL = vc_lab.RENDERER_URL, f"http://127.0.0.1:{server.server_port}"

    def sent() -> dict:
        res = client.get("/preview.pdf")
        assert res.status_code == 200, res.text
        return bodies[-1]

    try:
        yield sent
    finally:
        vc_lab.RENDERER_URL = saved
        server.shutdown()
        server.server_close()


def test_the_renderer_is_sent_the_mapped_claims() -> None:
    _upload_set()
    with _renderer_stand_in() as sent:
        request = sent()
        assert request["template"] == TEMPLATE and request["credentialFile"] == CREDENTIAL and request["locale"] == "en"
        assert request["credentialSubject"] == {
            "id": "did:example:holderId",  # Certify's own variables get a placeholder
            "holderName": "Ada Example",
            "thesisTitle": "On Small Fixtures",  # a nested reference, ${thesis.title}
            "terms": SUBJECT["records"],  # a reference that is the whole value keeps its list
        }
        credential = {**CREDENTIAL, "vc_template": {**CREDENTIAL["vc_template"], "credentialSubject": {
            "label": "Dr. ${name} of ${nowhere}", "kept": 3}}}
        assert _upload(credential=("record.json", _json(credential))).status_code == 200
        assert sent()["credentialSubject"] == {"label": "Dr. Ada Example of ", "kept": 3}, "text around a reference"
        envelope = sent()["credentialSubject"]
        assert _upload(sample=("bare.json", _json(SUBJECT))).status_code == 200
        assert sent()["credentialSubject"] == envelope, "a bare record maps the same as an enveloped one"


def test_replace_one_slot() -> None:
    _upload_set()
    res = _upload(template=("v2.html", b"<p>v2 for #claimValue('holderName')</p>"))
    assert res.json()["loaded"] == {"template": "v2.html", "credential": "record.json",
                                    "sample": "adapter-response.json", "background": None}
    with _renderer_stand_in() as sent:
        request = sent()
        assert request["template"] == "<p>v2 for #claimValue('holderName')</p>"
        assert request["credentialSubject"]["holderName"] == "Ada Example", "the other slots are kept"


def test_remove_background_then_clear() -> None:
    _upload_set()
    assert _upload(background=("paper.png", _png(20, 30))).json()["loaded"]["background"] == "paper.png"
    loaded = client.delete("/api/set/background").json()["loaded"]
    assert loaded["background"] is None and loaded["template"] == "record.html" and loaded["sample"]
    cleared = client.delete("/api/set").json()
    assert set(cleared["loaded"].values()) == {None}
    assert cleared["missing"] == ["template", "credential", "sample"]
    assert client.get("/preview.pdf").status_code == 409


def test_download_and_upload_back() -> None:
    _upload_set()
    paper = _png(20, 30)
    assert _upload(background=("../../secret/paper.png", paper)).status_code == 200
    with _renderer_stand_in() as sent:
        before_status, before_request = client.get("/api/set").json(), sent()
    assert before_status["loaded"]["background"] == "paper.png", "no path parts in a stored name"

    res = client.get("/download")
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        assert sorted(z.namelist()) == ["background/paper.png", "credential/record.json",
                                        "sample/adapter-response.json", "template/record.html"]
        assert z.read("background/paper.png") == paper, "each file exactly as uploaded"
        assert json.loads(z.read("credential/record.json")) == CREDENTIAL

    client.delete("/api/set")
    assert _upload(bundle=("vc-lab-set.zip", res.content)).status_code == 200
    assert client.get("/api/set").json() == before_status
    with _renderer_stand_in() as sent:
        assert sent() == before_request, "the renderer is sent the same request after the round trip"


def test_rejects_wrong_files() -> None:
    _upload_set()
    before = client.get("/api/set").json()
    no_mapping = {k: v for k, v in CREDENTIAL.items() if k != "vc_template"}
    cases = {
        "background a PDF": {"background": ("paper.pdf", _blank_pdf())},
        "background a GIF": {"background": ("paper.png", b"GIF89a" + b"\x00" * 20)},
        "background named .png but not an image": {"background": ("paper.png", b"not an image")},
        "background PNG signature alone": {"background": ("paper.png", b"\x89PNG\r\n\x1a\n")},
        "background JPEG signature and junk": {"background": ("paper.jpg", b"\xff\xd8\xff" + b"hello" * 20)},
        "background JPEG with no size in it": {"background": ("paper.jpg", b"\xff\xd8\xff\xd9")},
        "credential without vc_template": {"credential": ("c.json", _json(no_mapping))},
        "credential not JSON": {"credential": ("c.json", b"{oops")},
        "sample not JSON": {"sample": ("s.json", b"{oops")},
        "template not UTF-8": {"template": ("t.html", b"<p>\xff\xfe</p>")},
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
        if case.startswith("background"):
            assert "PNG or JPEG" in res.json()["detail"], (case, res.json())
    assert client.get("/api/set").json() == before, "a rejected upload leaves the set as it was"


def test_background_over_the_decoded_bound_is_refused() -> None:
    """A small file can hold a huge image (a PNG of one colour): what the renderer decodes it to is bounded, which is
    pixels x channels x bytes per sample, read from the header."""
    import labset

    _upload_set()
    before = client.get("/api/set").json()
    bound = f"{labset.MAX_DECODED // 1_000_000} MB"
    over = {
        "an RGB PNG, 48 MB": ("paper.png", _png(4000, 4000, channels=3)),
        "a 16-bit RGBA PNG, 80 MB": ("paper.png", _png(2500, 4000, channels=4, depth=16)),
        "an RGBA PNG one pixel row over": ("paper.png", _png(2500, 4001, channels=4)),
        "a JPEG header, 1.2 GB": ("paper.jpg", _jpeg_header(20000, 20000)),
    }
    for case, file in over.items():
        res = _upload(background=file)
        assert res.status_code == 400, (case, res.status_code, res.text)
        assert bound in res.json()["detail"] and "decoded" in res.json()["detail"], (case, res.json())
    assert client.get("/api/set").json() == before
    for case, file in {"A4 at 300 dpi, RGBA": ("paper.png", _png(2480, 3508, channels=4)),
                       "16-bit grey at the bound": ("paper.png", _png(2500, 8000, depth=16)),
                       "RGBA at the bound": ("paper.png", _png(2500, 4000, channels=4))}.items():
        res = _upload(background=file)
        assert res.status_code == 200, (case, res.status_code, res.text)


def test_a_full_set_downloads_and_uploads_back() -> None:
    """The set's files together may reach MAX_SET, and then its zip (those files, incompressible, plus the zip's
    headers and long names) is still one request VC Lab takes. One byte more is refused, naming the overshoot."""
    import labset

    long = "n" * 250  # with the extension a 255-byte name
    template = b"<p>#claimValue('holderName')</p>"
    others = {"template": (long + ".html", template), "credential": (long + ".json", _json(CREDENTIAL)),
              "sample": (long + ".json", _json(SAMPLE))}
    room = labset.MAX_SET - len(template) - len(_json(CREDENTIAL)) - len(_json(SAMPLE))
    client.delete("/api/set")
    assert _upload(**others).status_code == 200

    over = _upload(background=(long + ".png", _png_of_size(room + 1)))
    detail = over.json().get("detail", "")
    assert over.status_code == 400 and "1 over" in detail and "in all" in detail, (over.status_code, detail)
    assert client.get("/api/set").json()["loaded"]["background"] is None, "the refused upload left the set as it was"

    assert _upload(background=(long + ".png", _png_of_size(room))).status_code == 200, "exactly MAX_SET"
    zipped = client.get("/download").content
    client.delete("/api/set")
    res = _upload(bundle=("vc-lab-set.zip", zipped))
    assert res.status_code == 200, (len(zipped), res.status_code, res.text)
    assert client.get("/api/set").json()["loaded"]["background"] == long + ".png"


def test_a_long_file_name_is_cut_to_255_bytes() -> None:
    _upload_set()
    for name in ("x" * 1000 + ".png", "ใบรับรอง" * 100 + ".png"):
        res = _upload(background=(name, _png(20, 30)))
        assert res.status_code == 200, res.text
        stored = res.json()["loaded"]["background"]
        assert len(stored.encode("utf-8")) <= 255 and stored.endswith(".png"), (len(stored.encode("utf-8")), stored[-12:])
        zipped = client.get("/download")
        assert zipped.status_code == 200, "Download works with a long name"
        with zipfile.ZipFile(io.BytesIO(zipped.content)) as z:
            assert f"background/{stored}" in z.namelist()


def test_an_old_zip_with_a_pdf_background_says_what_to_do() -> None:
    _upload_set()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("template/record.html", TEMPLATE)
        z.writestr("background/paper.pdf", _blank_pdf())
    res = _upload(bundle=("old.zip", out.getvalue()))
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "PNG or JPEG" in detail and "remove background/ from the zip, or upload the files one at a time" in detail, detail

    # A refusal that removing the Background or uploading one at a time can't help gets no such advice.
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("template/record.html", TEMPLATE)
        z.writestr("background/huge.png", _png(4000, 4000, channels=3))
    res = _upload(bundle=("big.zip", out.getvalue()))
    assert res.status_code == 400 and "decoded" in res.json()["detail"], res.text
    assert "remove background/" not in res.json()["detail"], res.json()


def _stand_in_renderer(bodies: list) -> HTTPServer:
    """A renderer that keeps each request it gets and answers a PDF, so VC Lab's request is what's asserted. It
    runs on a host too, without Compose."""
    class StandIn(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", "5")
            self.end_headers()
            self.wfile.write(b"%PDF-")

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_renderer_is_sent_the_uploaded_background() -> None:
    """VC Lab's side of the Background, without a renderer: `backgroundImage` is the upload as a data: URI,
    `null` with none or after Remove, and the same after a zip round trip."""
    bodies: list = []
    server = _stand_in_renderer(bodies)
    saved, vc_lab.RENDERER_URL = vc_lab.RENDERER_URL, f"http://127.0.0.1:{server.server_port}"
    try:
        def sent() -> object:
            assert client.get("/preview.pdf").status_code == 200
            return bodies[-1]["backgroundImage"]

        png, jpeg = _png(40, 50), JPEG_16X24
        as_uri = lambda kind, data: f"data:image/{kind};base64,{base64.b64encode(data).decode()}"  # noqa: E731
        _upload_print_set()
        assert sent() is None, "no upload"
        assert _upload(background=("paper.png", png)).status_code == 200
        assert sent() == as_uri("png", png)
        assert _upload(background=("scan.bin", jpeg)).status_code == 200
        assert sent() == as_uri("jpeg", jpeg), "the kind comes from the bytes, not the name"
        zipped = client.get("/download").content
        assert client.delete("/api/set/background").status_code == 200
        assert sent() is None, "after Remove"
        client.delete("/api/set")
        assert _upload(bundle=("vc-lab-set.zip", zipped)).status_code == 200
        assert sent() == as_uri("jpeg", jpeg), "after the zip round trip"
    finally:
        vc_lab.RENDERER_URL = saved
        server.shutdown()
        server.server_close()


def test_large_upload_stays_in_memory() -> None:
    """A file over Starlette's 1 MB spool limit (the AIT watermark is about 1 MB) never goes to a temp file."""
    spilled = []
    original = tempfile.SpooledTemporaryFile.rollover
    tempfile.SpooledTemporaryFile.rollover = lambda self: spilled.append(True) or original(self)
    try:
        _upload_set()
        big = b"<p>#claimValue('holderName')</p>" + b" " * (3 * 1024 * 1024)
        assert _upload(template=("big.html", big)).status_code == 200
        assert _upload(background=("big.png", _png(1200, 1800, noisy=True))).status_code == 200  # about 2 MB
    finally:
        tempfile.SpooledTemporaryFile.rollover = original
    assert not spilled, "the upload was written to a temporary file on disk"
    with _renderer_stand_in() as sent:
        request = sent()
        assert request["credentialSubject"]["holderName"] == "Ada Example" and len(request["template"]) > 3 * 1024 * 1024
        assert request["backgroundImage"].startswith("data:image/png;base64,")


def test_preview_pdf_prints_mapped_values() -> bool:
    if _no_renderer("test_preview_pdf_prints_mapped_values"):
        return False
    _upload_print_set()
    text, pages = _printed()
    assert "Holder: Ada Example" in text, "a mapped field"
    assert "Thesis: On Small Fixtures" in text, "a nested field (${thesis.title})"
    assert "Example Record" in text, "the title comes from the display entry"
    assert "Colours: #123456 on #ffffff, logo https://example.org/logo.png, validity -1" in text
    assert (400, 400) in _images(pages[0]), "a placeholder QR the size Mimoto draws it (mosip.inji.qr.code.width)"
    assert "$rowProperties" not in text and "#claimValue" not in text
    return True


def test_preview_pdf_prints_data_as_written() -> bool:
    """A claim that looks like template code prints as text: the data is never read as Velocity."""
    if _no_renderer("test_preview_pdf_prints_data_as_written"):
        return False
    note = "Costs in $titleName #if(1)x#end"
    client.delete("/api/set")
    res = _upload(template=("print.html", PRINT_TEMPLATE.encode()), credential=("print.json", _json(PRINT_CREDENTIAL)),
                  sample=("adapter-response.json", _json({"credentialSubject": {**PRINT_SUBJECT, "note": note}})))
    assert res.status_code == 200, res.text
    text, _ = _printed()
    assert f"Note: {note}" in text, "the claim, verbatim"
    return True


def test_preview_pdf_flattens_claims_as_mimoto_does() -> bool:
    if _no_renderer("test_preview_pdf_flattens_claims_as_mimoto_does"):
        return False
    _upload_print_set()
    text, _ = _printed()
    assert "Records: []" in text, "a list of objects (terms) prints as nothing"
    assert "Majors: [Fixtures, Seams]" in text, "a list of text prints as one ', '-joined string"
    assert "Honours: With distinction" in text, "an object prints as its value"
    return True


def test_preview_pdf_hands_every_claim_in_display_order() -> bool:
    if _no_renderer("test_preview_pdf_hands_every_claim_in_display_order"):
        return False
    _upload_print_set()
    text, _ = _printed()
    assert "Note: Printed from made-up data" in text, "a claim with no display entry still reaches the template"
    assert "Order: thesisTitle holderName terms majors honours courseRows printNote" in text, (
        "display_order first, then the other claims; id is not a claim to print")
    assert "Names: Thesis; Holder; Terms; Majors; Honours; Course Rows; Print Note;" in text, (
        "display names from the credential file, and a title-case fallback for a claim without one")
    return True


def test_preview_pdf_template_error_is_422_with_its_line() -> bool:
    if _no_renderer("test_preview_pdf_template_error_is_422_with_its_line"):
        return False
    cases = {
        "a directive Velocity can't parse": ("<html><body>\n<p>fine</p>\n<p>#set($x = )</p>\n</body></html>\n",
                                             ["Encountered", "line 3"]),
        # Java's split drops trailing empty fields: without -1 an ungraded course has 6 fields, not 7.
        "a field past the end of a split row": (
            '<html><body>\n#set($row = "C|XY102|Seams|0|45|3|")\n#set($f = $row.split("\\|"))<p>$f.get(6)</p>\n</body></html>\n',
            ["method 'get'", "line 3"]),
        # VC Lab uploads it: Velocity, not an upload check, says what's wrong and where.
        "a #foreach without its #end": (
            "<html><body>\n<p>fine</p>\n#foreach($e in $rowProperties.entrySet())\n<p>$e.key</p>\n</body></html>\n",
            ["Encountered", "line "]),
    }
    for case, (template, expected) in cases.items():
        _upload_print_set(template)
        res = client.get("/preview.pdf")
        assert res.status_code == 422, (case, res.status_code, res.text)
        assert all(part in res.json()["detail"] for part in expected), (case, res.json())
    return True


def test_preview_pdf_takes_any_velocity_1_7_directive() -> bool:
    """Velocity 1.7 has directives the old engine never knew (#define, #{end}); a template using them uploads
    and prints."""
    if _no_renderer("test_preview_pdf_takes_any_velocity_1_7_directive"):
        return False
    _upload_print_set("<html><body>\n#define($block)Defined block#{end}\n<p>$block</p>\n</body></html>\n")
    assert "Defined block" in _printed()[0]
    return True


def test_preview_pdf_answers_a_template_too_deep_to_print() -> bool:
    """Velocity parses nested blocks recursively; a template nested past the renderer's stack is the template's
    fault: 422, and the renderer keeps serving."""
    if _no_renderer("test_preview_pdf_answers_a_template_too_deep_to_print"):
        return False
    _upload_print_set("<html><body><p>" + "#if(true)" * 4000 + "deep" + "#end" * 4000 + "</p></body></html>\n")
    res = client.get("/preview.pdf")
    assert res.status_code == 422, (res.status_code, res.text[:300])
    assert "deep" in res.json()["detail"], res.json()
    _upload_print_set()
    assert "Holder: Ada Example" in _printed()[0], "the renderer still prints after it"
    return True


def test_preview_pdf_names_a_thai_file() -> bool:
    if _no_renderer("test_preview_pdf_names_a_thai_file"):
        return False
    _upload_print_set()
    assert _upload(template=("ใบ.html", PRINT_TEMPLATE.encode())).status_code == 200
    res = client.get("/preview.pdf")
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "filename*=UTF-8''%E0%B9%83%E0%B8%9A.pdf" in disposition, res.headers
    assert 'filename="__.pdf"' in disposition, "an ASCII name for clients that don't read filename*"
    return True


def test_preview_pdf_reports_any_renderer_refusal() -> bool:
    """A refusal that isn't the renderer's JSON (from a proxy in between, say) still reaches the designer as text,
    and the renderer's 503 stays a 503. A stand-in renderer answers here, so this runs without Compose too."""
    answers = [(400, b"plain refusal", "text/plain"), (503, b'{"error": "out of memory"}', "application/json")]

    class StandIn(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers["Content-Length"]))
            status, body, kind = answers.pop(0)
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    saved, vc_lab.RENDERER_URL = vc_lab.RENDERER_URL, f"http://127.0.0.1:{server.server_port}"
    try:
        _upload_print_set()
        res = client.get("/preview.pdf")
        assert (res.status_code, res.json()["detail"]) == (400, "plain refusal"), (res.status_code, res.text)
        res = client.get("/preview.pdf")
        assert (res.status_code, res.json()["detail"]) == (503, "out of memory"), (res.status_code, res.text)
    finally:
        vc_lab.RENDERER_URL = saved
        server.shutdown()
        server.server_close()
    return True


def test_preview_pdf_passes_on_what_the_renderer_refuses() -> bool:
    """A credential file the renderer can't read as Certify's is the upload's fault: 400 with the renderer's
    reason, not a 502."""
    if _no_renderer("test_preview_pdf_passes_on_what_the_renderer_refuses"):
        return False
    _upload_print_set()
    unreadable = {**PRINT_CREDENTIAL, "credential_subject": {"holderName": "Holder"}}  # an entry must be an object
    assert _upload(credential=("print.json", _json(unreadable))).status_code == 200
    res = client.get("/preview.pdf")
    assert res.status_code == 400, (res.status_code, res.text)
    assert "credentialFile" in res.json()["detail"] and "answered" not in res.json()["detail"], res.json()
    return True


def test_preview_pdf_takes_a_redefined_macro() -> bool:
    """Each preview is a first print: a macro that a replaced template redefines prints its new body, even one
    the earlier tests' template (PRINT_TEMPLATE) defined too."""
    if _no_renderer("test_preview_pdf_takes_a_redefined_macro"):
        return False
    printed = []
    for body in ("FIRST", "SECOND"):
        _upload_print_set(f'<html><body>\n#macro(claimValue $n){body}-$n#end\n<p>#claimValue("x")</p>\n</body></html>\n')
        printed.append(_printed()[0])
    assert "FIRST-x" in printed[0], printed[0]
    assert "SECOND-x" in printed[1], printed[1]
    return True


def test_preview_pdf_splits_course_rows() -> bool:
    if _no_renderer("test_preview_pdf_splits_course_rows"):
        return False
    _upload_print_set()
    text, _ = _printed()
    rows = ["ROW T / 5 fields: Term One 6", "ROW C / 7 fields: XY101 Fixture Design", "ROW C / 7 fields: XY102 Seams"]
    assert all(row in text for row in rows), text
    assert text.index(rows[0]) < text.index(rows[1]) < text.index(rows[2]), "rows print in the claim's order"
    return True


def test_preview_pdf_uses_only_the_standard_fonts() -> bool:
    """Mimoto's iText knows the 14 standard PDF fonts only; a template asking for another font gets one of them."""
    if _no_renderer("test_preview_pdf_uses_only_the_standard_fonts"):
        return False
    _upload_print_set()  # its body asks for "Noto Sans", FreeSans and Arial
    _, pages = _printed()
    fonts = {str(f.get_object()["/BaseFont"]).lstrip("/").split("+")[-1]
             for page in pages for f in page["/Resources"].get_object().get("/Font", {}).values()}
    assert fonts and fonts <= STANDARD_FONTS, fonts
    return True


# A template that draws $backgroundImage the way the Wallet's templates do (a CSS background over the whole
# page), and nothing else; #if because Velocity prints an unset variable as written.
BACKGROUND_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>$titleName</title>
<style>
  @page { size: A4; margin: 0; }
  body { margin: 0; }
  .page { position: relative; width: 595.28pt; height: 841.89pt; }
  .background { position: absolute; left: 0; top: 0; width: 595.28pt; height: 841.89pt; }
  .content { position: absolute; left: 30pt; top: 30pt; width: 535pt; }  /* a flowing <p> would push the box down */
</style>
#macro(claimValue $claimName)#set($__claim = $rowProperties.get($claimName))#if($__claim)#foreach($__entry in $__claim.entrySet())$__entry.value#end#end#end
</head>
<body>
<div class="page">
#if($backgroundImage && $backgroundImage != "")<img class="background" src="$backgroundImage"/>#end
<div class="content"><p>Holder: #claimValue("holderName")</p></div>
</div>
</body></html>
"""


def _upload_background_set(**extra: tuple[str, bytes]) -> None:
    client.delete("/api/set")
    res = _upload(template=("paper.html", BACKGROUND_TEMPLATE.encode()),
                  credential=("print.json", _json(PRINT_CREDENTIAL)),
                  sample=("adapter-response.json", _json({"credentialSubject": PRINT_SUBJECT})), **extra)
    assert res.status_code == 200, res.text


def _printed_rects() -> list[dict]:
    """Every image the first page draws: its pixel size and the rectangle it covers, in points (as print_check does)."""
    text, pages = _printed()
    assert "Holder: Ada Example" in text, text
    return _drawn_images(pages[0])


def _printed_images() -> list[tuple[int, int]]:
    return [rect["px"] for rect in _printed_rects()]


def _on_the_whole_page(rect: dict) -> bool:
    """Drawn from the page's corner at the page's size, A4 in points: 595.28 x 841.89."""
    return (abs(rect["x"]) < 1.5 and abs(rect["y"]) < 1.5
            and abs(rect["w"] - 595.28) < 1.5 and abs(rect["h"] - 841.89) < 1.5)


def test_background_png_lands_as_the_pages_image() -> bool:
    if _no_renderer("test_background_png_lands_as_the_pages_image"):
        return False
    _upload_background_set()
    assert _printed_images() == [], "no Background, no image"
    assert _upload(background=("paper.png", _png(120, 160))).json()["loaded"]["background"] == "paper.png"
    assert _printed_images() == [(120, 160)], "the PNG, at its own pixel size"
    assert _on_the_whole_page(_printed_rects()[0]), ("full size: from the corner, over the whole A4 page", _printed_rects())
    return True


def test_background_jpeg_lands_as_the_pages_image() -> bool:
    if _no_renderer("test_background_jpeg_lands_as_the_pages_image"):
        return False
    _upload_background_set(background=("paper.jpg", JPEG_16X24))
    assert _printed_images() == [(16, 24)], "the JPEG, at its own pixel size"
    assert _on_the_whole_page(_printed_rects()[0]), _printed_rects()
    return True


def test_the_worst_accepted_background_prints_four_at_once() -> bool:
    """The bound is chosen so the renderer's heap copes with the biggest Background VC Lab accepts, in the formats
    that decode largest, each with about 7 MB of noise (the upload cap's worth), four prints at once."""
    if _no_renderer("test_the_worst_accepted_background_prints_four_at_once"):
        return False
    import labset
    from concurrent.futures import ThreadPoolExecutor

    worst = {  # name: (width, channels, depth); the height is what the bound allows
        "8-bit RGBA": (2500, 4, 8),
        "16-bit RGBA": (2000, 4, 16),
        "16-bit RGB": (2500, 3, 16),
    }
    for kind, (width, channels, depth) in worst.items():
        height = labset.MAX_DECODED // (width * channels * depth // 8)
        _upload_background_set(background=("big.png", _png(width, height, channels=channels, depth=depth,
                                                            noise_bytes=7_000_000)))
        rects = _printed_rects()
        assert [r["px"] for r in rects] == [(width, height)] and _on_the_whole_page(rects[0]), (kind, rects)
        with ThreadPoolExecutor(4) as pool:
            answers = list(pool.map(lambda _: client.get("/preview.pdf"), range(4)))
        assert [a.status_code for a in answers] == [200] * 4, (kind, [(a.status_code, a.text[:120]) for a in answers])
    return True


def _serve_png(png: bytes) -> HTTPServer:
    """A stand-in VDR, reachable from the renderer's container by this container's address."""
    class Vdr(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.end_headers()
            self.wfile.write(png)

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("0.0.0.0", 0), Vdr)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _with_published_background(server: HTTPServer) -> dict:
    """PRINT_CREDENTIAL with display[0].background_image.uri pointing at the stand-in VDR."""
    uri = f"http://{socket.gethostbyname(socket.gethostname())}:{server.server_port}/background.png"
    first = {**PRINT_CREDENTIAL["display"][0], "background_image": {"uri": uri}}
    return {**PRINT_CREDENTIAL, "display": [first]}


def test_no_background_uploaded_uses_the_credential_files_address() -> bool:
    if _no_renderer("test_no_background_uploaded_uses_the_credential_files_address"):
        return False
    server = _serve_png(_png(90, 60))
    try:
        _upload_background_set()
        credential = _with_published_background(server)
        assert _upload(credential=("print.json", _json(credential))).status_code == 200
        assert _printed_images() == [(90, 60)], "the published image, fetched by the renderer"
        assert _upload(background=("paper.png", _png(120, 160))).status_code == 200
        assert _printed_images() == [(120, 160)], "an upload overrides display[0].background_image.uri"
    finally:
        server.shutdown()
        server.server_close()
    return True


def test_remove_background_goes_back_to_the_files_address_or_none() -> bool:
    if _no_renderer("test_remove_background_goes_back_to_the_files_address_or_none"):
        return False
    server = _serve_png(_png(90, 60))
    try:
        _upload_background_set()
        assert _upload(credential=("print.json", _json(_with_published_background(server)))).status_code == 200
        assert _upload(background=("paper.png", _png(120, 160))).status_code == 200
        assert client.delete("/api/set/background").status_code == 200
        assert _printed_images() == [(90, 60)], "back to the credential file's address"
        assert _upload(background=("paper.png", _png(120, 160))).status_code == 200
        assert _upload(credential=("print.json", _json(PRINT_CREDENTIAL))).status_code == 200
        assert client.delete("/api/set/background").status_code == 200
        assert _printed_images() == [], "no address in the credential file: no Background"
    finally:
        server.shutdown()
        server.server_close()
    return True


def test_background_survives_download_and_upload_back() -> bool:
    if _no_renderer("test_background_survives_download_and_upload_back"):
        return False
    for name, image in (("paper.png", _png(120, 160)), ("paper.jpeg", JPEG_16X24)):
        _upload_background_set(background=(name, image))
        before = (client.get("/api/set").json(), _printed())
        res = client.get("/download")
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            assert z.read(f"background/{name}") == image, "the Background as the image that was uploaded"
        client.delete("/api/set")
        assert _upload(bundle=("vc-lab-set.zip", res.content)).status_code == 200
        after = (client.get("/api/set").json(), _printed())
        assert after[0] == before[0], name
        assert after[1][0] == before[1][0] and [_images(p) for p in after[1][1]] == [_images(p) for p in before[1][1]]
    return True


def test_preview_pdf_of_the_committed_transcript_template_leaves_a_missing_claim_empty() -> bool:
    """The committed AIT template's claimValue macro must print nothing for a claim the credential lacks. Velocity 1.7
    keeps a variable's old value when #set is given null, so without a reset in the macro, a missing claim printed the
    one before it. Made-up data: no country and no option, each printed straight after a claim with its own value."""
    if _no_renderer("test_preview_pdf_of_the_committed_transcript_template_leaves_a_missing_claim_empty"):
        return False
    template = REPO_ROOT / "deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html"
    credential = REPO_ROOT / "deploy/ait/certify/credentials/ait-transcript.json"
    record = {"fullName": "Mina Example", "dateOfBirth": "1999-01-02", "registrationNo": "st000001",
              "dateAdmitted": "2020-03-04", "degreeAwarded": "Master of Examples", "academicProgram": "M.Ex Fixtures"}
    client.delete("/api/set")
    res = _upload(template=(template.name, template.read_bytes()), credential=(credential.name, credential.read_bytes()),
                  sample=("record.json", _json(record)))
    assert res.status_code == 200, res.text
    text, _ = _printed()
    assert "Mina Example" in text and "1999-01-02" in text and "2020-03-04" in text, "the claims it has print"
    assert text.count("1999-01-02") == 1, "the date of birth printed once: country has no value"
    assert text.count("2020-03-04") == 1, "the date admitted printed once: option has no value"
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
        test_the_old_rendering_endpoints_are_gone,
        test_the_renderer_is_sent_the_mapped_claims,
        test_replace_one_slot,
        test_remove_background_then_clear,
        test_download_and_upload_back,
        test_rejects_wrong_files,
        test_large_upload_stays_in_memory,
        test_preview_pdf_prints_mapped_values,
        test_preview_pdf_prints_data_as_written,
        test_preview_pdf_flattens_claims_as_mimoto_does,
        test_preview_pdf_hands_every_claim_in_display_order,
        test_preview_pdf_template_error_is_422_with_its_line,
        test_preview_pdf_splits_course_rows,
        test_preview_pdf_of_the_committed_transcript_template_leaves_a_missing_claim_empty,
        test_preview_pdf_uses_only_the_standard_fonts,
        test_preview_pdf_takes_a_redefined_macro,
        test_preview_pdf_takes_any_velocity_1_7_directive,
        test_preview_pdf_names_a_thai_file,
        test_preview_pdf_passes_on_what_the_renderer_refuses,
        test_preview_pdf_answers_a_template_too_deep_to_print,
        test_preview_pdf_reports_any_renderer_refusal,
        test_background_over_the_decoded_bound_is_refused,
        test_a_full_set_downloads_and_uploads_back,
        test_a_long_file_name_is_cut_to_255_bytes,
        test_an_old_zip_with_a_pdf_background_says_what_to_do,
        test_the_renderer_is_sent_the_uploaded_background,
        test_the_worst_accepted_background_prints_four_at_once,
        test_background_png_lands_as_the_pages_image,
        test_background_jpeg_lands_as_the_pages_image,
        test_no_background_uploaded_uses_the_credential_files_address,
        test_remove_background_goes_back_to_the_files_address_or_none,
        test_background_survives_download_and_upload_back,
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
