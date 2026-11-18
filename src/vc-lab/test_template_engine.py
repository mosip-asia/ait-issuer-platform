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
TRANSCRIPT_TMPL = REPO_ROOT / "deploy" / "ait" / "vdr" / "templates" / "AITUniversity-ait-transcript-template.html"
BASE_TMPL = REPO_ROOT / "deploy" / "base" / "vdr" / "templates" / "credential-template.html"


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
    assert "data:image/png;base64," in content
    # Mimoto's variables only: no $terms, so the course body is courseList, and no background.
    assert "Advanced Algorithms — A" in content
    assert 'class="bg"' not in content
    assert "#macro" not in content, "Macro definitions must be stripped"
    assert "#claimValue" not in content, "#claimValue calls must be replaced"
    assert "#end" not in content, "No dangling #end tags should remain"
    assert "#if" not in content, "No dangling #if tags should remain"


def test_render_transcript_semester_table() -> None:
    claims = engine.load_student_claims("st120001")
    ctx = engine.lab_context(claims, background_url="/bg.jpg")
    content = engine.render_velocity_template(TRANSCRIPT_TMPL.read_text(encoding="utf-8"), ctx, claims)

    assert "August Semester 2024" in content and "January Semester 2025" in content
    assert "<td style=\"padding-left:6.8pt;\">CS601</td>" in content
    assert ">3.78</td>" in content, "Each term closes with its credits, GPA and cumulative GPA"
    assert "Advanced Algorithms — A" not in content, "The courseList fallback must not render beside the table"
    assert '<img class="bg" src="/bg.jpg"' in content
    assert "$t." not in content and "$c." not in content and "#foreach" not in content


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


def test_foreach_over_nested_lists() -> None:
    template_str = (
        "#foreach($t in $terms)[$t.term:"
        "#foreach($c in $t.courses)<$c.no #if($c.grade)$c.grade#else-#end>#end]#end"
    )
    ctx = {"terms": [
        {"term": "Aug 2016", "courses": [{"no": "CE70.11", "grade": "B+"}, {"no": "CE70.12", "grade": ""}]},
        {"term": "Jan 2017", "courses": [{"no": "CE70.22", "grade": "A & B"}]},
    ]}
    rendered = engine.render_velocity_template(template_str, ctx, {})
    assert rendered == "[Aug 2016:<CE70.11 B+><CE70.12 ->][Jan 2017:<CE70.22 A &amp; B>]", rendered


def test_foreach_over_missing_list_falls_back() -> None:
    # Mimoto never passes $terms; the #else branch must win and no loop text may leak.
    template_str = "#if($terms)#foreach($t in $terms)$t.term#end#else#claimValue('courseList')#end"
    rendered = engine.render_velocity_template(template_str, {}, {"courseList": "A — B"})
    assert rendered == "A — B", rendered


def test_longer_variable_names_win() -> None:
    rendered = engine.render_velocity_template("$title|$titleName", {"title": "x", "titleName": "y"}, {})
    assert rendered == "x|y", rendered


def main() -> None:
    test_foreach_over_nested_lists()
    print("PASS test_foreach_over_nested_lists")
    test_foreach_over_missing_list_falls_back()
    print("PASS test_foreach_over_missing_list_falls_back")
    test_longer_variable_names_win()
    print("PASS test_longer_variable_names_win")
    test_generate_mock_qr_png_base64()
    print("PASS test_generate_mock_qr_png_base64")
    test_load_student_claims()
    print("PASS test_load_student_claims")
    test_render_transcript_template()
    print("PASS test_render_transcript_template")
    test_render_transcript_semester_table()
    print("PASS test_render_transcript_semester_table")
    test_render_base_credential_template()
    print("PASS test_render_base_credential_template")
    test_custom_claims_inline()
    print("PASS test_custom_claims_inline")
    print("9 tests passed")


if __name__ == "__main__":
    main()
