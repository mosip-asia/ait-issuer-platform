"""The uploaded set VC Lab works on: a template, a credential file, a sample and an optional background image.

Part of the vc-lab module. A set is immutable; uploading builds a new one. Every file is parsed here, at the
upload boundary: a wrong file is a ValueError with a plain reason. The template is only checked to be UTF-8
text; Velocity judges the rest when it renders, so the renderer's 422 names the line. Nothing here touches the disk.
"""

from __future__ import annotations

import base64
import dataclasses
import io
import json
import re
import struct
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

MAX_UPLOAD = 8 * 1024 * 1024  # bytes: one request, and the files unpacked from one zip
# The files of a set together, so that Download's zip (the files plus its own headers) is a request VC Lab takes
# back. The slack is far above a zip's headers and deflate's worst case on an incompressible PNG.
MAX_SET = MAX_UPLOAD - 64 * 1024
# The biggest Background, in pixels. A4 at 300 dpi is 2480 x 3508 = 8.7 million, so this keeps 15% above print
# quality. The renderer decodes the image, 4 bytes a pixel, inside a 640 MB heap shared by up to four prints: a
# file's size says little (a PNG of one colour is tiny), so the size in its header is what's bounded.
MAX_PIXELS = 10_000_000
REQUIRED = ("template", "credential", "sample")

T = TypeVar("T")


@dataclass(frozen=True)
class Loaded(Generic[T]):
    filename: str  # as uploaded, made safe (no path parts)
    data: bytes  # the file exactly as uploaded; Download gives it back
    value: T  # what VC Lab uses: the parsed file


@dataclass(frozen=True)
class LabSet:
    template: Loaded[str] | None = None  # the Velocity HTML
    credential: Loaded[dict[str, Any]] | None = None  # Certify's credential file, with a vc_template object
    sample: Loaded[dict[str, Any]] | None = None  # the Adapter's response, a JSON object
    background: Loaded[str] | None = None  # a PNG or JPEG, as the data: URI the renderer takes for $backgroundImage

    def loaded(self) -> dict[str, str | None]:
        """Each slot's file name, None when empty."""
        return {slot: (f.filename if (f := getattr(self, slot)) else None) for slot in SLOTS}

    def missing(self) -> list[str]:
        """The slots rendering needs that are empty."""
        return [slot for slot in REQUIRED if getattr(self, slot) is None]

    def replace(self, files: dict[str, tuple[str, bytes]]) -> LabSet:
        """This set with the given slots replaced by the parsed files ({slot: (filename, data)})."""
        new = dataclasses.replace(self, **{slot: parse(slot, name, data) for slot, (name, data) in files.items()})
        total = sum(len(f.data) for slot in SLOTS if (f := getattr(new, slot)) is not None)
        if total > MAX_SET:
            mb = 1024 * 1024
            raise ValueError(f"the set would hold {total / mb:.1f} MB of files in all; it can hold {MAX_SET / mb:.1f} MB "
                             "in all, so that Download's zip uploads back")
        return new


SLOTS = tuple(f.name for f in dataclasses.fields(LabSet))


def parse(slot: str, filename: str, data: bytes) -> Loaded[Any]:
    """Parse one uploaded file for its slot. ValueError, with a plain reason, when it is the wrong kind."""
    if slot not in _PARSERS:
        raise ValueError(f"unknown slot {slot!r}; the slots are {', '.join(SLOTS)}")
    name = safe_filename(filename, slot)
    return Loaded(name, data, _PARSERS[slot](name, data))


def _template(name: str, data: bytes) -> str:
    try:
        source = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"template {name!r} is not UTF-8 text") from None
    return source  # Velocity checks the rest when it renders: /preview.pdf answers 422 with the line


def _png_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the IHDR chunk, which a PNG starts with; None when it isn't there."""
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the first start-of-frame marker (SOF0 to SOF15, not DHT, JPG or DAC); None when the
    marker segments end, or run past the data, before one."""
    i = 2  # after SOI
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
        elif marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers with no segment
            i += 2
        elif marker in (0xD9, 0xDA):  # the image ends, or its data starts, with no size given
            return None
        else:
            length = int.from_bytes(data[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if length < 8 or i + 9 > len(data):
                    return None
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return width, height
            if length < 2:
                return None
            i += 2 + length
    return None


_IMAGES = ((b"\x89PNG\r\n\x1a\n", "image/png", _png_size), (b"\xff\xd8\xff", "image/jpeg", _jpeg_size))


def _background(name: str, data: bytes) -> str:
    """The image as a data: URI. Its kind and size are read from the file's own header, never from its name; a file
    whose header can't be read, or whose image is over MAX_PIXELS, is refused."""
    for signature, media_type, read_size in _IMAGES:
        if data.startswith(signature):
            size = read_size(data)
            if size is None or 0 in size:
                break
            if size[0] * size[1] > MAX_PIXELS:
                raise ValueError(f"background {name!r} is {size[0]} x {size[1]} pixels; VC Lab takes at most "
                                 f"{MAX_PIXELS:,} (A4 at 300 dpi is 2480 x 3508): scale the image down")
            return f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}"
    raise ValueError(f"background {name!r} is not a PNG or JPEG image; upload the organisation's paper as PNG or JPEG")


def _json_object(slot: str, name: str, data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"{slot} {name!r} is not JSON: {e}") from None
    if not isinstance(value, dict):
        raise ValueError(f"{slot} {name!r} must be a JSON object")
    return value


def _credential(name: str, data: bytes) -> dict[str, Any]:
    config = _json_object("credential file", name, data)
    vc_template = config.get("vc_template")
    if not isinstance(vc_template, dict):
        raise ValueError(f"credential file {name!r} has no vc_template object")
    if not isinstance(vc_template.get("credentialSubject"), dict):
        raise ValueError(f"credential file {name!r}: vc_template has no credentialSubject object (the mapping)")
    display = config.get("display", [])
    if not isinstance(display, list) or not all(isinstance(entry, dict) for entry in display):
        raise ValueError(f"credential file {name!r}: display must be a list of objects")
    if display and not isinstance(display[0].get("logo") or {}, dict):
        raise ValueError(f"credential file {name!r}: display's logo must be an object")
    return config


_PARSERS: dict[str, Callable[[str, bytes], Any]] = {
    "template": _template,
    "credential": _credential,
    "sample": lambda name, data: _json_object("sample", name, data),
    "background": _background,
}
assert set(_PARSERS) == set(SLOTS), "every slot of LabSet needs a parser"


def safe_filename(filename: str, fallback: str) -> str:
    """The file name without any path parts or control characters; the fallback when nothing is left."""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = re.sub(r"[\x00-\x1f\x7f\"]", "", name).strip().lstrip(".")
    return name or fallback


def to_zip(lab: LabSet) -> bytes:
    """The set as a zip: one folder per loaded slot, holding the file as uploaded under its name."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for slot in SLOTS:
            if (f := getattr(lab, slot)) is not None:
                z.writestr(f"{slot}/{f.filename}", f.data)
    return out.getvalue()


def from_zip(data: bytes) -> LabSet:
    """The set a zip from to_zip holds. ValueError for anything else."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("bundle is not a zip file") from None
    with z:
        members = [m for m in z.infolist() if not m.is_dir()]
        if sum(m.file_size for m in members) > MAX_UPLOAD:
            raise ValueError(f"bundle unpacks to more than {MAX_UPLOAD // (1024 * 1024)} MB")
        files: dict[str, tuple[str, bytes]] = {}
        for m in members:
            slot, _, name = m.filename.partition("/")
            if slot not in SLOTS or not name or "/" in name:
                expected = f"<slot>/<file> with a slot of {', '.join(SLOTS)}"
                raise ValueError(f"bundle holds {m.filename!r}; expected {expected}")
            if slot in files:
                raise ValueError(f"bundle holds more than one {slot} file")
            files[slot] = (name, z.read(m))
    if not files:
        raise ValueError("bundle holds no files")
    try:
        return LabSet().replace(files)
    except ValueError as e:
        if "background" in files and str(e).startswith("background"):
            raise ValueError(f"{e}; remove background/ from the zip, or upload the files one at a time") from None
        raise
