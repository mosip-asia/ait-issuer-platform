"""The print check's scripts must fail early and name the key, and its Python must import with or without httpx.

Host only, no stack: src/tools/print_check.py needs httpx and pypdf at import, so where either is missing the test
imports it with a stand-in and takes the stand-in out of sys.modules again.
Run: python3 tests/test_print_check.py
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "tools"))


def _import_print_check():
    """print_check, with a stand-in only for a dependency that isn't installed; no stand-in stays in sys.modules."""
    stubs = []
    for name, attr in (("httpx", None), ("pypdf", "PdfReader")):
        try:
            __import__(name)
        except ImportError:
            stub = types.ModuleType(name)
            if attr:
                setattr(stub, attr, object)
            sys.modules[name] = stub
            stubs.append(name)
    try:
        import print_check
    finally:
        for name in stubs:
            sys.modules.pop(name, None)
    return print_check


_pc = _import_print_check()


def test_the_step_a_mimoto_error_code_names() -> None:
    assert _pc.failed_step("invalid_request", "") == "token exchange"
    assert _pc.failed_step("resource_not_found", "") == "issuance"
    assert _pc.failed_step("signature_verification_failed", "") == "signature check"
    assert _pc.failed_step("RESIDENT-APP-028", "java.lang.NullPointerException: template is null") == "template fetch"
    assert _pc.failed_step("RESIDENT-APP-028", "Velocity: Encountered at line 3") == "PDF content"
    assert _pc.failed_step("anything-else", "") == "issuance"


def test_a_template_the_vdr_does_not_serve_is_a_template_fetch_failure_not_a_traceback() -> None:
    """The credential's template is absent from the VDR's templates folder, so the VDR answers 404 for it."""
    class Reply:
        status_code = 404

    original = (_pc.context, _pc._get)
    _pc.context = lambda installation, student: {"template": "missing.html", "background_uri": ""}
    _pc._get = lambda url, **kw: Reply()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                _pc.run(Path(tmp), Path(tmp), Path(tmp), Path(tmp), None, "templates", "x")
            except _pc.StepFailed as e:
                assert e.step == "template fetch", e.step
            else:
                raise AssertionError("a template the VDR doesn't serve must be a StepFailed")
    finally:
        _pc.context, _pc._get = original


COURSES = [
    {"term": "T1", "credits": "6", "gpa": "3.5", "cumGpa": "3.5",
     "courses": [{"no": "A1", "title": "Algebra", "lab": "0", "lec": "45", "credits": "3", "grade": "A"},
                 {"no": "A2", "title": "Biology", "lab": "45", "lec": "30", "credits": "3", "grade": ""}]},
    {"term": "T2", "credits": "3", "gpa": "4.0", "cumGpa": "3.7",
     "courses": [{"no": "B1", "title": "Chemistry", "lab": "0", "lec": "45", "credits": "3", "grade": "B+"}]},
]
# What the PDF's page text holds for COURSES, written out: a row is its kind and fields between bars, then a semicolon,
# so a missing grade shows as "3 | ;" and a shifted field can't pass.
GRID = ("COURSE-GRID-START TERM | T1 | 6 | 3.5 | 3.5 ; COURSE | A1 | Algebra | 0 | 45 | 3 | A ; "
        "COURSE | A2 | Biology | 45 | 30 | 3 | ; TERM | T2 | 3 | 4.0 | 3.7 ; "
        "COURSE | B1 | Chemistry | 0 | 45 | 3 | B+ ; COURSE-GRID-END")


def _grid_failure(text: str, courses=COURSES, student: str = "") -> str:
    try:
        _pc.check_grid(text, courses, student)
    except _pc.StepFailed as e:
        assert e.step == "PDF content", e.step
        return str(e)
    raise AssertionError("the grid should have failed")


def test_the_grid_is_every_term_heading_and_course_row_in_order_with_an_empty_grade_cell() -> None:
    assert _pc.check_grid("Name " + GRID + " footer", COURSES, "") == "2 term headings and 3 course rows, in order"


def test_the_grid_fails_on_a_shifted_row_a_missing_row_or_missing_markers() -> None:
    shifted = GRID.replace("3 | ; TERM", "; TERM")  # the empty grade cell is gone
    assert "isn't the 2 term headings and 3 course rows" in _grid_failure(shifted)
    assert "isn't the" in _grid_failure(GRID.replace("COURSE | B1 | Chemistry | 0 | 45 | 3 | B+ ; ", ""))
    out_of_order = GRID.replace("COURSE | A1 | Algebra | 0 | 45 | 3 | A ; COURSE | A2 | Biology | 45 | 30 | 3 | ;",
                                "COURSE | A2 | Biology | 45 | 30 | 3 | ; COURSE | A1 | Algebra | 0 | 45 | 3 | A ;")
    assert out_of_order != GRID and "isn't the" in _grid_failure(out_of_order)
    assert "markers aren't in the page text" in _grid_failure("no grid here")


ST120001 = [
    {"term": "August Semester 2024", "credits": "9", "gpa": "3.67", "cumGpa": "3.67", "courses": [
        {"no": "CS601", "title": "Advanced Algorithms", "lab": "0", "lec": "45", "credits": "3", "grade": "A"},
        {"no": "CS602", "title": "Machine Learning", "lab": "45", "lec": "30", "credits": "3", "grade": "A-"},
        {"no": "CS603", "title": "Distributed Systems", "lab": "45", "lec": "30", "credits": "3", "grade": "B+"}]},
    {"term": "January Semester 2025", "credits": "9", "gpa": "3.89", "cumGpa": "3.78", "courses": [
        {"no": "CS604", "title": "Computer Vision", "lab": "45", "lec": "30", "credits": "3", "grade": "A"},
        {"no": "CS605", "title": "Cryptography and Network Security", "lab": "0", "lec": "45", "credits": "3",
         "grade": "A"},
        {"no": "CS606", "title": "Cloud Computing", "lab": "45", "lec": "30", "credits": "3", "grade": "A-"}]},
]
GRID_ST120001 = (
    "COURSE-GRID-START TERM | August Semester 2024 | 9 | 3.67 | 3.67 ; "
    "COURSE | CS601 | Advanced Algorithms | 0 | 45 | 3 | A ; COURSE | CS602 | Machine Learning | 45 | 30 | 3 | A- ; "
    "COURSE | CS603 | Distributed Systems | 45 | 30 | 3 | B+ ; "
    "TERM | January Semester 2025 | 9 | 3.89 | 3.78 ; COURSE | CS604 | Computer Vision | 45 | 30 | 3 | A ; "
    "COURSE | CS605 | Cryptography and Network Security | 0 | 45 | 3 | A ; "
    "COURSE | CS606 | Cloud Computing | 45 | 30 | 3 | A- ; COURSE-GRID-END")


def test_the_made_up_students_grid_is_pinned_to_the_committed_data_not_to_the_record() -> None:
    assert _pc.check_grid(GRID_ST120001, ST120001, "st120001") == "2 term headings and 6 course rows, in order"
    # A record and a page that agree with each other but not with the committed data must fail: a wrong title on
    # the first course, a wrong grade on the last.
    wrong_title = json.loads(json.dumps(ST120001))
    wrong_title[0]["courses"][0]["title"] = "Advanced Algorithm"
    assert "lacks" in _grid_failure(GRID_ST120001.replace("Advanced Algorithms", "Advanced Algorithm"), wrong_title,
                                    "st120001")
    wrong_grade = json.loads(json.dumps(ST120001))
    wrong_grade[1]["courses"][2]["grade"] = "A"
    assert "lacks" in _grid_failure(GRID_ST120001.replace("Cloud Computing | 45 | 30 | 3 | A-",
                                                           "Cloud Computing | 45 | 30 | 3 | A"), wrong_grade, "st120001")
    shorter = [ST120001[0], {**ST120001[1], "courses": ST120001[1]["courses"][:2]}]
    page = GRID_ST120001.replace("COURSE | CS606 | Cloud Computing | 45 | 30 | 3 | A- ; ", "")
    assert "not 2 and 6" in _grid_failure(page, shorter, "st120001")


def _pdf_with_rows(*rows: tuple[int, str]) -> bytes:
    """A one-page A4 PDF with each (y, text) drawn at x=30, for the grid's position check."""
    stream = "BT /F1 9 Tf " + " ".join(f"1 0 0 1 30 {y} Tm ({t}) Tj" for y, t in rows) + " ET"
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
               "/Resources << /Font << /F1 5 0 R >> >> >>",
               f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
               "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    body, offsets = "%PDF-1.4\n", []
    for n, obj in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{n} 0 obj\n{obj}\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    return (body + f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF").encode()


def test_a_grid_row_drawn_below_the_page_edge_is_named() -> None:
    on_page = _pdf_with_rows((700, "Name"), (500, "TERM | T1 | 6 | 3.5 | 3.5 ;"), (20, "COURSE | A1 | Algebra ;"))
    assert _pc.grid_rows_off_page(on_page) == []
    off = _pdf_with_rows((700, "Name"), (20, "COURSE | A1 | Algebra ;"), (-30, "COURSE | A2 | Biology ;"))
    assert _pc.grid_rows_off_page(off) == ["COURSE | A2 | Biology ; (y=-30)"]


def test_the_template_prints_every_grid_field_quietly_so_a_missing_one_is_empty_not_its_own_name() -> None:
    template = (REPO_ROOT / "tests" / "fixtures" / "print-check-template.html").read_text(encoding="utf-8")
    refs = re.findall(r"\$!?\{?(?:term|c)\.\w+", template)
    assert len(refs) == 11, refs  # 4 term fields and 6 course fields, plus the `$term.courses` loop source
    assert all(r.startswith("$!") for r in refs if not r.endswith(".courses")), refs


def test_a_key_missing_from_dot_env_falls_back_instead_of_ending_print_check_sh() -> None:
    """scripts/print-check.sh runs under `set -euo pipefail`: env_value's grep exits 1 for a missing key, which used to
    end the script silently before `${IMAGE_TAG:-latest}` could apply."""
    bash = shutil.which("bash")
    assert bash, "bash is needed"
    script = (REPO_ROOT / "scripts" / "print-check.sh").read_text(encoding="utf-8")
    definition = next(line for line in script.splitlines() if line.startswith("env_value()"))
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / ".env").write_text("INSTALLATION=ait\n", encoding="utf-8")
        run = subprocess.run(
            [bash, "-c", f'set -euo pipefail\n{definition}\nIMAGE_TAG=$(env_value IMAGE_TAG)\necho "${{IMAGE_TAG:-latest}}"'],
            cwd=tmp, capture_output=True, text=True,
        )
    assert (run.returncode, run.stdout.strip()) == (0, "latest"), (run.returncode, run.stdout, run.stderr)


def test_importing_this_test_leaves_the_real_httpx_in_place_or_no_stub_behind() -> None:
    # In a fresh process, so this one's own stand-ins can't count. With a real httpx it must still be the real module;
    # without one, no stand-in may stay in sys.modules. Passes with or without httpx installed.
    code = (f"import sys, importlib.util; sys.path.insert(0, {str(REPO_ROOT / 'tests')!r}); "
            "real = importlib.util.find_spec('httpx') is not None; import test_print_check; "
            "print(hasattr(sys.modules.get('httpx'), 'Client') if real else 'httpx' not in sys.modules)")
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert run.stdout.strip() == "True", (run.stdout, run.stderr)


def test_a_dot_env_without_installation_or_compose_file_fails_early_naming_the_key() -> None:
    """The real scripts/print-check.sh, in a scratch repository root with only a .env: a missing key must be named,
    not surface later as `deploy//smoke.json names no mimotoTemplate`."""
    bash = shutil.which("bash")
    assert bash, "bash is needed"
    for env, key in (("IMAGE_TAG=v1" + chr(10), "INSTALLATION"), ("INSTALLATION=ait" + chr(10), "COMPOSE_FILE")):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "scripts").mkdir()
            shutil.copy(REPO_ROOT / "scripts" / "print-check.sh", Path(tmp) / "scripts")
            (Path(tmp) / ".env").write_text(env, encoding="utf-8")
            run = subprocess.run([bash, "scripts/print-check.sh"], cwd=tmp, capture_output=True, text=True)
        out = run.stdout + run.stderr
        assert run.returncode == 1 and "FAIL setup" in out and f"{key} is not set in .env" in out, (key, run.returncode, out)


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
