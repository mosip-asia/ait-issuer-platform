"""The print check's scripts must fail early and name the key, and its Python must import with or without httpx.

Host only, no stack: src/tools/print_check.py needs httpx and pypdf at import, so where either is missing the test
imports it with a stand-in and takes the stand-in out of sys.modules again.
Run: python3 tests/test_print_check.py
"""

from __future__ import annotations

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


def test_the_made_up_students_grid_counts_are_written_out_apart_from_the_record() -> None:
    # A record that held other terms must not pass for st120001 even when the page matches the record.
    assert "holds 2 term headings and 3 course rows, not 2 and 6" in _grid_failure(GRID, COURSES, "st120001")


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
