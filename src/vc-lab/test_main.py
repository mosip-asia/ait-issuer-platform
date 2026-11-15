"""Unit tests for VC Lab FastAPI studio and developer endpoints.

Run:
    python3 src/vc-lab/test_main.py
"""

from __future__ import annotations

import sys
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


def main() -> None:
    test_health_endpoint()
    print("PASS test_health_endpoint")
    test_api_endpoints()
    print("PASS test_api_endpoints")
    test_preview_endpoint()
    print("PASS test_preview_endpoint")
    test_dashboard_endpoint()
    print("PASS test_dashboard_endpoint")
    print("4 tests passed")


if __name__ == "__main__":
    main()
