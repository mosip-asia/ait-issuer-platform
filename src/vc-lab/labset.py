"""The uploaded set VC Lab works on: a template, a credential file, a sample and an optional background.

Part of the vc-lab module. A set is immutable; uploading builds a new one. Every file is parsed here, at the
upload boundary, so a LabSet only ever holds files that render: a wrong file is a ValueError with a plain
reason, and nothing past this module checks a file again. Nothing here touches the disk.
"""

from __future__ import annotations

import dataclasses
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

import hardcopy
import template_engine

MAX_UPLOAD = 8 * 1024 * 1024  # bytes: one request, and the files unpacked from one zip
SLOTS = ("template", "credential", "sample", "background")
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
    background: Loaded[bytes] | None = None  # the upload's page 1 fitted on portrait A4 (hardcopy.make_background)

    def loaded(self) -> dict[str, str | None]:
        """Each slot's file name, None when empty."""
        return {slot: (f.filename if (f := getattr(self, slot)) else None) for slot in SLOTS}

    def missing(self) -> list[str]:
        """The slots rendering needs that are empty."""
        return [slot for slot in REQUIRED if getattr(self, slot) is None]

    def replace(self, files: dict[str, tuple[str, bytes]]) -> LabSet:
        """This set with the given slots replaced by the parsed files ({slot: (filename, data)})."""
        return dataclasses.replace(self, **{slot: parse(slot, name, data) for slot, (name, data) in files.items()})


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
    template_engine.check_template(source)
    return source


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
    return config


_PARSERS: dict[str, Callable[[str, bytes], Any]] = {
    "template": _template,
    "credential": _credential,
    "sample": lambda name, data: _json_object("sample", name, data),
    "background": hardcopy.make_background,
}


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
    return LabSet().replace(files)
