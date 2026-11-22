"""The parity check's comparison (src/tools/parity_check.py differences) on hand-made PDFs.

Host only, no stack. It needs pypdf, as parity_check does (CI installs it). The PDFs are written byte by byte here, not
with the code under test: one page, text lines in a font named as asked (with a ToUnicode map, so Thai extracts), and
grey images drawn at a given rectangle.
Run: python3 tests/test_parity_check.py
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))  # print_check imports ait_courses, as the image mounts it
sys.path.insert(0, str(REPO_ROOT / "src" / "tools"))

import parity_check  # noqa: E402
from print_check import BACKGROUND_PX, FONT_NAME  # noqa: E402

A4 = (595, 842)
THAI = "ภาษาไทย"
# Single-byte codes for the Thai letters, declared in the font's ToUnicode map; ASCII maps to itself.
THAI_CODES = {ch: 0x80 + i for i, ch in enumerate(sorted(set(THAI)))}
FULL_PAGE = (BACKGROUND_PX, 0, 0, *A4)  # (pixels, x, y, w, h): the Background drawn over the whole page


def make_pdf(lines: list[str], font: str = FONT_NAME, images: list[tuple] = (FULL_PAGE,)) -> bytes:
    """A one-page A4 PDF: each image ((width, height) px, x, y, w, h in points), then each line of text."""
    def text(line: str) -> str:
        return "".join(f"{THAI_CODES.get(ch, ord(ch)):02X}" for ch in line)

    draws = [f"q {w} 0 0 {h} {x} {y} cm /Im{i} Do Q" for i, (_, x, y, w, h) in enumerate(images)]
    draws += [f"BT /F1 10 Tf 1 0 0 1 40 {800 - 14 * n} Tm <{text(line)}> Tj ET" for n, line in enumerate(lines)]
    content = "\n".join(draws).encode()
    cmap = ("/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /Test def "
            "1 begincodespacerange <00> <FF> endcodespacerange 1 beginbfrange <20> <7E> <0020> endbfrange "
            f"{len(THAI_CODES)} beginbfchar "
            + " ".join(f"<{code:02X}> <{ord(ch):04X}>" for ch, code in THAI_CODES.items())
            + " endbfchar endcmap CMapName currentdict /CMap defineresource pop end end").encode()
    xobjects = " ".join(f"/Im{i} {6 + i} 0 R" for i in range(len(images)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] /Contents 4 0 R "
         f"/Resources << /Font << /F1 5 0 R >> /XObject << {xobjects} >> >> >>").encode(),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{font} /ToUnicode {6 + len(images)} 0 R >>".encode(),
    ]
    for (pw, ph), *_ in images:
        pixels = zlib.compress(bytes([200]) * (pw * ph))
        objects.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray "
                       b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (pw, ph, len(pixels))
                       + pixels + b"\nendstream")
    objects.append(b"<< /Length %d >>\nstream\n" % len(cmap) + cmap + b"\nendstream")
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


# What the made-up set prints when every feature reaches the page.
FULL_LINES = [f"THAI-TYPED: {THAI}", "fullName [fullName]: Nara Wattanakul",
              "programCommittee [programCommittee]: " + ", ".join(parity_check.LIST_OF_TEXT),
              "TERM August Semester 2024 9 3.67 3.67"]


def found(preview: bytes, wallet: bytes) -> dict[str, list[str]]:
    return {kind: lines for kind, lines in parity_check.differences(preview, wallet).items() if lines}


def test_two_prints_that_agree_and_show_every_feature_pass() -> None:
    pdf = make_pdf(FULL_LINES)
    assert found(pdf, make_pdf(FULL_LINES)) == {}, found(pdf, make_pdf(FULL_LINES))


def test_a_text_difference_is_named_with_both_sides() -> None:
    wallet = FULL_LINES[:1] + ["fullName [fullName]: Nara Wattanakul (Wallet)"] + FULL_LINES[2:]
    result = found(make_pdf(FULL_LINES), make_pdf(wallet))
    assert list(result) == ["page text"], result
    assert "the Wallet has '(Wallet)'" in result["page text"][0], result


def test_a_feature_lost_on_both_sides_is_named() -> None:
    # The same loss in VC Lab and the Wallet: Helvetica only, no Thai, no Background, no grid, the list emptied.
    lost = ["fullName [fullName]: Nara Wattanakul", "programCommittee [programCommittee]:"]
    pdf = make_pdf(lost, font="Helvetica", images=[])
    result = found(pdf, make_pdf(lost, font="Helvetica", images=[]))
    named = " ".join(result.get("the set's features", []))
    for missing in (FONT_NAME, f"{BACKGROUND_PX[0]}x{BACKGROUND_PX[1]}", "Thai", "TERM",
                    ", ".join(parity_check.LIST_OF_TEXT)):
        assert missing in named, (missing, result)
    assert list(result) == ["the set's features"], result


def test_an_image_drawn_at_another_size_is_named() -> None:
    corner = (BACKGROUND_PX, 0, 0, 100, 141)  # the same pixels, drawn small in a corner
    result = found(make_pdf(FULL_LINES), make_pdf(FULL_LINES, images=[corner]))
    assert list(result) == ["image sizes"], result
    assert "100" in result["image sizes"][0] and "141" in result["image sizes"][0], result


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"PASS {t.__name__}")
    print(f"{len(tests)} tests passed")
