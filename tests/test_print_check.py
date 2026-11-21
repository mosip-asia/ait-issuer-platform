"""The print check's expected course grid must match what the template prints for courseRows.

Host only, no stack: src/tools/print_check.py needs httpx and pypdf at import, and the grid function uses neither, so
the test puts stand-ins for them in sys.modules. Run: python3 tests/test_print_check.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))  # print_check.py imports ait_courses, as the image mounts it
sys.path.insert(0, str(REPO_ROOT / "src" / "tools"))
for name, attr in (("httpx", None), ("pypdf", "PdfReader")):
    if name not in sys.modules:
        stub = types.ModuleType(name)
        if attr:
            setattr(stub, attr, object)
        sys.modules[name] = stub

from print_check import expected_grid  # noqa: E402


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


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
