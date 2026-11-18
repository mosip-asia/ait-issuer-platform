"""The hard copy's PDF: the rendered template over an optional background.

Part of the vc-lab module. A background is what AIT prints first on blank paper (the watermark, seal and
signature); the template is what it prints second. Here the background is an uploaded PDF or image, never
edited: it is turned by the chosen rotation and fitted once onto a portrait A4 page, and the template's first
page is laid over that page. VC Lab holds backgrounds in memory only, so the confidential watermark never
reaches git or the public VDR. The Portal's hard copy calls render_pdf with the same template.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

A4 = (595.28, 841.89)  # points, portrait
ROTATIONS = (0, 90, 180, 270)  # clockwise


@dataclass(frozen=True)
class Background:
    filename: str
    original: bytes  # the uploaded file, as uploaded
    rotation: int  # clockwise degrees, one of ROTATIONS
    page_pdf: bytes  # one portrait A4 page: the upload turned and fitted
    preview_jpeg: bytes  # page_pdf as an image, for the HTML preview


def make_background(filename: str, data: bytes, rotation: int = 0) -> Background:
    """Place an uploaded PDF, PNG or JPEG on a portrait A4 page. Raises ValueError for anything else."""
    if rotation not in ROTATIONS:
        raise ValueError(f"rotation must be one of {ROTATIONS}, got {rotation}")
    page_pdf = _fit_on_a4(_as_pdf(data), rotation)
    return Background(filename, data, rotation, page_pdf, _render_jpeg(page_pdf))


def render_pdf(html: str, background: Background | None = None) -> bytes:
    """Render template HTML to PDF; with a background, its page goes under the first page."""
    from weasyprint import HTML  # imported here: it needs Pango, which only the container is sure to have

    info = HTML(string=html).write_pdf()
    if background is None:
        return info

    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for i, page in enumerate(PdfReader(io.BytesIO(info)).pages):
        if i == 0:
            writer.add_page(PdfReader(io.BytesIO(background.page_pdf)).pages[0]).merge_page(page)
        else:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _as_pdf(data: bytes) -> bytes:
    if data.startswith(b"%PDF"):
        return data
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError:
        raise ValueError("background must be a PDF, PNG or JPEG file") from None
    out = io.BytesIO()
    image.convert("RGB").save(out, "PDF", resolution=300)
    return out.getvalue()


def _fit_on_a4(source_pdf: bytes, rotation: int) -> bytes:
    from pypdf import PageObject, PdfReader, PdfWriter, Transformation

    try:
        src = PdfReader(io.BytesIO(source_pdf)).pages[0]
    except Exception as e:
        raise ValueError(f"background PDF could not be read: {e}") from None
    box = src.cropbox  # what a viewer shows; pypdf clips merged content to it
    w, h = float(box.width), float(box.height)
    turn = (rotation + src.rotation) % 360  # the source's own /Rotate counts too
    # After turning clockwise by `turn` about the origin, shift the content back into the positive quadrant.
    shift = {0: (0, 0), 90: (0, w), 180: (w, h), 270: (h, 0)}[turn]
    tw, th = (h, w) if turn in (90, 270) else (w, h)
    scale = min(A4[0] / tw, A4[1] / th)
    place = (
        Transformation()
        .translate(-float(box.left), -float(box.bottom))
        .rotate(-turn)
        .translate(*shift)
        .scale(scale)
        .translate((A4[0] - tw * scale) / 2, (A4[1] - th * scale) / 2)
    )
    page = PageObject.create_blank_page(width=A4[0], height=A4[1])
    page.merge_transformed_page(src, place)
    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _render_jpeg(page_pdf: bytes) -> bytes:
    import pypdfium2 as pdfium

    image = pdfium.PdfDocument(page_pdf)[0].render(scale=150 / 72).to_pil()
    out = io.BytesIO()
    image.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue()
