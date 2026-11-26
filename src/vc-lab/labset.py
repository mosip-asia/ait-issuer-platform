"""The set of files one request carries: a template, a credential file, a sample and an optional Background (a PNG).

Part of the vc-lab module. The dashboard holds the set and sends it with every call; the server keeps none. Every
file is parsed here, at the request boundary, so a LabSet only ever holds files that render: a wrong file is a
ValueError with a plain reason, and nothing past this module checks a file again. Nothing here touches the disk.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

import background

MAX_UPLOAD = 20 * 1024 * 1024  # bytes: one request, and the files unpacked from one Package
REQUIRED = ("template", "credential", "sample")

T = TypeVar("T")


@dataclass(frozen=True)
class Loaded(Generic[T]):
    filename: str  # as uploaded, made safe (no path parts)
    data: bytes  # the file exactly as uploaded; Export Package writes it as is
    value: T  # what VC Lab uses: the parsed file


@dataclass(frozen=True)
class LabSet:
    template: Loaded[str] | None = None  # the Velocity HTML
    credential: Loaded[dict[str, Any]] | None = None  # Certify's credential file, with a vc_template object
    sample: Loaded[dict[str, Any]] | None = None  # the Adapter's response, a JSON object
    background: Loaded[bytes] | None = None  # the PNG the template draws as $backgroundImage (background.to_png)

    def missing(self) -> list[str]:
        """The slots rendering needs that are empty."""
        return [slot for slot in REQUIRED if getattr(self, slot) is None]

    @classmethod
    def from_files(cls, files: dict[str, tuple[str, bytes]]) -> LabSet:
        """The set of the parsed files ({slot: (filename, data)})."""
        return cls(**{slot: parse(slot, name, data) for slot, (name, data) in files.items()})


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
    depth = 0
    for tag in _VELOCITY.finditer(source):
        word = tag.group("word") or tag.group("braced")
        if tag.group("escape") is None or len(tag.group("escape")) % 2:  # a comment or unparsed text, or an escaped #
            continue
        depth += -1 if word == "end" else 1
        if depth < 0:
            raise ValueError(f"template {name!r} has an #end without an #if, #foreach, #macro, #define or #@macro")
    if depth:
        raise ValueError(f"template {name!r} has {depth} #if, #foreach, #macro, #define or #@macro without an #end")
    return source


# One pass over the source, so what a comment or #[[unparsed]]# holds is never read as a directive. Velocity 1.7's block
# directives (each closed by #end) in their plain and #{braced} forms, and #@name( for a block macro call (#@name with no
# ( after it, and #{@name}, are text); a directive behind an odd number of backslashes is escaped. Linear: a backslash
# run is matched from its first backslash only, and a comment or unparsed text that never closes runs to the end.
_VELOCITY = re.compile(
    r"##[^\n]*|#\*.*?(?:\*#|\Z)|#\[\[.*?(?:\]\]#|\Z)"  # a line comment, a block comment, unparsed text
    r"|(?<!\\)(?P<escape>\\*)#(?:(?P<word>if|foreach|macro|define|end)\b|\{(?P<braced>if|foreach|macro|define|end)\}"
    r"|@\w+\s*\()",
    re.DOTALL)


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
    "background": background.check_png,
}
assert set(_PARSERS) == set(SLOTS), "every slot of LabSet needs a parser"


def safe_filename(filename: str, fallback: str) -> str:
    """The file name without any path parts or control characters; the fallback when nothing is left."""
    name = re.split(r"[\\/]", filename or "")[-1]
    name = re.sub(r"[\x00-\x1f\x7f\"]", "", name).strip().lstrip(".")
    return name or fallback
