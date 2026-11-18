"""In-memory Velocity template rendering engine for VC Lab.

Part of the vc-lab module.
Provides template parsing, macro stripping, condition evaluation, and mock asset
generation for live in-memory rendering in the VC Lab web studio and API.
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import struct
import sys
import zlib
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))
from ait_courses import enrich_ait_transcript_subject, parse_courses  # noqa: E402

STUDENTS_JSON = REPO_ROOT / "tests" / "fixtures" / "students.json"
VDR_BASE_URL = (os.environ.get("VDR_BASE_URL") or "http://vdr.localhost").rstrip("/")
DEFAULT_LOGO = f"{VDR_BASE_URL}/assets/AIT_globe.png"


def generate_mock_qr_png_base64() -> str:
    """Generate a clean 100x100 grayscale PNG resembling a QR code pattern in pure Python."""
    width = 100
    height = 100
    raw_data = bytearray()
    for y in range(height):
        raw_data.append(0)  # Filter type 0 (None)
        for x in range(width):
            # Outer border box
            is_outer_border = (x < 12 or x > 87 or y < 12 or y > 87)
            # Alignment corner boxes
            is_top_left = (x < 35 and y < 35 and (x < 8 or x > 26 or y < 8 or y > 26 or (14 <= x <= 20 and 14 <= y <= 20)))
            is_top_right = (x > 64 and y < 35 and (x < 73 or x > 91 or y < 8 or y > 26 or (79 <= x <= 85 and 14 <= y <= 20)))
            is_bottom_left = (x < 35 and y > 64 and (x < 8 or x > 26 or y < 73 or y > 91 or (14 <= x <= 20 and 79 <= y <= 85)))
            # Checkered data area
            is_data_pattern = ((x // 6 + y // 6) % 2 == 0)

            is_black = is_outer_border or is_top_left or is_top_right or is_bottom_left or is_data_pattern
            raw_data.append(0 if is_black else 255)

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    header = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    idat = zlib.compress(bytes(raw_data))
    png_bytes = header + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
    return base64.b64encode(png_bytes).decode("ascii")


def lab_context(claims: dict[str, Any], background_url: Optional[str] = None, **overrides: Any) -> dict[str, Any]:
    """The variables VC Lab hands a template: Mimoto's, plus $terms (the courses claim as a list, which Mimoto
    cannot pass) and $backgroundUrl (preview only; the PDF lays the background under the page instead)."""
    ctx: dict[str, Any] = {
        "titleName": "Asian Institute of Technology Credential",
        "logoUrl": DEFAULT_LOGO,
        "qrCodeImage": generate_mock_qr_png_base64(),
        "textColor": "#000000",
        "backgroundColor": "#FFFFFF",
        "credentialValidity": -1,
        **{k: v for k, v in overrides.items() if v is not None},
    }
    if claims.get("courses"):
        ctx["terms"] = parse_courses(claims["courses"])
    if background_url:
        ctx["backgroundUrl"] = background_url
    return ctx


def load_student_claims(
    student_id: str = "st120001",
    degree_id: Optional[str] = None,
    students_path: Path = STUDENTS_JSON,
) -> dict[str, Any]:
    """Load and enrich persona claims from students.json fixture."""
    data = json.loads(students_path.read_text(encoding="utf-8"))
    students = data.get("students", [])
    target = None
    for s in students:
        if s.get("id") == student_id:
            target = s
            break
    if not target:
        raise ValueError(f"Student persona {student_id!r} not found in {students_path}")

    degrees = target.get("degrees", [])
    if not degrees:
        raise ValueError(f"Student {student_id} has no degrees listed")

    selected_degree = None
    if degree_id:
        for d in degrees:
            if d.get("degreeId") == degree_id:
                selected_degree = d
                break
        if not selected_degree:
            raise ValueError(f"Degree {degree_id!r} not found for student {student_id}")
    else:
        selected_degree = degrees[0]

    subject: dict[str, Any] = {
        "fullName": target.get("fullName", ""),
        "dateOfBirth": target.get("dateOfBirth", ""),
        "country": target.get("country", ""),
        **selected_degree,
    }

    # Clean non-claim internal fields
    for k in ["degreeId", "level", "keycloakId", "eligibility"]:
        subject.pop(k, None)

    enriched = enrich_ait_transcript_subject(subject)
    return enriched


def strip_macros(text: str) -> str:
    """Strip Velocity #macro definitions and their nested content using a balanced scanner."""
    out = []
    i = 0
    tag_re = re.compile(r"#(?:macro|if|foreach)\b|#end\b")
    while i < len(text):
        m = re.search(r"#macro\s*\([^)]*\)", text[i:])
        if not m:
            out.append(text[i:])
            break
        macro_start = i + m.start()
        out.append(text[i:macro_start])
        curr = i + m.end()
        depth = 1
        while curr < len(text) and depth > 0:
            tm = tag_re.search(text, curr)
            if not tm:
                break
            tag = tm.group(0)
            if tag == "#end":
                depth -= 1
            else:
                depth += 1
            curr = tm.end()
        i = curr
    return "".join(out)


def render_if_blocks(text: str, ctx: dict[str, Any]) -> str:
    """Evaluate #if (...) ... #else ... #end blocks with support for nested tags."""
    out = []
    i = 0
    tag_re = re.compile(r"#(?:if|foreach)\b|#else\b|#end\b")
    while i < len(text):
        m = re.search(r"#if\s*\(([^)]+)\)", text[i:])
        if not m:
            out.append(text[i:])
            break

        if_start = i + m.start()
        out.append(text[i:if_start])

        cond_expr = m.group(1).strip()
        curr = i + m.end()
        depth = 1
        else_pos = None
        after_else = None

        while curr < len(text) and depth > 0:
            tm = tag_re.search(text, curr)
            if not tm:
                break
            tag = tm.group(0)
            if tag in ("#if", "#foreach"):
                depth += 1
                curr = tm.end()
            elif tag == "#end":
                depth -= 1
                if depth == 0:
                    end_pos = tm.start()
                    after_end = tm.end()
                else:
                    curr = tm.end()
            elif tag == "#else" and depth == 1:
                else_pos = tm.start()
                after_else = tm.end()
                curr = tm.end()
            else:
                curr = tm.end()

        if depth != 0:
            out.append(text[if_start:])
            break

        if else_pos is not None and after_else is not None:
            true_body = text[i + m.end() : else_pos]
            false_body = text[after_else:end_pos]
        else:
            true_body = text[i + m.end() : end_pos]
            false_body = ""

        is_true = eval_condition(cond_expr, ctx)
        chosen_body = true_body if is_true else false_body
        out.append(render_if_blocks(chosen_body, ctx))
        i = after_end

    return "".join(out)


def eval_condition(cond: str, ctx: dict[str, Any]) -> bool:
    """Evaluate a Velocity condition expression."""
    cond = cond.strip()
    if cond.startswith("!$"):
        var = cond[2:].strip()
        return not bool(ctx.get(var))
    elif cond.startswith("$"):
        var = cond[1:].strip()
        if "!=" in var:
            k, target = [x.strip() for x in var.split("!=", 1)]
            val = ctx.get(k, None)
            target = target.strip("\"'")
            if target == "-1":
                return str(val) != "-1" and val != -1
            return str(val) != target
        elif "==" in var:
            k, target = [x.strip() for x in var.split("==", 1)]
            val = ctx.get(k, None)
            target = target.strip("\"'")
            return str(val) == target
        else:
            return bool(ctx.get(var))
    return bool(cond)


_BLOCK_TAG = re.compile(r"#(?:if|foreach)\b|#end\b")
_FOREACH = re.compile(r"#foreach\s*\(\s*\$(\w+)\s+in\s+\$([\w.]+)\s*\)")


def _find_block_end(text: str, body_start: int) -> tuple[int, int]:
    """Return (start, end) of the #end closing the block whose body starts at body_start."""
    depth = 1
    for tm in _BLOCK_TAG.finditer(text, body_start):
        depth += -1 if tm.group(0) == "#end" else 1
        if depth == 0:
            return tm.start(), tm.end()
    raise ValueError("Unbalanced #foreach/#if: missing #end")


def _scope(ctx: dict[str, Any], var: str, item: Any) -> dict[str, Any]:
    """Context for one loop pass: $var is the item, $var.key each field (strings escaped, lists kept for nested loops)."""
    inner = dict(ctx)
    fields = item.items() if isinstance(item, dict) else [("", item)]
    for key, value in fields:
        name = f"{var}.{key}" if key else var
        inner[name] = value if isinstance(value, list) else html.escape(str(value))
    return inner


def _render_blocks(text: str, ctx: dict[str, Any]) -> str:
    """Expand #foreach over context lists, then #if blocks, then $variables (longest name first)."""
    out = []
    pos = 0
    for m in _FOREACH.finditer(text):
        if m.start() < pos:
            continue  # inside a loop body already expanded
        end_start, end_end = _find_block_end(text, m.end())
        body = text[m.end():end_start]
        items = ctx.get(m.group(2))
        out.append(text[pos:m.start()])
        out.extend(_render_blocks(body, _scope(ctx, m.group(1), it)) for it in (items or []))
        pos = end_end
    out.append(text[pos:])
    rendered = render_if_blocks("".join(out), ctx)
    for k in sorted(ctx, key=len, reverse=True):
        v = ctx[k]
        if isinstance(v, (str, int, float, bool)):
            rendered = rendered.replace(f"${{{k}}}", str(v)).replace(f"${k}", str(v))
    return rendered


def render_velocity_template(
    template_text: str,
    context: dict[str, Any],
    claims: dict[str, Any],
) -> str:
    """Render a Velocity template with claims and context dictionary in memory."""
    # 1. Strip comments
    tmpl = re.sub(r"##.*$", "", template_text, flags=re.MULTILINE)
    tmpl = re.sub(r"#\*.*?\*#", "", tmpl, flags=re.DOTALL)

    # 2. Strip macro definitions
    tmpl = strip_macros(tmpl)

    # 3. Handle generic card #foreach over rowProperties.entrySet()
    if "#foreach($entry in $rowProperties.entrySet())" in tmpl:
        card_blocks = []
        for k, v in claims.items():
            if v is not None and str(v).strip():
                card_blocks.append(
                    f'            <div style="margin-bottom: 10px; float: left; width: 450px;">\n'
                    f'                <div style="font-weight: bold; font-size: 16px; margin-bottom: 5px; word-wrap: break-word;">{html.escape(str(k))}</div>\n'
                    f'                <div style="font-size: 16px; word-wrap: break-word;">{html.escape(str(v))}</div>\n'
                    f"            </div>"
                )
        rendered_claims_html = "\n".join(card_blocks)

        # Replace balanced foreach block
        m_fe = re.search(r"#foreach\s*\(\$entry in \$rowProperties\.entrySet\(\)\)", tmpl)
        if m_fe:
            _, end_end = _find_block_end(tmpl, m_fe.end())
            tmpl = tmpl[:m_fe.start()] + rendered_claims_html + tmpl[end_end:]

    # 4. #foreach over context lists, #if / #else / #end, then $var / ${var}
    tmpl = _render_blocks(tmpl, context)

    # 5. #claimValue("key") last, so claim data is never read as template syntax
    def replace_claim_value(m: re.Match) -> str:
        val = claims.get(m.group(1))
        return "" if val is None else html.escape(str(val))

    return re.sub(r"#claimValue\s*\(\s*[\"']([^\"']+)[\"']\s*\)", replace_claim_value, tmpl)
