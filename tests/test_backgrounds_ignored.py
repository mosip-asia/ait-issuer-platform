"""A Background placed under an Installation's VDR templates folder can never be committed.

An organisation's Background is its paper: it is published on that organisation's own VDR and stays out of git
(scripts/print-check.sh and the VC Lab publish command put one there). Host only, no Docker, but it asks git, so it
runs inside the repository. Run: python3 tests/test_backgrounds_ignored.py
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = "deploy/ait/vdr/templates"


def ignored(path: str) -> bool:
    """Whether the repository's own ignore rules cover the path, which needn't exist. --no-index judges a path git
    tracks by the rules alone (check-ignore would say "not ignored" for any tracked file, so a rule that hid a
    committed file could never fail the negative test), and an empty user-level excludes file keeps the answer the
    same on every machine. core.ignorecase=false makes the match case-sensitive as on Linux, whatever the checkout's own
    setting (Windows checkouts default to true, which would hide a rule that misses an extension's case)."""
    command = ["git", "-c", f"core.excludesFile={os.devnull}", "-c", "core.ignorecase=false", "check-ignore", "--no-index", "-q", path]
    return subprocess.run(command, cwd=REPO_ROOT).returncode == 0


def test_a_background_under_the_templates_folder_is_ignored() -> None:
    for path in (
        f"{TEMPLATES}/ait-transcript/background.png",  # where display[0].background_image.uri points
        f"{TEMPLATES}/ait-transcript/background.jpg",
        f"{TEMPLATES}/ait-transcript/background.jpeg",
        f"{TEMPLATES}/background.png",
        f"{TEMPLATES}/a/b/paper.png",
        f"{TEMPLATES}/ait-transcript/background.PNG",  # Linux is case-sensitive
        f"{TEMPLATES}/ait-transcript/background.JPG",
        f"{TEMPLATES}/ait-transcript/background.JPEG",
        f"{TEMPLATES}/ait-transcript/background.Png",  # any mix of cases
        f"{TEMPLATES}/ait-transcript/b.jPg",
        f"{TEMPLATES}/ait-transcript/b.JpEg",
        "deploy/another-installation/vdr/templates/ait-transcript/background.png",
    ):
        assert ignored(path), f"git doesn't ignore {path}"


def test_a_font_under_the_templates_folder_is_ignored() -> None:
    """A font the template loads through @font-face is published on the VDR like a Background, and may carry a licence
    that forbids redistribution, so it stays out of git too."""
    for path in (
        f"{TEMPLATES}/fonts/narrow.ttf",
        f"{TEMPLATES}/fonts/thai.otf",
        f"{TEMPLATES}/fonts/a.woff",
        f"{TEMPLATES}/fonts/a.woff2",
        f"{TEMPLATES}/fonts/a.TTF",
        f"{TEMPLATES}/fonts/a.Woff2",
        f"{TEMPLATES}/a.OtF",
        "deploy/another-installation/vdr/templates/fonts/narrow.ttf",
    ):
        assert ignored(path), f"git doesn't ignore {path}"


def test_the_print_checks_font_folder_is_ignored() -> None:
    assert ignored(f"{TEMPLATES}/print-check/thai-font.ttf")


def test_templates_and_brand_assets_are_not_ignored() -> None:
    for path in (
        f"{TEMPLATES}/AITUniversity-ait-transcript-template.html",
        "deploy/ait/vdr/assets/AIT_globe.png",  # the logo: brand assets are committed
    ):
        assert not ignored(path), f"git ignores {path}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"PASS {name}")
