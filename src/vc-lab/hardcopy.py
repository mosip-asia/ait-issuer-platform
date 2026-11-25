"""The hard copy's background page, laid under the PDF the renderer prints.

Part of the vc-lab module. An organisation may print its transcript on pre-printed paper (a watermark, a seal,
a signature). Uploaded as a PDF, that paper becomes the background: page 1 of the upload, its own /Rotate and
crop box respected, fitted once onto a portrait A4 page and never redrawn. lay_background lays it under page 1
of the rendered PDF.
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


def lay_background(rendered: bytes, background: bytes) -> bytes:
    """The rendered PDF with a background page (from make_background) under page 1 only."""
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
