"""The print check's expected course grid must match what the template prints for courseRows.

Host only, no stack: src/tools/print_check.py needs httpx and pypdf at import, and the grid function uses neither, so
where either is missing the test imports it with a stand-in and takes the stand-in out of sys.modules again.
Run: python3 tests/test_print_check.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))  # print_check.py imports ait_courses, as the image mounts it
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
StepFailed, check_grid, expected_grid = _pc.StepFailed, _pc.check_grid, _pc.expected_grid


def test_an_empty_field_and_a_pipe_in_a_title_print_as_the_template_prints_them() -> None:
    # The Adapter sends `/` for `|` and an empty field for no value; the template prints the fields whitespace-collapsed.
    courses = [{"term": "TERM 1/2025", "credits": "3", "gpa": "", "cumGpa": "",
                "courses": [{"no": "CS701", "title": "X | Y", "lab": "0", "lec": "45", "credits": "3", "grade": ""}]}]
    assert expected_grid(courses) == "TERM TERM 1/2025 3 COURSE CS701 X / Y 0 45 3"


def test_a_number_or_null_in_the_record_is_a_field_not_an_error() -> None:
    courses = [{"term": "T", "credits": 3, "gpa": None, "cumGpa": 3.5,
                "courses": [{"no": "A1", "title": "B", "lab": 0, "lec": 45, "credits": 3, "grade": None}]}]
    assert expected_grid(courses) == "TERM T 3 3.5 COURSE A1 B 0 45 3"


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


def test_a_term_with_no_courses_key_or_a_null_one_is_a_term_without_courses() -> None:
    # The Adapter's rule: `block.get("courses") or []`. A record's term without courses must not end in a KeyError.
    for term in ({"term": "T", "credits": "1", "gpa": "", "cumGpa": ""},
                 {"term": "T", "credits": "1", "gpa": "", "cumGpa": "", "courses": None}):
        assert check_grid("COURSE-GRID-START TERM T 1 COURSE-GRID-END", [term]) == "1 term headings and 0 course rows, in order"
        try:
            check_grid("COURSE-GRID-START TERM X 1 COURSE-GRID-END", [term])
        except StepFailed:
            pass
        else:
            raise AssertionError("a wrong grid must be a StepFailed")



def test_help_without_the_mounted_adapter_module_is_a_one_line_setup_failure() -> None:
    """print_check.py runs in the ait-vc image with ait_courses.py mounted beside it; without the mount it must say so."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copy(REPO_ROOT / "src" / "tools" / "print_check.py", tmp)
        (Path(tmp) / "httpx.py").write_text("", encoding="utf-8")  # stand-ins, so only ait_courses is missing
        (Path(tmp) / "pypdf.py").write_text("PdfReader = object" + chr(10), encoding="utf-8")
        run = subprocess.run([sys.executable, str(Path(tmp) / "print_check.py"), "--help"],
                             cwd=tmp, capture_output=True, text=True, env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})
    out = run.stdout + run.stderr
    assert run.returncode == 1 and "FAIL setup" in out and "Traceback" not in out, (run.returncode, out)



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
