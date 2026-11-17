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

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "vc-lab"))
sys.path.insert(0, str(REPO_ROOT / "mock" / "adapter"))

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


@app.get("/preview", response_class=HTMLResponse)
def preview_html(
    template: str = Query("AITUniversity-ait-transcript-template.html", description="Template file name"),
    student: str = Query("st120001", description="Student persona ID"),
    degree: Optional[str] = Query(None, description="Degree ID"),
) -> HTMLResponse:
    """Render and return the Velocity credential template directly as HTML."""
    target_path = None
    for d in [TEMPLATES_DIR, BASE_TEMPLATES_DIR]:
        candidate = d / template
        if candidate.exists():
            target_path = candidate
            break

    if not target_path or not target_path.exists():
        raise HTTPException(status_code=404, detail=f"Template {template} not found")

    try:
        claims = pt.load_student_claims(student_id=student, degree_id=degree, students_path=STUDENTS_FILE)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error loading student {student}: {e}")

    template_text = target_path.read_text(encoding="utf-8")
    context = {
        "titleName": "Asian Institute of Technology Credential",
        "logoUrl": pt.DEFAULT_LOGO,
        "qrCodeImage": pt.generate_mock_qr_png_base64(),
        "textColor": "#000000",
        "backgroundColor": "#FFFFFF",
        "credentialValidity": -1,
    }

    rendered = pt.render_velocity_template(template_text, context, claims)
    return HTMLResponse(content=rendered)


@app.post("/api/preview")
def api_preview(req: PreviewRequest) -> dict[str, str]:
    """Programmatic API to render a Velocity template with custom or student claims."""
    template_text = ""
    if req.template_content:
        template_text = req.template_content
    elif req.template_name:
        for d in [TEMPLATES_DIR, BASE_TEMPLATES_DIR]:
            candidate = d / req.template_name
            if candidate.exists():
                template_text = candidate.read_text(encoding="utf-8")
                break
        if not template_text:
            raise HTTPException(status_code=404, detail=f"Template {req.template_name} not found")
    else:
        # Default to transcript
        default_file = TEMPLATES_DIR / "AITUniversity-ait-transcript-template.html"
        if default_file.exists():
            template_text = default_file.read_text(encoding="utf-8")
        else:
            template_text = "<html><body><h1>$titleName</h1><p>#claimValue('fullName')</p></body></html>"

    claims = req.claims
    if not claims:
        claims = pt.load_student_claims(student_id=req.student_id or "st120001", students_path=STUDENTS_FILE)

    context = {
        "titleName": req.title,
        "logoUrl": req.logo_url,
        "qrCodeImage": pt.generate_mock_qr_png_base64(),
        "textColor": req.text_color,
        "backgroundColor": req.bg_color,
        "credentialValidity": -1,
    }

    rendered = pt.render_velocity_template(template_text, context, claims)
    return {"html": rendered}


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
          <div style="margin-top: 10px; font-size: 12px; color: #64748b;">
            💡 Evaluates Velocity `#claimValue`, `#if`, loops, and generates mock verification QR codes.
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
    function updatePreview() {{
      const template = document.getElementById('templateSelect').value;
      const student = document.getElementById('studentSelect').value;
      const url = `/preview?template=${{encodeURIComponent(template)}}&student=${{encodeURIComponent(student)}}`;
      document.getElementById('previewFrame').src = url;
      document.getElementById('openNewTab').href = url;
    }}
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

