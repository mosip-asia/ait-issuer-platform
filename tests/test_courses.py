"""Plain-assert smoke tests for ait_courses.py (PLAN.md Phase 0 Tests).

Run: python3 src/adapter/test_courses.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))
from ait_courses import (  # noqa: E402
    PackValidationError,
    derive_course_rows_from_courses,
    enrich_ait_transcript_subject,
    parse_courses,
)

_SAMPLE_COURSES = [
    {
        "term": "August Semester 2024",
        "courses": [
            {"no": "CS601", "title": "Advanced Algorithms", "lab": "0", "lec": "45", "credits": "3", "grade": "A"}
        ],
        "credits": "3",
        "gpa": "4.00",
        "cumGpa": "4.00",
    }
]


def test_enrich_derives_courses_and_course_list_only() -> None:
    subject = {"id": "x", "courses": _SAMPLE_COURSES}
    out = enrich_ait_transcript_subject(subject)
    assert out["courses"] == (
        '[{"term":"August Semester 2024","courses":[{"no":"CS601","title":"Advanced Algorithms",'
        '"lab":"0","lec":"45","credits":"3","grade":"A"}],"credits":"3","gpa":"4.00","cumGpa":"4.00"}]'
    )
    assert out["courseList"] == "Advanced Algorithms — A"
    assert out["courseRows"] == "T|August Semester 2024|3|4.00|4.00\nC|CS601|Advanced Algorithms|0|45|3|A"
    assert set(out) == {"id", "courses", "courseList", "courseRows"}, "no other derived claim (the HTML course table is gone)"


def test_course_rows_replace_the_separators_inside_a_field() -> None:
    # A `|` or a line break inside a field would split the row wrongly in the template, so each is replaced.
    semesters = parse_courses(
        [{"term": "T|1", "courses": [{"no": "X1", "title": "Pipes | and\nbreaks\r\nhere", "lab": "0", "lec": "3",
                                      "credits": "3", "grade": "A"}],
          "credits": "3", "gpa": "4.00", "cumGpa": "4.00"}]
    )
    lines = derive_course_rows_from_courses(semesters).split("\n")
    assert [len(line.split("|")) for line in lines] == [5, 7], lines
    assert lines[0].startswith("T|T/1|") and lines[1].startswith("C|X1|Pipes / and breaks here|"), lines


def test_an_absent_value_is_an_empty_course_rows_field() -> None:
    # None (a null in the record) is no value, not the text "None".
    rows = derive_course_rows_from_courses(
        [{"term": "T", "credits": "1", "gpa": None, "cumGpa": "3.5",
          "courses": [{"no": "X1", "title": "Y", "lab": None, "lec": "3", "credits": "3", "grade": None}]}]
    )
    assert rows == "T|T|1||3.5\nC|X1|Y||3|3|", rows


def test_course_rows_have_one_heading_per_term_and_one_row_per_course() -> None:
    semesters = parse_courses(
        [{"term": f"Term {t}", "credits": "6", "gpa": "3.50", "cumGpa": "3.50",
          "courses": [{"no": f"C{t}{c}", "title": "Title", "lab": "0", "lec": "3", "credits": "3", "grade": "B+"}
                      for c in range(3)]} for t in range(2)]
    )
    kinds = [line[0] for line in derive_course_rows_from_courses(semesters).split("\n")]
    assert kinds == ["T", "C", "C", "C", "T", "C", "C", "C"]


def test_numbers_inside_courses_become_strings() -> None:
    # The context types courses as @json with no datatypes, so every value inside is a string.
    semesters = parse_courses(
        [{"term": "T", "courses": [{"no": "X1", "title": "Y", "lab": 0, "lec": 45, "credits": 3, "grade": "A"}],
          "credits": 3, "gpa": 4.0, "cumGpa": 3.5}]
    )
    assert semesters == [{"term": "T", "courses": [{"no": "X1", "title": "Y", "lab": "0", "lec": "45",
                                                    "credits": "3", "grade": "A"}],
                          "credits": "3", "gpa": "4.0", "cumGpa": "3.5"}]


def test_missing_term_raises() -> None:
    try:
        parse_courses([{"courses": []}])
    except PackValidationError:
        return
    raise AssertionError("expected PackValidationError for missing term")


def test_missing_course_no_or_title_raises() -> None:
    try:
        parse_courses([{"term": "T", "courses": [{"title": "X"}]}])
    except PackValidationError:
        return
    raise AssertionError("expected PackValidationError for missing course no")


def test_subject_without_courses_passthrough() -> None:
    subject = {"id": "registrar-001", "role": "registrar"}
    out = enrich_ait_transcript_subject(subject)
    assert out == subject


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
