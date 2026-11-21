"""A Background placed under an Installation's VDR templates folder can never be committed.

An organisation's Background is its paper: it is published on that organisation's own VDR and stays out of git
(scripts/print-check.sh and the VC Lab publish command put one there). Host only, no Docker, but it asks git, so it
runs inside the repository. Run: python3 tests/test_backgrounds_ignored.py
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = "deploy/ait/vdr/templates"


def ignored(path: str) -> bool:
    """Whether git ignores the path (which needn't exist)."""
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT).returncode == 0


def test_a_background_under_the_templates_folder_is_ignored() -> None:
    for path in (
        f"{TEMPLATES}/ait-transcript/background.png",  # where display[0].background_image.uri points
        f"{TEMPLATES}/ait-transcript/background.jpg",
        f"{TEMPLATES}/ait-transcript/background.jpeg",
        f"{TEMPLATES}/background.png",
        f"{TEMPLATES}/a/b/paper.png",
        "deploy/another-installation/vdr/templates/ait-transcript/background.png",
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
