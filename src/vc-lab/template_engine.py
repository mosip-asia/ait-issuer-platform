"""In-memory Velocity rendering for VC Lab: from a sample record to the HTML a template renders.

Part of the vc-lab module. Pure functions only: nothing here reads files, the network or the environment.

The pipeline (render_credential):
1. The record is the sample's credentialSubject when it has one, else the whole sample.
2. The credential file's vc_template.credentialSubject maps the record to the claims (map_claims).
3. The template's context is Mimoto's variables plus every list-valued claim, so the template can loop over it
   (template_context). The Wallet view drops the lists and blanks list claims, as Mimoto 0.21 does.
4. The template is rendered (render_velocity_template): the Velocity subset Mimoto's templates use.
"""

from __future__ import annotations

import base64
import functools
import html
import json
import re
import struct
import zlib
from typing import Any

# ---------------------------------------------------------------------------------------------------------------
# From sample to claims to context


def render_credential(template_text: str, credential: dict[str, Any], sample: dict[str, Any], wallet: bool) -> str:
    """The template rendered for one uploaded set. wallet=True renders what Mimoto would print."""
    claims = credential_subject(credential, sample)
    if wallet:
        claims = {k: "" if isinstance(v, list) else v for k, v in claims.items()}
    display = (credential.get("display") or [{}])[0]  # its shape is checked at upload (labset)
    return render_velocity_template(template_text, template_context(claims, display, wallet), claims)


def credential_subject(credential: dict[str, Any], sample: dict[str, Any]) -> dict[str, Any]:
    """The claims Certify would sign for this sample: the credential file's mapping evaluated against the record,
    which is the sample's credentialSubject, or the whole sample when it has none."""
    record = sample.get("credentialSubject")
    return map_claims(credential["vc_template"]["credentialSubject"], record if isinstance(record, dict) else sample)


# ${name}, ${a.b} or $name, $a.b: a reference to a value in the record.
_REF = re.compile(r"\$\{([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)\}|\$([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)")


def map_claims(mapping: Any, record: dict[str, Any]) -> Any:
    """Evaluate a credential file's mapping against a record.

    A string that is exactly one reference passes the referenced value through unchanged (a list or object
    stays a list or object); references inside longer text are replaced by their text. Objects and lists in the
    mapping are evaluated member by member; other values are kept. A reference to nothing gives "".
    """
    if isinstance(mapping, dict):
        return {k: map_claims(v, record) for k, v in mapping.items()}
    if isinstance(mapping, list):
        return [map_claims(v, record) for v in mapping]
    if not isinstance(mapping, str):
        return mapping
    whole = _REF.fullmatch(mapping)
    if whole:
        return _lookup(whole.group(1) or whole.group(2), record)
    return _REF.sub(lambda m: text(_lookup(m.group(1) or m.group(2), record)), mapping)


def _lookup(path: str, record: dict[str, Any]) -> Any:
    if path.startswith("_"):  # Certify's own variables (_holderId, _issuer, ...): fixed placeholders
        return f"did:example:{path[1:]}"
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return ""
        value = value[part]
    return value


def template_context(claims: dict[str, Any], display: dict[str, Any], wallet: bool) -> dict[str, Any]:
    """Mimoto's variables, taken from the credential file's display entry, plus (except in the Wallet view, as
    Mimoto has none) each claim that holds a list, or text holding a JSON list, under its claim name."""
    lists = {} if wallet else {n: items for n, v in claims.items() if (items := _as_list(v)) is not None}
    return {
        **lists,
        "titleName": display.get("name", ""),
        "logoUrl": (display.get("logo") or {}).get("url", ""),
        "backgroundColor": display.get("background_color", ""),
        "textColor": display.get("text_color", ""),
        "qrCodeImage": generate_mock_qr_png_base64(),
        "credentialValidity": -1,  # Mimoto's value when the credential sets no verification limit
    }


def _as_list(value: Any) -> list | None:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.lstrip().startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, list) else None
    return None


def text(value: Any) -> str:
    """A value as a template prints it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


@functools.cache
def generate_mock_qr_png_base64() -> str:
    """A 100x100 grayscale PNG that looks like a QR code, built in pure Python."""
    width = height = 100
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None)
        for x in range(width):
            outer = x < 12 or x > 87 or y < 12 or y > 87
            top_left = x < 35 and y < 35 and (x < 8 or x > 26 or y < 8 or y > 26 or (14 <= x <= 20 and 14 <= y <= 20))
            top_right = x > 64 and y < 35 and (x < 73 or x > 91 or y < 8 or y > 26 or (79 <= x <= 85 and 14 <= y <= 20))
            bottom_left = x < 35 and y > 64 and (
                x < 8 or x > 26 or y < 73 or y > 91 or (14 <= x <= 20 and 79 <= y <= 85)
            )
            data = (x // 6 + y // 6) % 2 == 0
            raw.append(0 if (outer or top_left or top_right or bottom_left or data) else 255)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw)))
        + chunk(b"IEND", b"")
    )
    return base64.b64encode(png).decode("ascii")


# ---------------------------------------------------------------------------------------------------------------
# Velocity


_BLOCK_TAG = re.compile(r"#(?:if|foreach|macro)\b|#end\b")
_FOREACH = re.compile(r"#foreach\s*\(\s*\$(\w+)\s+in\s+\$([\w.]+)\s*\)")
_IF = re.compile(r"#if\s*\(([^)]+)\)")
_IF_TAG = re.compile(r"#(?:if|foreach)\b|#else\b|#end\b")
_CLAIM_VALUE = re.compile(r"#claimValue\s*\(\s*[\"']([^\"']+)[\"']\s*\)")


def check_template(template_text: str) -> None:
    """Raise ValueError unless every #if, #foreach and #macro has its #end."""
    depth = 0
    for tag in _BLOCK_TAG.finditer(_strip_comments(template_text)):
        depth += -1 if tag.group(0) == "#end" else 1
        if depth < 0:
            raise ValueError("template has an #end without an #if, #foreach or #macro")
    if depth:
        raise ValueError(f"template has {depth} #if, #foreach or #macro without an #end")


def render_velocity_template(template_text: str, context: dict[str, Any], claims: dict[str, Any]) -> str:
    """Render the Velocity subset Mimoto's templates use: #foreach over context lists (nested, with $x.field),
    #if/#else, $var and ${var}, then #claimValue("name") last, so claim data is never read as template syntax."""
    tmpl = _strip_macros(_strip_comments(template_text))
    tmpl = _render_blocks(tmpl, context)
    return _CLAIM_VALUE.sub(lambda m: html.escape(text(claims.get(m.group(1)))), tmpl)


def _strip_comments(text_: str) -> str:
    return re.sub(r"#\*.*?\*#", "", re.sub(r"##.*$", "", text_, flags=re.MULTILINE), flags=re.DOTALL)


def _strip_macros(text_: str) -> str:
    """Drop #macro(...) ... #end definitions; VC Lab implements #claimValue itself."""
    out, pos = [], 0
    for m in re.finditer(r"#macro\s*\([^)]*\)", text_):
        if m.start() < pos:
            continue  # inside a macro already dropped
        out.append(text_[pos:m.start()])
        pos = _find_block_end(text_, m.end())[1]
    out.append(text_[pos:])
    return "".join(out)


def _find_block_end(text_: str, body_start: int) -> tuple[int, int]:
    """(start, end) of the #end closing the block whose body starts at body_start."""
    depth = 1
    for tag in _BLOCK_TAG.finditer(text_, body_start):
        depth += -1 if tag.group(0) == "#end" else 1
        if depth == 0:
            return tag.start(), tag.end()
    raise ValueError("unbalanced #foreach/#if/#macro: missing #end")


def _render_blocks(text_: str, ctx: dict[str, Any]) -> str:
    """Expand #foreach over context lists, then #if blocks, then $variables."""
    out, pos = [], 0
    for m in _FOREACH.finditer(text_):
        if m.start() < pos:
            continue  # inside a loop body already expanded
        end_start, end_end = _find_block_end(text_, m.end())
        body = text_[m.end():end_start]
        out.append(text_[pos:m.start()])
        items = ctx.get(m.group(2))
        items = items if isinstance(items, list) else []
        out.extend(_render_blocks(body, _scope(ctx, m.group(1), item)) for item in items)
        pos = end_end
    out.append(text_[pos:])
    return _substitute(_render_if_blocks("".join(out), ctx), ctx)


def _scope(ctx: dict[str, Any], var: str, item: Any) -> dict[str, Any]:
    """The context for one loop pass: $var is the item and $var.key each field, nested objects flattened.
    Lists stay lists for nested loops; every other value is escaped, so data prints as written: HTML-escaped,
    and $ and # as entities, so neither the #if pass nor the $variable pass can read data as template code."""
    inner = dict(ctx)

    def put(name: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, field in value.items():
                put(f"{name}.{key}", field)
        elif (items := _as_list(value)) is not None:
            inner[name] = items
        else:
            inner[name] = _escape(text(value))

    put(var, item)
    return inner


_ENTITIES = str.maketrans(
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "#": "&#35;", "$": "&#36;"}
)


def _escape(value: str) -> str:
    return value.translate(_ENTITIES)  # one pass, so no entity is escaped again


def _substitute(text_: str, ctx: dict[str, Any]) -> str:
    """Replace $name and ${name} for every scalar in the context, in one pass (so a value is never re-read); the
    longest name wins, and a name must end where the reference does."""
    names = sorted((k for k, v in ctx.items() if isinstance(v, (str, int, float, bool))), key=len, reverse=True)
    if not names:
        return text_
    alternatives = "|".join(re.escape(n) for n in names)
    pattern = re.compile(rf"\$\{{({alternatives})\}}|\$({alternatives})(?![\w])")
    return pattern.sub(lambda m: text(ctx[m.group(1) or m.group(2)]), text_)


def _render_if_blocks(text_: str, ctx: dict[str, Any]) -> str:
    """Evaluate #if (...) ... #else ... #end blocks, nested ones included."""
    out, pos = [], 0
    while True:
        m = _IF.search(text_, pos)
        if not m:
            out.append(text_[pos:])
            return "".join(out)
        out.append(text_[pos:m.start()])
        depth, cursor, else_at, end_at = 1, m.end(), None, None
        while end_at is None:
            tag = _IF_TAG.search(text_, cursor)
            if tag is None:
                raise ValueError("unbalanced #if: missing #end")
            cursor = tag.end()
            if tag.group(0) == "#end":
                depth -= 1
                if depth == 0:
                    end_at = tag
            elif tag.group(0) == "#else":
                if depth == 1:
                    else_at = tag
            else:
                depth += 1
        if else_at is not None:
            true_body, false_body = text_[m.end():else_at.start()], text_[else_at.end():end_at.start()]
        else:
            true_body, false_body = text_[m.end():end_at.start()], ""
        chosen = true_body if _eval_condition(m.group(1), ctx) else false_body
        out.append(_render_if_blocks(chosen, ctx))
        pos = end_at.end()


def _eval_condition(cond: str, ctx: dict[str, Any]) -> bool:
    """$var, !$var, $var == "x" and $var != "x" (a number or a quoted string)."""
    cond = cond.strip()
    if cond.startswith("!$"):
        return not ctx.get(cond[2:].strip())
    if not cond.startswith("$"):
        return bool(cond)
    for op in ("!=", "=="):
        if op in cond:
            name, target = (part.strip() for part in cond[1:].split(op, 1))
            equal = text(ctx.get(name)) == target.strip("\"'")
            return equal if op == "==" else not equal
    return bool(ctx.get(cond[1:].strip()))
