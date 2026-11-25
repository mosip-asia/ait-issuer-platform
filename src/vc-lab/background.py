"""The Background as the Wallet draws it: one PNG.

Part of the vc-lab module. An organisation may print on pre-printed paper (a watermark, a seal, a signature, its
logo). The Wallet draws that paper as the template's `$backgroundImage`, a PNG, so VC Lab keeps the Background as
that PNG and nothing else. `to_png` makes it from what a staff member has: a PDF, a PNG or a JPEG.
"""

from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image

DPI = 150  # a PDF page is drawn at its own size, at this resolution
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def to_png(filename: str, data: bytes) -> bytes:
    """An uploaded PDF (page 1), PNG or JPEG as a PNG. ValueError, naming the file, for anything else."""
    if data.startswith(b"%PDF"):
        return _png_of(_first_page(filename, data))
    if data.startswith(PNG_MAGIC):
        _open(filename, data)
        return data
    if data.startswith(b"\xff\xd8\xff"):
        return _png_of(_open(filename, data))
    raise ValueError(f"background {filename!r} is not a PDF, PNG or JPEG")


def check_png(filename: str, data: bytes) -> bytes:
    """The set holds the Background as a PNG only (to_png makes it). ValueError when this is not one."""
    if not data.startswith(PNG_MAGIC):
        raise ValueError(f"background {filename!r} is not a PNG: turn a PDF or JPEG into one first (POST /api/background)")
    _open(filename, data)
    return data


def _open(filename: str, data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()  # decodes every pixel, so a truncated file fails here and not in the renderer
    except Exception as e:
        raise ValueError(f"background {filename!r} could not be read as an image: {e}") from None
    return image


def _first_page(filename: str, data: bytes) -> Image.Image:
    """Page 1 as pdfium shows it: /Rotate applied, the crop box as the page."""
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        # pdfium refuses a document with no pages the same way as a damaged one, so the reason names both.
        raise ValueError(f"background {filename!r} could not be read as a PDF, or it has no pages: {e}") from None
    with pdf:
        if len(pdf) == 0:
            raise ValueError(f"background {filename!r} is a PDF with no pages")
        try:
            return pdf[0].render(scale=DPI / 72).to_pil()
        except pdfium.PdfiumError as e:
            raise ValueError(f"background {filename!r} page 1 could not be drawn: {e}") from None


def _png_of(image: Image.Image) -> bytes:
    if image.mode not in ("RGB", "RGBA", "L", "LA"):
        image = image.convert("RGB")  # CMYK and palette JPEGs; PNG has no CMYK
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
