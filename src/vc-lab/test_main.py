"""Unit tests for VC Lab FastAPI studio and developer endpoints.

Run:
    python3 src/vc-lab/test_main.py
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

VC_LAB_DIR = Path(__file__).resolve().parent
REPO_ROOT = VC_LAB_DIR.parent.parent

# Ensure vc-lab takes precedence over mock/adapter for 'main'
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))
sys.path.insert(0, str(VC_LAB_DIR))

import main as vc_lab_main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(vc_lab_main.app)


def test_health_endpoint() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UP"
    assert data["service"] == "vc-lab"


def test_api_endpoints() -> None:
    res = client.get("/api/templates")
    assert res.status_code == 200
    templates = res.json()
    assert len(templates) > 0
    names = [t["name"] for t in templates]
    assert "AITUniversity-ait-transcript-template.html" in names

    res_personas = client.get("/api/personas")
    assert res_personas.status_code == 200
    personas = res_personas.json()
    assert len(personas) > 0
    ids = [p["id"] for p in personas]
    assert "st120001" in ids


def test_preview_endpoint() -> None:
    res = client.get("/preview?template=AITUniversity-ait-transcript-template.html&student=st120001")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "Nara Wattanakul" in res.text
    assert "Master of Engineering" in res.text


def test_dashboard_endpoint() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "VC Lab Studio" in res.text
    assert "Interactive Credential Viewer" in res.text


TEMPLATE = "AITUniversity-ait-transcript-template.html"


def _png(width: int, height: int) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 230, 180)).save(out, "PNG")
    return out.getvalue()


def test_background_upload_preview_download_remove() -> None:
    landscape = _png(300, 200)
    res = client.post("/api/background", data={"template": TEMPLATE, "rotation": "90"},
                      files={"file": ("paper.png", landscape, "image/png")})
    assert res.status_code == 200, res.text
    assert client.get(f"/api/background?template={TEMPLATE}").json() == {"template": TEMPLATE, "filename": "paper.png", "rotation": 90}

    from PIL import Image
    shown = Image.open(io.BytesIO(client.get(f"/api/background/preview.jpg?template={TEMPLATE}").content))
    assert shown.height > shown.width, "Turned 90 degrees, a landscape upload fills the portrait A4 page"

    page = client.get(f"/preview?template={TEMPLATE}&student=st120001").text
    assert '<img class="bg" src="/api/background/preview.jpg?template=' in page

    # Changing only the rotation keeps the uploaded file.
    assert client.post("/api/background", data={"template": TEMPLATE, "rotation": "0"}).status_code == 200
    with zipfile.ZipFile(io.BytesIO(client.get(f"/download?template={TEMPLATE}").content)) as z:
        assert z.read("background/paper.png") == landscape, "The download holds the background exactly as uploaded"
        assert json.loads(z.read("background/background.json")) == {"file": "paper.png", "rotation": 0}
        assert "OFFICIAL TRANSCRIPT" in z.read(TEMPLATE).decode("utf-8")

    assert client.delete(f"/api/background?template={TEMPLATE}").status_code == 200
    assert 'class="bg"' not in client.get(f"/preview?template={TEMPLATE}").text
    assert client.get(f"/api/background/preview.jpg?template={TEMPLATE}").status_code == 404


def test_background_rejects_other_files() -> None:
    res = client.post("/api/background", data={"template": TEMPLATE}, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert res.status_code == 400
    assert client.post("/api/background", data={"template": "../secret.html"},
                       files={"file": ("p.png", _png(10, 10), "image/png")}).status_code == 404


def test_export_pdf_puts_background_under_page_one() -> bool:
    try:
        import weasyprint  # noqa: F401
    except Exception as e:  # Pango missing on this host; the container has it
        print(f"SKIP test_export_pdf_puts_background_under_page_one ({type(e).__name__})")
        return False
    from pypdf import PdfReader

    plain = PdfReader(io.BytesIO(client.get(f"/export.pdf?template={TEMPLATE}&student=st120001").content))
    assert len(plain.pages) == 2, "Page 1 is the transcript, page 2 the QR"
    assert "Nara Wattanakul" in plain.pages[0].extract_text()

    client.post("/api/background", data={"template": TEMPLATE, "rotation": "0"},
                files={"file": ("paper.png", _png(200, 300), "image/png")})
    try:
        layered = PdfReader(io.BytesIO(client.get(f"/export.pdf?template={TEMPLATE}&student=st120001").content))
    finally:
        client.delete(f"/api/background?template={TEMPLATE}")
    assert len(layered.pages) == 2
    assert len(layered.pages[0].images) == len(plain.pages[0].images) + 1, "The background goes under page 1"
    assert len(layered.pages[1].images) == len(plain.pages[1].images), "and not under page 2"
    assert "Nara Wattanakul" in layered.pages[0].extract_text(), "The transcript text stays above the background"
    return True


def main() -> None:
    test_health_endpoint()
    print("PASS test_health_endpoint")
    test_api_endpoints()
    print("PASS test_api_endpoints")
    test_preview_endpoint()
    print("PASS test_preview_endpoint")
    test_dashboard_endpoint()
    print("PASS test_dashboard_endpoint")
    test_background_upload_preview_download_remove()
    print("PASS test_background_upload_preview_download_remove")
    test_background_rejects_other_files()
    print("PASS test_background_rejects_other_files")
    if test_export_pdf_puts_background_under_page_one():
        print("PASS test_export_pdf_puts_background_under_page_one")
        print("7 tests passed")
    else:
        print("6 tests passed, 1 skipped")


if __name__ == "__main__":
    main()
