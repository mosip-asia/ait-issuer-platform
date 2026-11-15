"""Unit tests for in-memory Velocity template engine in vc-lab.

Run:
    python3 src/vc-lab/test_template_engine.py
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import template_engine as engine  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TRANSCRIPT_TMPL = REPO_ROOT / "deploy" / "ait" / "AITUniversity-ait-transcript-template.html"
BASE_TMPL = REPO_ROOT / "deploy" / "base" / "credential-template.html"


def test_generate_mock_qr_png_base64() -> None:
    b64 = engine.generate_mock_qr_png_base64()
    assert isinstance(b64, str)
    raw = base64.b64decode(b64)
    assert raw.startswith(b"\x89PNG\r\n\x1a\n"), "Must be a valid PNG header"


def test_load_student_claims() -> None:
    claims = engine.load_student_claims(student_id="st120001", degree_id="meng-cs")
    assert claims["fullName"] == "Nara Wattanakul"
    assert claims["registrationNo"] == "st120001"
    assert claims["degreeAwarded"] == "Master of Engineering"
    assert "courseList" in claims, "Courses must be enriched into courseList"
    assert "Advanced Algorithms" in claims["courseList"]


def test_render_transcript_template() -> None:
    claims = engine.load_student_claims("st120001")
    tmpl_text = TRANSCRIPT_TMPL.read_text(encoding="utf-8")
    ctx = {
        "titleName": "Asian Institute of Technology Credential",
        "logoUrl": engine.DEFAULT_LOGO,
        "qrCodeImage": engine.generate_mock_qr_png_base64(),
        "textColor": "#000000",
        "backgroundColor": "#FFFFFF",
        "credentialValidity": -1,
    }
    content = engine.render_velocity_template(tmpl_text, ctx, claims)

    assert "Nara Wattanakul" in content
    assert "st120001" in content
    assert "Master of Engineering" in content
    assert "AIT_globe.png" in content
    assert "data:image/png;base64," in content
    assert "#macro" not in content, "Macro definitions must be stripped"
    assert "#claimValue" not in content, "#claimValue calls must be replaced"
    assert "#end" not in content, "No dangling #end tags should remain"
    assert "#if" not in content, "No dangling #if tags should remain"


def test_render_base_credential_template() -> None:
    claims = {
        "studentId": "st125001",
        "fullName": "Nara Wattanakul",
        "faculty": "School of Engineering and Technology",
        "academicProgram": "Computer Science",
    }
    context = {
        "titleName": "AIT Student ID Card",
        "textColor": "#005696",
        "backgroundColor": "#F4F8FA",
    }
    tmpl_text = BASE_TMPL.read_text(encoding="utf-8")
    content = engine.render_velocity_template(tmpl_text, context, claims)

    assert "AIT Student ID Card" in content
    assert "Nara Wattanakul" in content
    assert "st125001" in content
    assert "Computer Science" in content
    assert "color: #005696;" in content
    assert "background: #F4F8FA;" in content
    assert "#foreach" not in content, "Foreach loops should be rendered"
    assert "#end" not in content, "No dangling #end tags should remain"


def test_custom_claims_inline() -> None:
    template_str = '<html><body><h1>$titleName</h1><p>#claimValue("award")</p></body></html>'
    ctx = {"titleName": "Hackathon Award"}
    claims = {"award": "First Place - Verifiable Credentials Track"}
    rendered = engine.render_velocity_template(template_str, ctx, claims)
    assert "Hackathon Award" in rendered
    assert "First Place - Verifiable Credentials Track" in rendered


def main() -> None:
    test_generate_mock_qr_png_base64()
    print("PASS test_generate_mock_qr_png_base64")
    test_load_student_claims()
    print("PASS test_load_student_claims")
    test_render_transcript_template()
    print("PASS test_render_transcript_template")
    test_render_base_credential_template()
    print("PASS test_render_base_credential_template")
    test_custom_claims_inline()
    print("PASS test_custom_claims_inline")
    print("5 tests passed")


if __name__ == "__main__":
    main()
