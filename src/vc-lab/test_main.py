"""VC Lab's web API, driven the way the dashboard drives it, with a small made-up set.

Run:
    python3 src/vc-lab/test_main.py

The preview tests need the renderer (src/renderer) at RENDERER_URL and skip without it. Inside Compose, VC Lab has
it: `docker compose run --rm vc-lab python src/vc-lab/test_main.py`. The Background conversion tests need none.
"""

from __future__ import annotations

import base64
import html
import io
import json
import struct
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
import pypdfium2  # noqa: E402
from PIL import Image  # noqa: E402
from pypdf import PdfReader, PdfWriter  # noqa: E402
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, TextStringObject  # noqa: E402

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
# The Adapter's record, flat, as the Adapter contract (docs/contracts/adapter-openapi.yaml) has it.
SAMPLE = {
    "name": "Ada Example",
    "thesisTitle": "On Small Fixtures",
    "courses": [
        {"label": "Term One", "items": [{"code": "XY101", "title": "Fixture Design", "grade": "A"},
                                        {"code": "XY102", "title": TRICKY_TITLE, "grade": "B+"}]},
        {"label": "Term Two", "items": [{"code": "XY201", "title": "Seams", "grade": "A"}]},
    ],
}


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


# What the dashboard asks Export Package for, with the VDR address as a person types it (trailing slash and all).
LOCAL_VDR = "http://vdr.localhost"
EXPORT = {"config_id": "example-record", "version": "v1", "vdr_address": "https://vdr.example.org/"}
PACKAGE_DIR = "vdr/templates/example-record/v1"


def _export(files: dict[str, tuple[str, bytes]], **params: str):
    """Export Package: the set as the dashboard holds it, plus the config id, the version and the VDR address."""
    return client.post("/api/package/export", files=files, data={**EXPORT, **params})


def _read(package: bytes):
    return client.post("/api/package/read", files={"package": ("package.zip", package)})


def _read_set(package: bytes) -> dict[str, tuple[str, bytes]]:
    """A Package read back, as the dashboard would hold it: {slot: (filename, data)}."""
    res = _read(package)
    assert res.status_code == 200, res.text
    return {slot: (f["filename"], base64.b64decode(f["data"])) for slot, f in res.json()["set"].items()}


# A set whose template and credential file carry the local stack's addresses, as the committed ones do.
LOCAL_TEMPLATE = TEMPLATE.replace("</body>", '<img src="http://cdn.localhost/logo.png"/>'
                                  '<link href="http://vdr.localhost/fonts/f.css"/></body>')
LOCAL_CREDENTIAL = {**CREDENTIAL, "display": [{**CREDENTIAL["display"][0],
                                               "logo": {"url": "http://cdn.localhost/logo.png"},
                                               "background_image": {"uri": "http://vdr.localhost/old/background.png"}}]}


def _png(width: int = 40, height: int = 60, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), color).save(out, "PNG")
    return out.getvalue()


def _jpeg(width: int = 40, height: int = 60) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (30, 30, 200)).save(out, "JPEG")
    return out.getvalue()


def _pdf(width: float, height: float, rotate: int = 0, crop: tuple[float, float, float, float] | None = None,
         pages: int = 1) -> bytes:
    """Pages of `width` x `height` points, each with a red 50 x 50 square at the bottom-left of the stored page."""
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=width, height=height)
        stream = DecodedStreamObject()
        stream.set_data(b"1 0 0 rg 0 0 50 50 re f")
        page[NameObject("/Contents")] = writer._add_object(stream)
        if rotate:
            page.rotate(rotate)
        if crop:
            page.cropbox.lower_left, page.cropbox.upper_right = crop[:2], crop[2:]
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _signed_pdf(width: float, height: float) -> bytes:
    """A page whose only mark is a signature field (/Widget, /FT /Sig) with a red appearance in [100 100 200 200]."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=width, height=height)
    form = DecodedStreamObject()
    form.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"),
                 NameObject("/BBox"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(100), NumberObject(100)])})
    form.set_data(b"1 0 0 rg 0 0 100 100 re f")
    widget = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Widget"),
        NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject("Signature1"),
        NameObject("/F"): NumberObject(4),
        NameObject("/Rect"): ArrayObject([NumberObject(v) for v in (100, 100, 200, 200)]),
        NameObject("/AP"): DictionaryObject({NameObject("/N"): writer._add_object(form)})}))
    page[NameObject("/Annots")] = ArrayObject([widget])
    writer._root_object[NameObject("/AcroForm")] = DictionaryObject({
        NameObject("/Fields"): ArrayObject([widget]), NameObject("/SigFlags"): NumberObject(1)})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _cmyk_profile() -> bytes:
    """A made-up CMYK ICC profile (v2, lut8) that prints every ink as grey: no ink is white, and the more ink the
    darker. It is nothing like Pillow's naive CMYK to RGB, where full cyan is (0, 255, 255)."""
    clut = bytearray()
    for c in (0, 1):
        for m in (0, 1):
            for y in (0, 1):
                for k in (0, 1):
                    clut += bytes([round(255 * (1 - k) * (1 - 0.5 * (c + m + y) / 3)), 128, 128])
    ramp = bytes(range(256))
    identity = struct.pack(">9i", 65536, 0, 0, 0, 65536, 0, 0, 0, 65536)
    lut = b"mft1" + bytes(4) + bytes([4, 3, 2, 0]) + identity + ramp * 4 + bytes(clut) + ramp * 3
    text = lambda t: b"text" + bytes(4) + t + b"\0"
    desc = b"desc" + bytes(4) + struct.pack(">I", 5) + b"test\0" + bytes(4 + 4 + 2 + 1 + 67)
    xyz = b"XYZ " + bytes(4) + struct.pack(">3i", 63190, 65536, 54061)
    tags = [(b"desc", desc), (b"cprt", text(b"none")), (b"wtpt", xyz), (b"A2B0", lut)]
    offset = 128 + 4 + 12 * len(tags)
    table, body = b"", b""
    for sig, data in tags:
        data += bytes(-len(data) % 4)
        table += sig + struct.pack(">II", offset + len(body), len(data))
        body += data
    header = struct.pack(">I4sI4s4s4s", 0, b"none", 0x02100000, b"prtr", b"CMYK", b"Lab ") + bytes(12) + b"acsp" + bytes(28)
    header += struct.pack(">3i", 63190, 65536, 54061) + bytes(48)
    profile = header + struct.pack(">I", len(tags)) + table + body
    return struct.pack(">I", len(profile)) + profile[4:]


def _image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


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


def _pages(files: dict[str, tuple[str, bytes]]) -> list:
    res = _post("/preview.pdf", files)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    return PdfReader(io.BytesIO(res.content)).pages


def _skip_without_renderer(test: str) -> bool:
    """True, after printing SKIP, when this host has no renderer to call."""
    if not os.environ.get("RENDERER_URL"):
        print(f"SKIP {test} (no RENDERER_URL)")
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
    _export(_set())
    for method, path in (("get", "/api/set"), ("post", "/api/set"), ("delete", "/api/set"),
                         ("delete", "/api/set/background"), ("get", "/preview"), ("get", "/preview.pdf"),
                         ("get", "/api/package/export"), ("get", "/api/package/read")):
        res = getattr(client, method)(path)
        assert res.status_code in (404, 405), (method, path, res.status_code)


def test_download_and_the_bundle_are_gone() -> None:
    """Export Package replaces Download, and read Package replaces the bundle: neither endpoint nor button remains."""
    assert _post("/download", _set()).status_code == 404
    assert client.post("/api/bundle", files={"bundle": ("set.zip", _zip_of({"template/t.html": b"x"}))}).status_code == 404
    page = client.get("/").text
    assert "Export Package" in page and "Load Package" in page
    assert "/download" not in page and "/api/bundle" not in page and ">Download<" not in page


def test_every_call_asks_for_what_it_was_not_sent() -> None:
    """Nothing is remembered between calls: a call without the credential file and the sample is asked for them,
    though the full set was sent a moment ago."""
    assert _export(_set()).status_code == 200
    for res in (_post("/preview", _set(credential=None, sample=None)),
                _post("/preview.pdf", _set(credential=None, sample=None)),
                _export(_set(credential=None, sample=None))):
        assert res.status_code == 409, res.status_code
        assert "credential" in res.json()["detail"] and "sample" in res.json()["detail"]
        assert "template" not in res.json()["detail"]
    assert _export({}).status_code == 400, "no file sent, no Package"


def test_two_visitors_each_get_their_own_package() -> None:
    mine = _set(template=("mine.html", b"<p>mine</p>"), background=("background.png", _png()))
    theirs = _set(template=("theirs.html", b"<p>theirs</p>"))
    first = _export(mine)
    second = _export(theirs)
    again = _export(mine)
    assert first.status_code == second.status_code == again.status_code == 200
    assert _zip_files(second.content)[f"{PACKAGE_DIR}/template.html"] == b"<p>theirs</p>"
    assert f"{PACKAGE_DIR}/background.png" not in _zip_files(second.content), "no Background of the other visitor's"
    assert _zip_files(first.content) == _zip_files(again.content)
    assert f"{PACKAGE_DIR}/background.png" in _zip_files(first.content)


def test_export_package_lays_the_files_out_as_the_vdr_and_certify_take_them() -> None:
    paper = _png()
    files = _set(template=("record.html", LOCAL_TEMPLATE.encode()), credential=("record.json", _json(LOCAL_CREDENTIAL)),
                 background=("../../secret/paper.png", paper))
    res = _export(files)
    assert res.status_code == 200 and res.headers["content-type"] == "application/zip", res.text
    zipped = _zip_files(res.content)
    assert sorted(zipped) == sorted(["certify/credentials/example-record.json", f"{PACKAGE_DIR}/background.png",
                                     f"{PACKAGE_DIR}/manifest.json", f"{PACKAGE_DIR}/template.html",
                                     "sample/adapter-response.json"])
    assert zipped[f"{PACKAGE_DIR}/background.png"] == paper

    template = zipped[f"{PACKAGE_DIR}/template.html"].decode()
    assert "https://vdr.example.org/logo.png" in template and "https://vdr.example.org/fonts/f.css" in template
    assert "localhost" not in template, "every local address rewritten, the trailing slash removed"
    assert template == LOCAL_TEMPLATE.replace("http://cdn.localhost", "https://vdr.example.org") \
        .replace("http://vdr.localhost", "https://vdr.example.org")

    credential = json.loads(zipped["certify/credentials/example-record.json"])
    assert "localhost" not in json.dumps(credential)
    assert credential["display"][0]["logo"] == {"url": "https://vdr.example.org/logo.png"}
    assert credential["display"][0]["background_image"]["uri"] == \
        "https://vdr.example.org/templates/example-record/v1/background.png"
    assert credential["vc_template"] == CREDENTIAL["vc_template"], "only the addresses and the Background's change"

    assert json.loads(zipped["sample/adapter-response.json"]) == SAMPLE, "the sample goes as it is"


def test_the_manifest_names_the_config_the_version_the_vdr_and_each_component_with_its_role() -> None:
    manifest = json.loads(_zip_files(_export(_set(background=("background.png", _png()))).content)
                          [f"{PACKAGE_DIR}/manifest.json"])
    assert manifest["credentialConfigId"] == "example-record" and manifest["version"] == "v1"
    assert manifest["vdrAddress"] == "https://vdr.example.org", "as exported, without the trailing slash"
    assert manifest["components"] == [
        {"role": "template", "path": f"{PACKAGE_DIR}/template.html", "deploy": True},
        {"role": "background", "path": f"{PACKAGE_DIR}/background.png", "deploy": True},
        {"role": "credential", "path": "certify/credentials/example-record.json", "deploy": True},
        {"role": "sample", "path": "sample/adapter-response.json", "deploy": False},
    ]


def test_export_without_a_background_writes_none_and_leaves_the_credential_files_address() -> None:
    files = _set(credential=("record.json", _json(LOCAL_CREDENTIAL)))
    zipped = _zip_files(_export(files).content)
    assert f"{PACKAGE_DIR}/background.png" not in zipped
    credential = json.loads(zipped["certify/credentials/example-record.json"])
    assert credential["display"][0]["background_image"]["uri"] == "https://vdr.example.org/old/background.png", \
        "as it was, with only the local address rewritten"
    manifest = json.loads(zipped[f"{PACKAGE_DIR}/manifest.json"])
    assert [c["role"] for c in manifest["components"]] == ["template", "credential", "sample"]
    bare = json.loads(_zip_files(_export(_set()).content)["certify/credentials/example-record.json"])
    assert bare["display"] == CREDENTIAL["display"], "no display[0].background_image invented"


def test_the_backgrounds_address_goes_into_the_credential_file_and_a_templates_addresses_stay_as_they_are() -> None:
    """The Package holds background.png under <config id>/<version>, and the credential file names it there: the
    Wallet fills $backgroundImage from display[0].background_image.uri. A template's addresses are not the Background's."""
    template = TEMPLATE.replace("</body>", '<img src="http://vdr.localhost/templates/example-record/background.png"/>'
                                '<img src="http://vdr.localhost/templates/a/b/background.png"/></body>')
    files = _set(template=("record.html", template.encode()), background=("background.png", _png()))
    zipped = _zip_files(_export(files, version="v2").content)
    exported = zipped["vdr/templates/example-record/v2/template.html"].decode()
    assert exported == template.replace(LOCAL_VDR, "https://vdr.example.org"), "only the local host, rewritten"
    credential = json.loads(zipped["certify/credentials/example-record.json"])
    assert credential["display"][0]["background_image"]["uri"] == \
        "https://vdr.example.org/templates/example-record/v2/background.png"


def test_the_config_id_must_be_the_credential_files_key() -> None:
    res = _export(_set(), config_id="other-id")
    assert res.status_code == 400
    assert "other-id" in res.json()["detail"] and "example-record" in res.json()["detail"]
    no_key = {k: v for k, v in CREDENTIAL.items() if k != "credential_config_key_id"}
    assert _export(_set(credential=("c.json", _json(no_key)))).status_code == 400


def test_a_sample_named_manifest_json_still_reads_back() -> None:
    files = _set(sample=("manifest.json", _json(SAMPLE)))
    package = _export(files).content
    assert "sample/manifest.json" in _zip_files(package)
    assert _read_set(package)["sample"] == ("manifest.json", _json(SAMPLE))


def test_a_background_image_that_is_not_an_object_is_replaced_by_the_address() -> None:
    for value in (None, "old.png", 3, ["x"]):
        credential = {**CREDENTIAL, "display": [{**CREDENTIAL["display"][0], "background_image": value}]}
        res = _export(_set(credential=("c.json", _json(credential)), background=("background.png", _png())))
        assert res.status_code == 200, (value, res.text)
        written = json.loads(_zip_files(res.content)["certify/credentials/example-record.json"])
        assert written["display"][0]["background_image"] == {
            "uri": "https://vdr.example.org/templates/example-record/v1/background.png"}, value


def test_export_asks_for_a_config_id_a_version_and_an_address() -> None:
    for case, params in {"no config id": {"config_id": ""}, "no version": {"version": " "},
                         "no VDR address": {"vdr_address": ""}, "an address that is no URL": {"vdr_address": "vdr"}}.items():
        res = _export(_set(), **params)
        assert res.status_code == 400 and isinstance(res.json()["detail"], str), (case, res.status_code)
    res = client.post("/api/package/export", files=_set(), data={"config_id": "x"})
    assert res.status_code == 400, "version and address are asked for"


def test_a_package_reads_back_as_the_set_with_the_vdr_address_turned_back_to_local() -> None:
    paper = _png()
    files = _set(template=("record.html", LOCAL_TEMPLATE.encode()), credential=("record.json", _json(LOCAL_CREDENTIAL)),
                 background=("background.png", paper))
    package = _export(files).content
    res = _read(package)
    assert res.status_code == 200, res.text
    assert res.json()["export"] == {"configId": "example-record", "version": "v1",
                                    "vdrAddress": "https://vdr.example.org"}, "to pre-fill the next export"
    got = _read_set(package)
    assert sorted(got) == ["background", "credential", "sample", "template"]
    assert got["background"] == ("background.png", paper)
    assert got["sample"] == ("adapter-response.json", _json(SAMPLE))
    assert got["template"] == ("template.html", LOCAL_TEMPLATE.replace("http://cdn.localhost", LOCAL_VDR).encode()), \
        "local addresses again; cdn.localhost stays the VDR's"
    credential = json.loads(got["credential"][1])
    assert got["credential"][0] == "example-record.json"
    assert credential["display"][0]["logo"] == {"url": "http://vdr.localhost/logo.png"}
    assert credential["display"][0]["background_image"]["uri"] == \
        "http://vdr.localhost/templates/example-record/v1/background.png", "stays set, local"
    assert credential["vc_template"] == CREDENTIAL["vc_template"]
    # What was read exports to the same Package: the round trip is stable.
    again = _export(got, config_id="example-record", version="v1", vdr_address="https://vdr.example.org").content
    assert _zip_files(again) == _zip_files(package)


def test_a_package_without_a_background_reads_back_without_one() -> None:
    got = _read_set(_export(_set()).content)
    assert sorted(got) == ["credential", "sample", "template"]


def test_read_package_accepts_only_the_exported_layout() -> None:
    good = _zip_files(_export(_set(background=("background.png", _png()))).content)

    def broken(**changes: bytes | None) -> bytes:
        members = {**good, **changes}
        return _zip_of({name: data for name, data in members.items() if data is not None})

    cases = {
        "not a zip": b"not a zip",
        "no files": _empty_zip(),
        "no manifest": broken(**{f"{PACKAGE_DIR}/manifest.json": None}),
        "manifest not JSON": broken(**{f"{PACKAGE_DIR}/manifest.json": b"{oops"}),
        "template missing": broken(**{f"{PACKAGE_DIR}/template.html": None}),
        "credential file missing": broken(**{"certify/credentials/example-record.json": None}),
        "sample missing": broken(**{"sample/adapter-response.json": None}),
        "a Background the manifest does not list": broken(**{f"{PACKAGE_DIR}/manifest.json": json.dumps(
            {**json.loads(good[f"{PACKAGE_DIR}/manifest.json"]), "components": [
                c for c in json.loads(good[f"{PACKAGE_DIR}/manifest.json"])["components"]
                if c["role"] != "background"]}).encode()}),
        "a file the manifest does not list": broken(**{"notes/readme.txt": b"hi"}),
        "a bundle from the old Download": _zip_of({"template/record.html": b"<p/>"}),
        "a credential file without a vc_template": broken(**{"certify/credentials/example-record.json": b"{}"}),
    }
    for case, package in cases.items():
        res = _read(package)
        assert res.status_code == 400, (case, res.status_code, res.text)
        assert isinstance(res.json()["detail"], str) and res.json()["detail"], case


def test_rejects_wrong_files() -> None:
    no_mapping = {k: v for k, v in CREDENTIAL.items() if k != "vc_template"}
    cases = {
        "background not a PNG": {"background": ("background.png", b"\x89PNG\r\n\x1a\n not a png")},
        "background a PDF, which the set does not keep": {"background": ("paper.pdf", _pdf(200, 300))},
        "credential without vc_template": {"credential": ("c.json", _json(no_mapping))},
        "credential not JSON": {"credential": ("c.json", b"{oops")},
        "sample not JSON": {"sample": ("s.json", b"{oops")},
        "sample not an object": {"sample": ("s.json", b"[1]")},
        "credential with display not a list": {"credential": ("c.json", _json({**CREDENTIAL, "display": {"name": "x"}}))},
        "credential with a logo not an object": {
            "credential": ("c.json", _json({**CREDENTIAL, "display": [{"name": "x", "logo": "logo.png"}]}))},
        "unknown field": {"stylesheet": ("s.css", b"p {}")},
    }
    for case, changes in cases.items():
        for path, send in (("/preview", _post), ("/preview.pdf", _post), ("export", lambda _, f: _export(f))):
            res = send(path, _set(**changes))
            assert res.status_code == 400, (case, path, res.status_code, res.text)
            assert isinstance(res.json()["detail"], str) and res.json()["detail"], (case, path)
def test_a_request_over_20_mb_is_refused() -> None:
    assert vc_lab.MAX_UPLOAD == 20 * 1024 * 1024
    big = b"<p>big</p>" + b" " * (15 * 1024 * 1024)
    assert _export(_set(template=("big.html", big))).status_code == 200, "15 MB fits"
    too_big = b"<p>big</p>" + b" " * (vc_lab.MAX_UPLOAD + 1)
    for res in (_post("/preview", _set(template=("big.html", too_big))),
                _post("/preview.pdf", _set(template=("big.html", too_big))),
                _export(_set(template=("big.html", too_big))), _read(too_big)):
        assert res.status_code == 400 and "20 MB" in res.json()["detail"], res.status_code


def test_one_visitors_slow_render_does_not_block_another() -> None:
    """A preview waiting on a slow renderer must not freeze the Lab for everyone else: a real server, the renderer
    call patched to take 2 s, and /health asked half a second into it."""
    import socket
    import threading
    import time

    import httpx
    import uvicorn

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(vc_lab.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started

    original_post, original_url = vc_lab.httpx.post, vc_lab.RENDERER_URL
    vc_lab.RENDERER_URL = "http://renderer.invalid"
    vc_lab.httpx.post = lambda *a, **k: time.sleep(2) or httpx.Response(200, content=b"<p>slow</p>")
    try:
        slow = threading.Thread(target=lambda: httpx.Client().post(base + "/preview", files=_set(), timeout=30))
        slow.start()
        time.sleep(0.5)
        started = time.monotonic()
        assert httpx.get(base + "/health", timeout=30).status_code == 200
        waited = time.monotonic() - started
        slow.join()
    finally:
        vc_lab.httpx.post, vc_lab.RENDERER_URL = original_post, original_url
        server.should_exit = True
    assert waited < 1, f"/health waited {waited:.1f} s behind another visitor's preview"


def test_large_upload_stays_in_memory() -> None:
    """A file over Starlette's 1 MB spool limit (the AIT watermark is about 1 MB) never goes to a temp file."""
    spilled = []
    original = tempfile.SpooledTemporaryFile.rollover
    tempfile.SpooledTemporaryFile.rollover = lambda self: spilled.append(True) or original(self)
    try:
        big = b"<p>big</p>" + b" " * (3 * 1024 * 1024)
        assert _export(_set(template=("big.html", big))).status_code == 200
    finally:
        tempfile.SpooledTemporaryFile.rollover = original
    assert not spilled, "the upload was written to a temporary file on disk"


def _background(filename: str, data: bytes):
    return client.post("/api/background", files={"background": (filename, data)})


def test_a_png_background_is_kept_as_is() -> None:
    png = _png(37, 91)
    res = _background("logo-and-seal.png", png)
    assert res.status_code == 200 and res.headers["content-type"] == "image/png", res.text
    assert res.content == png


def test_a_jpeg_background_becomes_a_png_of_its_own_size() -> None:
    res = _background("scan.jpg", _jpeg(50, 70))
    assert res.status_code == 200 and res.headers["content-type"] == "image/png", res.text
    image = _image(res.content)
    assert image.format == "PNG" and image.size == (50, 70)


def test_a_pdf_background_is_drawn_at_its_page_size_and_150_dpi() -> None:
    res = _background("paper.pdf", _pdf(612, 792, pages=2))
    assert res.status_code == 200 and res.headers["content-type"] == "image/png", res.text
    image = _image(res.content)
    assert image.format == "PNG" and max(abs(image.width - 1275), abs(image.height - 1650)) <= 1, \
        ("612 x 792 points at 150 dpi, page 1 only", image.size)
    image = image.convert("RGB")
    assert image.getpixel((10, 1635)) == (255, 0, 0), "the red square sits at the page's bottom-left"
    assert image.getpixel((1200, 50)) == (255, 255, 255), "paper is white where nothing is drawn"


def test_a_pdf_background_keeps_its_rotation_and_crop_box() -> None:
    turned = _image(_background("paper.pdf", _pdf(300, 200, rotate=90)).content).convert("RGB")
    assert turned.size == (417, 625), "a viewer shows a /Rotate 90 page upright: 200 x 300 points"
    assert turned.getpixel((10, 10)) == (255, 0, 0), "the stored bottom-left is the top-left after turning clockwise"
    assert turned.getpixel((10, 600)) == (255, 255, 255)

    cropped = _image(_background("paper.pdf", _pdf(400, 400, crop=(100, 100, 300, 400))).content).convert("RGB")
    assert cropped.size == (417, 625), "the crop box, 200 x 300 points, is the page"
    assert cropped.getpixel((10, 600)) == (255, 255, 255), "the square at the stored corner is cropped out"


def test_a_jpeg_background_is_turned_upright_by_its_exif_orientation() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # stored 80 x 40; a viewer turns it a quarter clockwise, to 40 x 80
    out = io.BytesIO()
    image = Image.new("RGB", (80, 40), (255, 255, 255))
    image.paste((255, 0, 0), (0, 0, 10, 10))  # the stored top-left corner
    image.save(out, "JPEG", quality=100, exif=exif)
    png = _image(_background("phone.jpg", out.getvalue()).content).convert("RGB")
    assert png.size == (40, 80), "as every viewer shows it"
    r, g, b = png.getpixel((35, 5))
    assert r > 200 and g < 80 and b < 80, "the stored top-left corner is the top-right after a quarter turn clockwise"


def test_a_pdf_background_draws_its_signature_field() -> None:
    png = _image(_background("signed.pdf", _signed_pdf(300, 400)).content).convert("RGB")
    assert png.getpixel((312, 520)) == (255, 0, 0), "the field's appearance, drawn where the page has it"


def test_a_cmyk_jpeg_background_is_converted_through_its_profile_and_carries_none() -> None:
    out = io.BytesIO()
    Image.new("CMYK", (30, 30), (255, 0, 0, 0)).save(out, "JPEG", quality=100, icc_profile=_cmyk_profile())
    png = _image(_background("print-shop.jpg", out.getvalue()).content)
    r, g, b = png.convert("RGB").getpixel((15, 15))
    assert max(r, g, b) - min(r, g, b) < 12, ("the profile prints full cyan as grey; a naive conversion gives cyan", (r, g, b))
    assert png.mode == "RGB"
    profile = png.info.get("icc_profile")
    assert profile is None or profile[16:20] == b"RGB ", "the PNG must not carry the CMYK profile"


def test_a_background_that_is_not_a_pdf_png_or_jpeg_answers_400_with_the_reason() -> None:
    no_pages = PdfWriter()
    out = io.BytesIO()
    no_pages.write(out)
    cases = {
        "a text file": ("notes.txt", b"hello"),
        "a GIF": ("anim.gif", b"GIF89a" + bytes(8)),
        "a truncated PNG": ("cut.png", _png()[:40]),
        "a truncated JPEG": ("cut.jpg", _jpeg()[:40]),
        "a damaged PDF": ("bad.pdf", b"%PDF-1.4 not really"),
        "a PDF with no pages": ("empty.pdf", out.getvalue()),
    }
    for case, (name, data) in cases.items():
        res = _background(name, data)
        assert res.status_code == 400, (case, res.status_code)
        detail = res.json()["detail"]
        assert isinstance(detail, str) and name in detail, (case, "the reason names the file", detail)
    assert "no pages" in _background("empty.pdf", out.getvalue()).json()["detail"]
    assert "PDF, PNG or JPEG" in _background("notes.txt", b"hello").json()["detail"]
    assert client.post("/api/background", files={"template": ("t.html", b"<p>")}).status_code == 400
    assert client.post("/api/background", files={}).status_code == 400


def test_export_with_a_vdr_address_under_the_local_one_writes_it_once_in_the_template_and_the_credential() -> None:
    vdr = "http://vdr.localhost:8088"
    template = LOCAL_TEMPLATE.replace("</body>", '<img src="http://vdr.localhost/templates/old/v0/background.png"/></body>')
    files = _set(template=("record.html", template.encode()), credential=("record.json", _json(LOCAL_CREDENTIAL)),
                 background=("background.png", _png()))
    res = _export(files, vdr_address=vdr)
    assert res.status_code == 200, res.text
    zipped = _zip_files(res.content)
    template = zipped[f"{PACKAGE_DIR}/template.html"].decode()
    credential = zipped["certify/credentials/example-record.json"].decode()
    assert f"{vdr}:8088" not in template + credential, "the VDR address written twice"
    assert f'src="{vdr}/templates/old/v0/background.png"' in template
    address = f"{vdr}/templates/example-record/v1/background.png"
    assert json.loads(credential)["display"][0]["background_image"]["uri"] == address
    assert f"{vdr}/logo.png" in template and f"{vdr}/fonts/f.css" in template
    assert json.loads(credential)["display"][0]["logo"] == {"url": f"{vdr}/logo.png"}


def test_the_quick_view_is_the_renderers_html_as_it_is() -> None:
    """The Background reaches it as $backgroundImage's data URI; an address in the template is never swapped for it."""
    png = _png()
    template = TEMPLATE.replace("</body>", '<img src="http://vdr.localhost/templates/background.png"/>'
                                '<img src="http://vdr.localhost/templates/a/b/background.png"/>'
                                '<img src="http://vdr.localhost/templates/a/other.png"/></body>')

    class Renderer:  # stands in for the renderer: it hands back the template as the HTML
        status_code = 200

        def __init__(self, request: dict) -> None:
            self.content = request["template"].encode()

    real_post, real_url = vc_lab.httpx.post, vc_lab.RENDERER_URL
    vc_lab.httpx.post = lambda url, json, timeout: Renderer(json)
    vc_lab.RENDERER_URL = "http://renderer.test"
    try:
        res = _post("/preview", _set(template=("record.html", template.encode()), background=("background.png", png)))
    finally:
        vc_lab.httpx.post, vc_lab.RENDERER_URL = real_post, real_url
    assert res.status_code == 200, res.text
    assert res.text == template, "the renderer's HTML, unchanged"


def test_a_pdf_background_with_bytes_before_the_header_is_still_a_pdf() -> None:
    for case, lead in (("a newline", b"\n"), ("a UTF-8 BOM", b"\xef\xbb\xbf"), ("junk", b"junk\r\n" * 3)):
        res = _background("paper.pdf", lead + _pdf(200, 300))
        assert res.status_code == 200, (case, res.text)
        assert _image(res.content).size == (417, 625), case
    edge = _background("paper.pdf", bytes(1024) + _pdf(200, 300))
    assert edge.status_code == 200, ("pdfium opens a header that starts at byte 1024", edge.text)
    far = _background("paper.pdf", bytes(1025) + _pdf(200, 300))
    assert far.status_code == 400, "pdfium looks for the header no further than byte 1024"


def test_a_png_or_jpeg_whose_metadata_mentions_a_pdf_is_still_an_image() -> None:
    from PIL import PngImagePlugin
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "exported from scan.pdf (%PDF-1.7)")
    out = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 30, 30)).save(out, "PNG", pnginfo=info)
    png = _background("paper.png", out.getvalue())
    assert png.status_code == 200 and png.content == out.getvalue(), png.text
    out = io.BytesIO()
    Image.new("RGB", (40, 60), (200, 30, 30)).save(out, "JPEG", comment=b"made from %PDF-1.4 scan")
    jpeg = _background("paper.jpg", out.getvalue())
    assert jpeg.status_code == 200 and _image(jpeg.content).size == (40, 60), jpeg.text


def test_export_and_read_back_with_a_vdr_address_that_starts_a_local_one() -> None:
    vdr = "http://vdr"  # the VDR's Compose service name, the start of http://vdr.localhost
    template = TEMPLATE.replace("</body>", '<img src="http://vdr.localhost/templates/x/background.png"/>'
                                '<img src="http://vdr.localhost/assets/logo.png"/><img src="http://cdn.localhost/l.png"/></body>')
    credential = {**CREDENTIAL, "display": [{**CREDENTIAL["display"][0], "logo": {"url": "http://vdr.localhost/assets/logo.png"}}]}
    files = _set(template=("record.html", template.encode()), credential=("record.json", _json(credential)),
                 background=("background.png", _png()))
    res = _export(files, vdr_address=vdr)
    assert res.status_code == 200, res.text
    zipped = _zip_files(res.content)
    exported = zipped[f"{PACKAGE_DIR}/template.html"].decode()
    exported_credential = zipped["certify/credentials/example-record.json"].decode()
    assert "localhost" not in exported + exported_credential, "every local address is the VDR address"
    for address in ("http://vdr/templates/x/background.png", "http://vdr/assets/logo.png", "http://vdr/l.png"):
        assert f'src="{address}"' in exported, address
    back = _read_set(res.content)
    read_template, read_credential = back["template"][1].decode(), back["credential"][1].decode()
    assert "localhost.localhost" not in read_template + read_credential
    assert 'src="http://vdr.localhost/assets/logo.png"' in read_template
    assert json.loads(read_credential)["display"][0]["logo"] == {"url": "http://vdr.localhost/assets/logo.png"}


# ---------------------------------------------------------------------------------------------------------------
# Tests through the renderer


def test_grid_from_credential_subject_in_the_pdf_and_the_quick_view() -> bool:
    if _skip_without_renderer("test_grid_from_credential_subject_in_the_pdf_and_the_quick_view"):
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
    if _skip_without_renderer("test_two_visitors_each_preview_their_own_set"):
        return False
    mine = _set(sample=("mine.json", _json({**SAMPLE, "name": "Ada Mine"})))
    theirs = _set(sample=("theirs.json", _json({**SAMPLE, "name": "Bo Theirs"})))
    for _ in range(2):  # interleaved, twice, so the second call of each would show a remembered set
        for files, name, other in ((mine, "Ada Mine", "Bo Theirs"), (theirs, "Bo Theirs", "Ada Mine")):
            quick = html.unescape(_post("/preview", files).text)
            printed = _pages(files)[0].extract_text()
            for shown in (quick, printed):
                assert name in shown and other not in shown, (name, other)
    return True


def test_velocity_and_mapping_errors_answer_422_with_the_engines_message() -> bool:
    if _skip_without_renderer("test_velocity_and_mapping_errors_answer_422_with_the_engines_message"):
        return False
    bad = _set(template=("bad.html", b"<p>ok</p>\n<p>#set($x = )</p>"))
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, bad)
        assert res.status_code == 422, (path, res.status_code, res.text)
        assert "line 2" in res.json()["detail"], (path, "Velocity names the line", res.json())

    null = _set(sample=("null.json", _json({**SAMPLE, "thesisTitle": None})))
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, null)
        assert res.status_code == 422, (path, res.status_code, res.text)
        assert "null for thesisTitle" in res.json()["detail"], (path, "the plugin's refusal", res.json())
    return True


def test_an_unbalanced_template_answers_422_with_velocitys_message() -> bool:
    if _skip_without_renderer("test_an_unbalanced_template_answers_422_with_velocitys_message"):
        return False
    cases = {  # VC Lab keeps no block check of its own: the renderer's Velocity answers, with its line and column
        "an #if without an #end": b"<p>ok</p>\n#if(true)a",
        "a stray #end": b"<p>ok</p>\n<p>#end</p>",
    }
    for case, source in cases.items():
        for path in ("/preview", "/preview.pdf"):
            res = _post(path, _set(template=("t.html", source)))
            assert res.status_code == 422, (case, path, res.status_code, res.text)
            detail = res.json()["detail"]
            assert "line 2" in detail and "column" in detail, (case, path, "Velocity's own message", detail)
    return True


def test_a_vc_template_nested_too_deep_answers_422() -> bool:
    if _skip_without_renderer("test_a_vc_template_nested_too_deep_answers_422"):
        return False
    deep = "#if(true)" * 20000 + "x" + "#end" * 20000
    mapping = {**CREDENTIAL["vc_template"], "credentialSubject": {
        **CREDENTIAL["vc_template"]["credentialSubject"], "thesisTitle": deep}}
    files = _set(credential=("deep.json", _json({**CREDENTIAL, "vc_template": mapping})))
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, files)
        assert res.status_code == 422, (path, res.status_code, res.text[:200])
        assert "too deep" in res.json()["detail"], (path, res.json())
    return True


def test_a_record_certify_refuses_answers_422_with_the_plugins_reason() -> bool:
    if _skip_without_renderer("test_a_record_certify_refuses_answers_422_with_the_plugins_reason"):
        return False
    cases = {
        "a reserved key": (_json({**SAMPLE, "id": "st0001"}),
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
    if _skip_without_renderer("test_a_template_named_in_any_script_previews"):
        return False
    res = _post("/preview.pdf", _set(template=("ใบรับรอง.html", TEMPLATE.encode())))
    assert res.status_code == 200, res.text
    disposition = res.headers["content-disposition"]
    assert "filename*=UTF-8''" + quote("ใบรับรอง.pdf") in disposition, disposition
    assert "Ada Example" in PdfReader(io.BytesIO(res.content)).pages[0].extract_text()
    return True


def test_a_sample_with_a_credential_subject_answers_422() -> bool:
    """The plugin refuses a record wrapped in a credential, so the preview does too, saying what to upload."""
    if _skip_without_renderer("test_a_sample_with_a_credential_subject_answers_422"):
        return False
    credential = {"@context": ["https://www.w3.org/ns/credentials/v2"], "type": ["VerifiableCredential"],
                  "issuer": "did:example:adapter", "credentialSubject": SAMPLE}
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, _set(sample=("credential.json", _json(credential))))
        assert res.status_code == 422, (path, res.status_code, res.text[:200])
        detail = res.json()["detail"]
        assert "adapter_error" in detail and "the sample has a credentialSubject" in detail, (path, detail)
        assert "upload the Adapter's answer" in detail, (path, detail)
    return True


def _with_body(body: str) -> bytes:
    """TEMPLATE with `body` at the top of page 1."""
    return TEMPLATE.replace('<div class="page">', f'<div class="page">\n{body}', 1).encode()


def test_a_template_reaching_for_an_address_answers_422_naming_it() -> bool:
    if _skip_without_renderer("test_a_template_reaching_for_an_address_answers_422_naming_it"):
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
        for path in ("/preview", "/preview.pdf"):
            res = _post(path, _set(template=("reach.html", _with_body(body))))
            assert res.status_code == 422, (case, path, res.status_code, res.text[:200])
            assert address in res.json()["detail"], (case, path, res.json())
    return True


def test_a_template_that_draws_logo_url_previews_without_a_logo() -> bool:
    if _skip_without_renderer("test_a_template_that_draws_logo_url_previews_without_a_logo"):
        return False
    # As the committed demo template draws it. $logoUrl is "", which Velocity 1.7 counts as true.
    logo = '#if ($logoUrl)\n<img src="$logoUrl" alt="the logo" style="height:56px; width: auto;" />\n#end'
    files = _set(template=("logo.html", _with_body(logo)))
    page = _post("/preview", files)
    assert page.status_code == 200, page.text
    assert '<img src=""' in page.text, "the template draws an empty logo"
    pages = _pages(files)
    assert "Ada Example" in pages[0].extract_text()
    return True


def test_reflection_fails_in_the_print_template_and_the_vc_template() -> bool:
    if _skip_without_renderer("test_reflection_fails_in_the_print_template_and_the_vc_template"):
        return False
    reach = ".getClass().forName('java.lang.Runtime')"
    mapping = {**CREDENTIAL["vc_template"], "credentialSubject": {
        **CREDENTIAL["vc_template"]["credentialSubject"], "thesisTitle": "MAPPED $name" + reach}}
    files = _set(template=("reflect.html", _with_body(f"<p>PRINTED $titleName{reach}</p>")),
                 credential=("reflect.json", _json({**CREDENTIAL, "vc_template": mapping})))
    page = _post("/preview", files)
    assert page.status_code == 200, page.text
    printed = _pages(files)[0].extract_text()
    for shown, where in ((html.unescape(page.text), "quick view"), (printed, "PDF")):
        for engine in ("PRINTED", "MAPPED"):  # the print template's, the vc_template's
            assert engine in shown, (where, engine, "evaluated")
            assert f"{engine} class java.lang.Runtime" not in shown, (where, engine, "reached java.lang.Runtime")
    return True




# Over the whole page, whatever the @page margin (20 mm here); a zero-height box, so it takes no room in the flow.
_PAPER = "width: 210mm; height: 297mm; margin: -20mm 0 0 -20mm"
DRAWS_BACKGROUND = _with_body(f'<div style="height: 0"><img src="$!backgroundImage" style="{_PAPER}"/></div>')
# The address the Wallet fetches the Background from once an organisation has put it on its VDR.
VDR_BACKGROUND = "http://vdr.localhost/templates/example-record/v1/background.png"


def _images(page) -> list[Image.Image]:
    return [i.image for i in page.images]


def test_a_template_that_draws_the_background_shows_it_in_the_pdf_and_the_quick_view() -> bool:
    if _skip_without_renderer("test_a_template_that_draws_the_background_shows_it_in_the_pdf_and_the_quick_view"):
        return False
    png = _png(40, 60, (200, 30, 30))
    files = _set(template=("record.html", DRAWS_BACKGROUND), background=("background.png", png))
    pages = _pages(files)
    assert [i.size for i in _images(pages[0])] == [(40, 60)], "page 1 carries the Background picture"
    assert _images(pages[0])[0].convert("RGB").getpixel((5, 5)) == (200, 30, 30)
    assert "Ada Example" in pages[0].extract_text(), "with the record over it"
    assert len(_images(pages[1])) == 1, "page 2 carries only the QR code"

    quick = _post("/preview", files).text
    assert "data:image/png;base64," + base64.b64encode(png).decode() in quick, "the quick view draws it too"
    return True


def test_a_pdf_background_prints_upright_under_the_record() -> bool:
    """From the upload to the printed page: the paper's bottom-left corner is the page's bottom-left corner."""
    if _skip_without_renderer("test_a_pdf_background_prints_upright_under_the_record"):
        return False
    png = _background("paper.pdf", _pdf(595.28, 841.89)).content  # a red square at the paper's bottom-left
    res = _post("/preview.pdf", _set(template=("record.html", DRAWS_BACKGROUND), background=("background.png", png)))
    assert res.status_code == 200, res.text
    page = pypdfium2.PdfDocument(res.content)[0].render(scale=0.5).to_pil().convert("RGB")
    assert page.getpixel((5, page.height - 5)) == (255, 0, 0), "the red square is at the page's bottom-left"
    assert page.getpixel((page.width - 5, 5)) == (255, 255, 255), "the rest of the paper is white"
    return True


def test_after_remove_background_the_template_previews_on_plain_paper() -> bool:
    if _skip_without_renderer("test_after_remove_background_the_template_previews_on_plain_paper"):
        return False
    plain = _set(template=("record.html", DRAWS_BACKGROUND))  # the dashboard sends no background slot
    page = _pages(plain)[0]
    assert _images(page) == [], "nothing under the record"
    assert "Ada Example" in page.extract_text()
    assert _post("/preview", plain).text.count("data:image/png;base64,") == 1, "the QR code only, in the quick view too"
    return True


def test_the_guides_credential_file_with_a_background_address_previews_on_plain_paper_without_one() -> bool:
    """docs/guides/print-from-the-wallet.md sets display[0].background_image.uri and draws $backgroundImage when it
    is set. Without a Background in the set, $backgroundImage is empty, not that address (which the renderer refuses)."""
    name = "test_the_guides_credential_file_with_a_background_address_previews_on_plain_paper_without_one"
    if _skip_without_renderer(name):
        return False
    display = [{**CREDENTIAL["display"][0], "background_image": {"uri": VDR_BACKGROUND}}]
    credential = ("record.json", _json({**CREDENTIAL, "display": display}))
    guide = _with_body('#if($backgroundImage && $backgroundImage != "")<img src="$backgroundImage"/>#end')
    plain = _set(template=("record.html", guide), credential=credential)
    for path in ("/preview", "/preview.pdf"):
        res = _post(path, plain)
        assert res.status_code == 200, (path, res.text[:200])
    assert _images(_pages(plain)[0]) == [], "plain paper"
    with_paper = _set(template=("record.html", guide), credential=credential, background=("background.png", _png(40, 60)))
    assert [i.size for i in _images(_pages(with_paper)[0])] == [(40, 60)], "the uploaded Background, not the address"
    return True


def test_a_template_that_loads_the_background_by_its_vdr_address_answers_422_naming_it() -> bool:
    """The renderer serves no address, the Background's included: a template draws it with $backgroundImage. Every
    form of the address is refused alike, with a Background loaded or not."""
    if _skip_without_renderer("test_a_template_that_loads_the_background_by_its_vdr_address_answers_422_naming_it"):
        return False
    addresses = [VDR_BACKGROUND, "http://vdr.localhost/templates/background.png",
                 "http://vdr.localhost/templates/a(1)/background.png", "http://vdr.localhost/templates/my folder/background.png",
                 "http://vdr.localhost/templates/a/background.pngs/logo.png", "http://vdr.localhost/templates/a/background.png.bak",
                 "http://vdr.localhost/templates/a/background.png?v=2"]
    for address in addresses:
        for background in ({}, {"background": ("background.png", _png(40, 60))}):
            files = _set(template=("record.html", _with_body(f'<img src="{address}"/>')), **background)
            for path in ("/preview", "/preview.pdf"):
                res = _post(path, files)
                assert res.status_code == 422, (address, path, bool(background), res.status_code)
                assert "$backgroundImage" in res.json()["detail"], (address, path, res.json())
                assert address.split("/templates/")[1].split(" ")[0] in res.json()["detail"], (address, path, res.json())
    return True


def test_a_loaded_package_previews_the_same_as_the_original() -> bool:
    if _skip_without_renderer("test_a_loaded_package_previews_the_same_as_the_original"):
        return False
    original = _set(template=("record.html", DRAWS_BACKGROUND), background=("background.png", _png(40, 60)))
    loaded = _read_set(_export(original).content)
    for path in ("/preview", "/preview.pdf"):
        assert _post(path, loaded).status_code == 200, path
    assert _post("/preview", loaded).text == _post("/preview", original).text, "the quick views match"
    mine, theirs = _pages(original), _pages(loaded)
    assert len(mine) == len(theirs) == 2
    for a, b in zip(mine, theirs):
        assert a.extract_text() == b.extract_text()
    assert [i.size for i in _images(theirs[0])] == [i.size for i in _images(mine[0])] == [(40, 60)], \
        "the Background, from $backgroundImage again"
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
        test_download_and_the_bundle_are_gone,
        test_two_visitors_each_get_their_own_package,
        test_export_package_lays_the_files_out_as_the_vdr_and_certify_take_them,
        test_the_manifest_names_the_config_the_version_the_vdr_and_each_component_with_its_role,
        test_export_without_a_background_writes_none_and_leaves_the_credential_files_address,
        test_the_backgrounds_address_goes_into_the_credential_file_and_a_templates_addresses_stay_as_they_are,
        test_the_config_id_must_be_the_credential_files_key,
        test_a_sample_named_manifest_json_still_reads_back,
        test_a_background_image_that_is_not_an_object_is_replaced_by_the_address,
        test_export_asks_for_a_config_id_a_version_and_an_address,
        test_a_package_reads_back_as_the_set_with_the_vdr_address_turned_back_to_local,
        test_a_package_without_a_background_reads_back_without_one,
        test_read_package_accepts_only_the_exported_layout,
        test_rejects_wrong_files,
        test_a_request_over_20_mb_is_refused,
        test_one_visitors_slow_render_does_not_block_another,
        test_large_upload_stays_in_memory,
        test_a_png_background_is_kept_as_is,
        test_a_jpeg_background_becomes_a_png_of_its_own_size,
        test_a_pdf_background_is_drawn_at_its_page_size_and_150_dpi,
        test_a_pdf_background_keeps_its_rotation_and_crop_box,
        test_a_jpeg_background_is_turned_upright_by_its_exif_orientation,
        test_a_pdf_background_draws_its_signature_field,
        test_a_cmyk_jpeg_background_is_converted_through_its_profile_and_carries_none,
        test_a_background_that_is_not_a_pdf_png_or_jpeg_answers_400_with_the_reason,
        test_export_with_a_vdr_address_under_the_local_one_writes_it_once_in_the_template_and_the_credential,
        test_the_quick_view_is_the_renderers_html_as_it_is,
        test_a_pdf_background_with_bytes_before_the_header_is_still_a_pdf,
        test_a_png_or_jpeg_whose_metadata_mentions_a_pdf_is_still_an_image,
        test_export_and_read_back_with_a_vdr_address_that_starts_a_local_one,
        test_grid_from_credential_subject_in_the_pdf_and_the_quick_view,
        test_two_visitors_each_preview_their_own_set,
        test_velocity_and_mapping_errors_answer_422_with_the_engines_message,
        test_an_unbalanced_template_answers_422_with_velocitys_message,
        test_a_vc_template_nested_too_deep_answers_422,
        test_a_record_certify_refuses_answers_422_with_the_plugins_reason,
        test_a_template_named_in_any_script_previews,
        test_a_sample_with_a_credential_subject_answers_422,
        test_a_template_reaching_for_an_address_answers_422_naming_it,
        test_a_template_that_draws_logo_url_previews_without_a_logo,
        test_reflection_fails_in_the_print_template_and_the_vc_template,
        test_a_template_that_draws_the_background_shows_it_in_the_pdf_and_the_quick_view,
        test_a_pdf_background_prints_upright_under_the_record,
        test_after_remove_background_the_template_previews_on_plain_paper,
        test_the_guides_credential_file_with_a_background_address_previews_on_plain_paper_without_one,
        test_a_template_that_loads_the_background_by_its_vdr_address_answers_422_naming_it,
        test_a_loaded_package_previews_the_same_as_the_original,
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
