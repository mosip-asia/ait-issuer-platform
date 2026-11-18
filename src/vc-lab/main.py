"""VC Lab: Visual Credential Studio & Developer API Server.

Provides visual and programmatic tools for VC developers and operators to:
1. Define, inspect, and export versioned W3C JSON-LD schemas and Certify blueprints.
2. Author, preview, and test Apache Velocity HTML credential templates offline.
3. Model visual card presentations and Inji Verify render orders.

Usage:
    python3 src/vc-lab/main.py
    uvicorn main:app --host 0.0.0.0 --port 4200
"""

from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "vc-lab"))
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))

import hardcopy  # noqa: E402
import template_engine as pt  # noqa: E402

app = FastAPI(
    title="VC Lab Studio",
    description="Verifiable Credential Design, Authoring, and Preview Studio",
    version="0.1.0",
)

# Configuration from environment or defaults
default_creds = REPO_ROOT / "deploy" / "ait" / "certify" / "credentials"
if not default_creds.exists():
    default_creds = REPO_ROOT / "deploy" / "ait" / "credentials"
CREDENTIALS_DIR = Path(os.environ.get("CREDENTIALS_DIR", default_creds))
CONTEXTS_DIR = Path(os.environ.get("CONTEXTS_DIR", REPO_ROOT / "deploy" / "ait" / "vdr" / "contexts"))
ASSETS_DIR = Path(os.environ.get("ASSETS_DIR", REPO_ROOT / "deploy" / "ait" / "vdr" / "assets"))
TEMPLATES_DIR = Path(os.environ.get("TEMPLATES_DIR", REPO_ROOT / "deploy" / "ait" / "vdr" / "templates"))
BASE_TEMPLATES_DIR = Path(os.environ.get("BASE_TEMPLATES_DIR", REPO_ROOT / "deploy" / "base" / "vdr" / "templates"))
STUDENTS_FILE = Path(os.environ.get("STUDENTS_FILE", REPO_ROOT / "tests" / "fixtures" / "students.json"))
INSTALLATION = os.environ.get("INSTALLATION", "ait")
VDR_BASE_URL = (os.environ.get("VDR_BASE_URL") or "http://vdr.localhost").rstrip("/")
CDN_BASE_URL = (os.environ.get("CDN_BASE_URL") or VDR_BASE_URL).rstrip("/")
DEFAULT_TEMPLATE = "AITUniversity-ait-transcript-template.html"

# Uploaded backgrounds, by template name. Memory only, on purpose: a background (AIT's watermark, seal and
# signature) is confidential, so it is never written to the bind-mounted, git-tracked or VDR-served folders,
# and a restart forgets it. "Download template" is how a finished template and its background are kept.
BACKGROUNDS: dict[str, hardcopy.Background] = {}


class PreviewRequest(BaseModel):
    template_name: Optional[str] = None
    template_content: Optional[str] = None
    student_id: Optional[str] = "st120001"
    claims: Optional[dict[str, Any]] = None
    title: Optional[str] = "Asian Institute of Technology Credential"
    logo_url: Optional[str] = f"{VDR_BASE_URL}/assets/AIT_globe.png"
    text_color: Optional[str] = "#000000"
    bg_color: Optional[str] = "#FFFFFF"


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "UP",
        "service": "vc-lab",
        "installation": INSTALLATION,
    }


@app.get("/api/contexts")
def list_contexts() -> list[dict[str, Any]]:
    """List all versioned W3C JSON-LD contexts in contexts directory."""
    results = []
    if CONTEXTS_DIR.exists():
        for f in sorted(CONTEXTS_DIR.rglob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rel_path = f.relative_to(CONTEXTS_DIR).as_posix()
                results.append({
                    "path": rel_path,
                    "canonical_uri": f"{VDR_BASE_URL}/contexts/{rel_path}",
                    "content": data,
                })
            except Exception as e:
                results.append({"path": str(f), "error": str(e)})
    return results


@app.get("/api/credentials")
def list_credentials() -> list[dict[str, Any]]:
    """List all Inji Certify credential configurations."""
    results = []
    if CREDENTIALS_DIR.exists():
        for f in sorted(CREDENTIALS_DIR.glob("*.json")):
            try:
                content = f.read_text(encoding="utf-8")
                content = content.replace("${VDR_BASE_URL}", VDR_BASE_URL)
                content = content.replace("${CDN_BASE_URL}", CDN_BASE_URL)
                content = content.replace("http://vdr.localhost", VDR_BASE_URL)
                content = content.replace("http://cdn.localhost", CDN_BASE_URL)
                data = json.loads(content)
                results.append({
                    "filename": f.name,
                    "key_id": data.get("credential_config_key_id"),
                    "format": data.get("credential_format"),
                    "scope": data.get("scope"),
                    "signing_algo": data.get("signature_algo"),
                    "content": data,
                })
            except Exception as e:
                results.append({"filename": f.name, "error": str(e)})
    return results


@app.get("/api/assets")
def list_assets() -> list[dict[str, str]]:
    """List all brand assets in assets directory."""
    results = []
    if ASSETS_DIR.exists():
        for f in sorted(ASSETS_DIR.glob("*")):
            if f.is_file():
                results.append({
                    "filename": f.name,
                    "cdn_url": f"{CDN_BASE_URL}/assets/{f.name}",
                    "size_bytes": str(f.stat().st_size),
                })
    return results


@app.get("/api/personas")
def list_personas() -> list[dict[str, Any]]:
    """List available mock student personas for testing."""
    if not STUDENTS_FILE.exists():
        return []
    try:
        data = json.loads(STUDENTS_FILE.read_text(encoding="utf-8"))
        students = data.get("students", [])
        return [
            {
                "id": s.get("id"),
                "fullName": s.get("fullName"),
                "country": s.get("country"),
                "degrees": [d.get("degreeId") for d in s.get("degrees", [])],
            }
            for s in students
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/templates")
def list_templates() -> list[dict[str, str]]:
    """List available Velocity HTML templates."""
    templates = []
    # Installation specific templates
    if TEMPLATES_DIR.exists():
        for f in sorted(TEMPLATES_DIR.glob("*-template.html")):
            templates.append({
                "name": f.name,
                "scope": "installation",
                "path": str(f),
            })
    # Base templates
    if BASE_TEMPLATES_DIR.exists():
        for f in sorted(BASE_TEMPLATES_DIR.glob("*-template.html")):
            templates.append({
                "name": f.name,
                "scope": "base",
                "path": str(f),
            })
    return templates


def _template_text(name: str) -> str:
    """A template from the installation's templates, else the base ones; 404 if neither has it."""
    for d in [TEMPLATES_DIR, BASE_TEMPLATES_DIR]:
        candidate = d / name
        if candidate.is_file() and candidate.parent == d:
            return candidate.read_text(encoding="utf-8")
    raise HTTPException(status_code=404, detail=f"Template {name} not found")


def _student_claims(student: str, degree: Optional[str] = None) -> dict[str, Any]:
    try:
        return pt.load_student_claims(student_id=student, degree_id=degree, students_path=STUDENTS_FILE)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error loading student {student}: {e}")


def _background_url(template: str) -> Optional[str]:
    bg = BACKGROUNDS.get(template)
    if bg is None:
        return None
    # The rotation and size in the query make the browser fetch a changed background instead of its cached one.
    return f"/api/background/preview.jpg?template={quote(template)}&v={bg.rotation}-{len(bg.original)}"


@app.get("/preview", response_class=HTMLResponse)
def preview_html(
    template: str = Query(DEFAULT_TEMPLATE, description="Template file name"),
    student: str = Query("st120001", description="Student persona ID"),
    degree: Optional[str] = Query(None, description="Degree ID"),
) -> HTMLResponse:
    """Render the template as HTML, over the template's uploaded background when it has one."""
    claims = _student_claims(student, degree)
    context = pt.lab_context(claims, background_url=_background_url(template))
    return HTMLResponse(content=pt.render_velocity_template(_template_text(template), context, claims))


@app.get("/export.pdf")
def export_pdf(
    template: str = Query(DEFAULT_TEMPLATE, description="Template file name"),
    student: str = Query("st120001", description="Student persona ID"),
    degree: Optional[str] = Query(None, description="Degree ID"),
) -> Response:
    """Render the template to PDF with mock data; the uploaded background, if any, goes under page 1."""
    claims = _student_claims(student, degree)
    html = pt.render_velocity_template(_template_text(template), pt.lab_context(claims), claims)
    pdf = hardcopy.render_pdf(html, BACKGROUNDS.get(template))
    filename = f"{Path(template).stem}-{student}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.post("/api/background")
async def set_background(
    template: str = Form(DEFAULT_TEMPLATE),
    rotation: int = Form(0),
    file: Optional[UploadFile] = File(None),
) -> dict[str, Any]:
    """Upload a template's background (PDF, PNG or JPEG), or change the rotation of the one it has."""
    _template_text(template)
    if file is not None and file.filename:
        filename, data = file.filename, await file.read()
    elif template in BACKGROUNDS:
        filename, data = BACKGROUNDS[template].filename, BACKGROUNDS[template].original
    else:
        raise HTTPException(status_code=400, detail="No file uploaded and this template has no background yet")
    try:
        BACKGROUNDS[template] = hardcopy.make_background(filename, data, rotation)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"template": template, "filename": filename, "rotation": rotation}


@app.get("/api/background")
def get_background(template: str = Query(DEFAULT_TEMPLATE)) -> dict[str, Any]:
    bg = BACKGROUNDS.get(template)
    return {"template": template, "filename": bg.filename if bg else None, "rotation": bg.rotation if bg else 0}


@app.delete("/api/background")
def delete_background(template: str = Query(DEFAULT_TEMPLATE)) -> dict[str, str]:
    BACKGROUNDS.pop(template, None)
    return {"template": template}


@app.get("/api/background/preview.jpg")
def background_preview(template: str = Query(DEFAULT_TEMPLATE)) -> Response:
    bg = BACKGROUNDS.get(template)
    if bg is None:
        raise HTTPException(status_code=404, detail=f"Template {template} has no background")
    return Response(bg.preview_jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/download")
def download_template(template: str = Query(DEFAULT_TEMPLATE)) -> Response:
    """The finished template as a zip: the template file, plus its background as uploaded and its rotation."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(template, _template_text(template))
        bg = BACKGROUNDS.get(template)
        if bg is not None:
            z.writestr(f"background/{bg.filename}", bg.original)
            z.writestr("background/background.json", json.dumps({"file": bg.filename, "rotation": bg.rotation}, indent=2))
    headers = {"Content-Disposition": f'attachment; filename="{Path(template).stem}.zip"'}
    return Response(out.getvalue(), media_type="application/zip", headers=headers)


@app.post("/api/preview")
def api_preview(req: PreviewRequest) -> dict[str, str]:
    """Programmatic API to render a Velocity template with custom or student claims."""
    if req.template_content:
        template_text = req.template_content
    else:
        template_text = _template_text(req.template_name or DEFAULT_TEMPLATE)
    claims = req.claims or _student_claims(req.student_id or "st120001")
    context = pt.lab_context(
        claims, titleName=req.title, logoUrl=req.logo_url, textColor=req.text_color, backgroundColor=req.bg_color
    )
    return {"html": pt.render_velocity_template(template_text, context, claims)}


@app.get("/", response_class=HTMLResponse)
def studio_dashboard() -> HTMLResponse:
    """Interactive VC Lab Studio web dashboard."""
    templates = list_templates()
    personas = list_personas()
    contexts = list_contexts()
    credentials = list_credentials()
    assets = list_assets()

    templates_options = "".join(f'<option value="{t["name"]}">{t["name"]} ({t["scope"]})</option>' for t in templates)
    personas_options = "".join(f'<option value="{p["id"]}">{p["fullName"]} ({p["id"]})</option>' for p in personas)

    schemas_rows = "".join(
        f'<tr><td><code>{c.get("path")}</code></td><td><a href="{c.get("canonical_uri")}" target="_blank">{c.get("canonical_uri")}</a></td><td><span class="badge badge-schema">W3C JSON-LD</span></td></tr>'
        for c in contexts
    )
    creds_rows = "".join(
        f'<tr><td><b>{cr.get("filename")}</b></td><td><code>{cr.get("scope")}</code></td><td><code>{cr.get("format")}</code></td><td><code>{cr.get("signing_algo")}</code></td></tr>'
        for cr in credentials
    )
    assets_rows = "".join(
        f'<tr><td><b>{a.get("filename")}</b></td><td><code>{a.get("cdn_url")}</code></td><td>{a.get("size_bytes")} B</td></tr>'
        for a in assets
    )

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>VC Lab: Visual Credential Studio</title>
  <style>
    :root {{
      --primary: #005696;
      --primary-light: #e6f0f8;
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text: #1e293b;
      --border: #e2e8f0;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      margin: 0;
      padding: 0;
    }}
    header {{
      background: var(--primary);
      color: white;
      padding: 16px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }}
    header h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
    .badge {{
      background: rgba(255,255,255,0.2);
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
    }}
    .badge-schema {{ background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 4px; }}
    .container {{
      max-width: 1400px;
      margin: 24px auto;
      padding: 0 24px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 450px 1fr;
      gap: 24px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 24px;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .card h2 {{
      margin-top: 0;
      font-size: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
      color: var(--primary);
    }}
    label {{
      display: block;
      font-size: 13px;
      font-weight: 600;
      margin-top: 12px;
      margin-bottom: 4px;
    }}
    select, input, button {{
      width: 100%;
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 6px;
      font-size: 14px;
      box-sizing: border-box;
    }}
    button {{
      background: var(--primary);
      color: white;
      font-weight: 600;
      border: none;
      cursor: pointer;
      margin-top: 16px;
      transition: opacity 0.2s;
    }}
    button:hover {{ opacity: 0.9; }}
    iframe {{
      width: 100%;
      height: 780px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: white;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-top: 8px;
    }}
    th, td {{
      padding: 8px 12px;
      text-align: left;
      border-bottom: 1px solid var(--border);
    }}
    th {{ background: var(--primary-light); color: var(--primary); font-weight: 600; }}
  </style>
</head>
<body>
  <header>
    <h1>VC Lab Studio: Verifiable Credential Studio</h1>
    <div>
      <span class="badge">Tenant: {INSTALLATION}</span>
      <span class="badge" style="background:#10b981;">Online</span>
    </div>
  </header>

  <div class="container">
    <div class="grid">
      <!-- Controls Panel -->
      <div>
        <div class="card">
          <h2>1. Live Template Preview</h2>
          <label for="templateSelect">Template:</label>
          <select id="templateSelect">{templates_options}</select>

          <label for="studentSelect">Mock Persona / Student:</label>
          <select id="studentSelect">{personas_options}</select>

          <button onclick="updatePreview()">Render Live Preview</button>
          <div style="display:flex; gap:8px;">
            <button onclick="openWith('/export.pdf', true)">Export PDF</button>
            <button onclick="openWith('/download', false)">Download template</button>
          </div>
          <div style="margin-top: 10px; font-size: 12px; color: #64748b;">
            💡 Evaluates Velocity `#claimValue`, `#if`, `#foreach`, and generates mock verification QR codes.
          </div>
        </div>

        <div class="card">
          <h2>Background</h2>
          <div style="font-size: 12px; color: #b45309; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 8px;">
            ⚠️ A background such as AIT's watermark is confidential. Upload it only on a VC Lab running on your own machine,
            never on a deployed one. VC Lab keeps it in memory for the selected template, forgets it on restart, and never
            publishes it; "Download template" is how you keep it.
          </div>
          <label for="bgFile">PDF, PNG or JPEG (page 1 only, used as uploaded):</label>
          <input type="file" id="bgFile" accept="application/pdf,image/png,image/jpeg" />
          <label for="bgRotation">Rotation (clockwise):</label>
          <select id="bgRotation">
            <option value="0">0°</option><option value="90">90°</option><option value="180">180°</option><option value="270">270°</option>
          </select>
          <div id="bgStatus" style="margin-top: 8px; font-size: 12px; color: #64748b;">No background (the default).</div>
          <div style="display:flex; gap:8px;">
            <button onclick="saveBackground()">Apply</button>
            <button onclick="removeBackground()" style="background:#64748b;">Remove</button>
          </div>
        </div>

        <div class="card">
          <h2>2. Brand Assets (VDR)</h2>
          <table>
            <thead><tr><th>Asset</th><th>URI</th><th>Size</th></tr></thead>
            <tbody>{assets_rows}</tbody>
          </table>
        </div>

        <div class="card">
          <h2>3. Certify Blueprints</h2>
          <table>
            <thead><tr><th>File</th><th>Scope</th><th>Format</th><th>Algo</th></tr></thead>
            <tbody>{creds_rows}</tbody>
          </table>
        </div>
      </div>

      <!-- Live Viewer Panel -->
      <div>
        <div class="card">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
            <h2 style="margin:0; border:none; padding:0;">Interactive Credential Viewer</h2>
            <a id="openNewTab" href="/preview" target="_blank" style="font-size:13px; color:var(--primary); text-decoration:none;">Open in new tab ↗</a>
          </div>
          <iframe id="previewFrame" src="/preview?template=AITUniversity-ait-transcript-template.html&student=st120001"></iframe>
        </div>

        <div class="card">
          <h2>4. Versioned W3C Schemas (VDR)</h2>
          <table>
            <thead><tr><th>Context File</th><th>Canonical Production URI</th><th>Format</th></tr></thead>
            <tbody>{schemas_rows}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <script>
    const selected = () => ({{
      template: document.getElementById('templateSelect').value,
      student: document.getElementById('studentSelect').value,
    }});
    function updatePreview() {{
      const {{template, student}} = selected();
      const url = `/preview?template=${{encodeURIComponent(template)}}&student=${{encodeURIComponent(student)}}`;
      document.getElementById('previewFrame').src = url;
      document.getElementById('openNewTab').href = url;
    }}
    function openWith(path, withStudent) {{
      const {{template, student}} = selected();
      let url = `${{path}}?template=${{encodeURIComponent(template)}}`;
      if (withStudent) url += `&student=${{encodeURIComponent(student)}}`;
      window.open(url, '_blank');
    }}
    async function showBackground() {{
      const res = await fetch(`/api/background?template=${{encodeURIComponent(selected().template)}}`);
      const bg = await res.json();
      document.getElementById('bgStatus').textContent = bg.filename
        ? `Background: ${{bg.filename}}, turned ${{bg.rotation}}°.` : 'No background (the default).';
      document.getElementById('bgRotation').value = String(bg.rotation);
    }}
    async function saveBackground() {{
      const form = new FormData();
      form.append('template', selected().template);
      form.append('rotation', document.getElementById('bgRotation').value);
      const file = document.getElementById('bgFile').files[0];
      if (file) form.append('file', file);
      const res = await fetch('/api/background', {{method: 'POST', body: form}});
      if (!res.ok) {{ alert((await res.json()).detail); return; }}
      document.getElementById('bgFile').value = '';
      await showBackground();
      updatePreview();
    }}
    async function removeBackground() {{
      await fetch(`/api/background?template=${{encodeURIComponent(selected().template)}}`, {{method: 'DELETE'}});
      await showBackground();
      updatePreview();
    }}
    document.getElementById('templateSelect').addEventListener('change', () => {{ showBackground(); updatePreview(); }});
    showBackground();
  </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)


def main() -> None:
    import uvicorn
    port = int(os.environ.get("PORT", 4200))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting VC Lab Studio on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

