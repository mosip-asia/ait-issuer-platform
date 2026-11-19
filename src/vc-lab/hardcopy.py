"""The hard copy's PDF: rendered template HTML over an optional background page.

Part of the vc-lab module. An organisation may print its transcript on pre-printed paper (a watermark, a seal,
a signature). Uploaded as a PDF, that paper becomes the background: page 1 of the upload, its own /Rotate and
crop box respected, fitted once onto a portrait A4 page and never redrawn. render_pdf lays it under page 1 of
the rendered template. The Admin Portal's hard copy can call render_pdf the same way.
"""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter, Transformation

A4 = (595.28, 841.89)  # points, portrait


def make_background(filename: str, data: bytes) -> bytes:
    """Page 1 of an uploaded PDF, fitted on a portrait A4 page, as a one-page PDF. ValueError for anything else."""
    if not data.startswith(b"%PDF"):
        raise ValueError(f"background {filename!r} is not a PDF")
    try:
        src = PdfReader(io.BytesIO(data)).pages[0]
    except Exception as e:
        raise ValueError(f"background {filename!r} could not be read as a PDF: {e}") from None

    box = src.cropbox  # what a viewer shows; pypdf clips merged content to it
    w, h = float(box.width), float(box.height)
    turn = src.rotation % 360  # clockwise, as a viewer applies it
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
    writer = PdfWriter()
    writer.add_blank_page(width=A4[0], height=A4[1]).merge_transformed_page(src, place)
    return _bytes(writer)


def render_pdf(html: str, background: bytes | None = None) -> bytes:
    """Render template HTML to PDF; a background page (from make_background) goes under page 1 only."""
    from weasyprint import HTML  # imported here: it needs Pango, which only the container is sure to have

    rendered = HTML(string=html).write_pdf()
    if background is None:
        return rendered

    writer = PdfWriter()
    for i, page in enumerate(PdfReader(io.BytesIO(rendered)).pages):
        if i == 0:
            writer.add_page(PdfReader(io.BytesIO(background)).pages[0]).merge_page(page)
        else:
            writer.add_page(page)
    return _bytes(writer)


def _bytes(writer: PdfWriter) -> bytes:
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
