"""Velocity details of VC Lab's template engine. Everything else is tested through the web API (test_main.py).

Run:
    python3 src/vc-lab/test_template_engine.py
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import template_engine as engine  # noqa: E402


def test_nested_foreach() -> None:
    template = "#foreach($t in $terms)[$t.term:#foreach($c in $t.courses)<$c.no $c.grade>#end]#end"
    context = {"terms": [
        {"term": "T1", "courses": [{"no": "AB101", "grade": "B+"}, {"no": "AB102", "grade": "A"}]},
        {"term": "T2", "courses": [{"no": "AB201", "grade": "A & B"}]},
    ]}
    rendered = engine.render_velocity_template(template, context, {})
    assert rendered == "[T1:<AB101 B+><AB102 A>][T2:<AB201 A &amp; B>]", rendered


def test_if_else() -> None:
    template = "#foreach($c in $courses)#if($c.grade)$c.grade#else-#end;#end#if($missing)yes#else no#end"
    rendered = engine.render_velocity_template(template, {"courses": [{"grade": "A"}, {"grade": ""}]}, {})
    assert rendered == "A;-; no", rendered


def test_longest_variable_name_wins() -> None:
    rendered = engine.render_velocity_template("$title|$titleName|${title}", {"title": "x", "titleName": "y"}, {})
    assert rendered == "x|y|x", rendered


def test_loop_data_prints_as_written() -> None:
    template = "#foreach($c in $courses)<p>$c.title</p>#end"
    title = "Costs in $title and #if($title)never#end, 'quoted' <b>"
    rendered = engine.render_velocity_template(template, {"title": "LEAK", "courses": [{"title": title}]}, {})
    assert "LEAK" not in rendered and "never" in rendered, rendered
    assert html.unescape(rendered) == f"<p>{title}</p>", rendered


def test_claim_data_prints_as_written() -> None:
    value = "Costs in $title and #if($title)never#end"
    rendered = engine.render_velocity_template("<p>#claimValue('note')</p>", {"title": "LEAK"}, {"note": value})
    assert html.unescape(rendered) == f"<p>{value}</p>", rendered


def main() -> None:
    tests = [test_nested_foreach, test_if_else, test_longest_variable_name_wins, test_loop_data_prints_as_written,
             test_claim_data_prints_as_written]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests passed")


if __name__ == "__main__":
    main()
