"""VC Lab: render a credential template from uploaded files, and export its hard copy as a PDF.

VC Lab knows nothing about any organisation and reads nothing from the repo. The user uploads one set (the
template, Certify's credential file, the Adapter's sample response and an optional background PDF); VC Lab
holds it in memory only and forgets it on restart. /preview.pdf is the PDF the Wallet prints from the set, drawn
by the renderer (src/renderer), whose address comes from RENDERER_URL. See README.md.

Usage:
    python3 src/vc-lab/main.py
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

import hardcopy
import labset
import template_engine
from labset import MAX_UPLOAD, LabSet

app = FastAPI(title="VC Lab", description="Render a credential template from uploaded files", version="0.2.0")

# The one set, replaced whole on every change. Memory only, on purpose: see the README's note on backgrounds.
_lab = LabSet()

View = Literal["lab", "wallet"]

# The renderer: Mimoto 0.21's print path as a service (src/renderer). Compose sets it.
RENDERER_URL = os.environ.get("RENDERER_URL", "").rstrip("/")


class _InMemoryParser(MultiPartParser):
    """Starlette spools uploads over 1 MB to a temporary file; the request is capped at MAX_UPLOAD, so with this
    limit every uploaded file, a confidential background included, stays in memory."""

    spool_max_size = MAX_UPLOAD + 1


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP", "service": "vc-lab"}


@app.post("/api/set")
async def upload(request: Request) -> dict[str, Any]:
    """Multipart: any of template, credential, sample, background (each replaces its slot), or one bundle (a zip
    from /download, which replaces the whole set)."""
    global _lab
    files = await _read_files(request)
    try:
        if "bundle" in files:
            if len(files) > 1:
                raise ValueError("send a bundle on its own, without other files")
            new = labset.from_zip(files["bundle"][1])
        else:
            new = _lab.replace(files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _lab = new
    return _status()


@app.get("/api/set")
def get_set() -> dict[str, Any]:
    return _status()


@app.delete("/api/set")
def clear_set() -> dict[str, Any]:
    global _lab
    _lab = LabSet()
    return _status()


@app.delete("/api/set/background")
def remove_background() -> dict[str, Any]:
    global _lab
    _lab = dataclasses.replace(_lab, background=None)
    return _status()


@app.get("/preview", response_class=HTMLResponse)
def preview(view: View = Query("lab")) -> HTMLResponse:
    """The rendered template as HTML. Never with the background: the PDF is where the background shows."""
    return HTMLResponse(_render(_lab, view))


@app.get("/export.pdf")
def export_pdf(view: View = Query("lab")) -> Response:
    """The rendered template as a PDF, with the background under page 1 when one is loaded."""
    lab = _lab  # one set for the whole request, even if an upload replaces it meanwhile
    html = _render(lab, view)
    pdf = hardcopy.render_pdf(html, lab.background.value if lab.background else None)
    name = f"{Path(lab.template.filename).stem}-{view}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/preview.pdf")
def preview_pdf() -> Response:
    """The PDF the Wallet would print from the set, drawn by the renderer as Mimoto 0.21 draws it."""
    lab = _lab  # one set for the whole request, even if an upload replaces it meanwhile
    _require_complete(lab)
    if not RENDERER_URL:
        raise HTTPException(status_code=503, detail="VC Lab has no renderer: set RENDERER_URL (Compose sets it)")
    request = {
        "template": lab.template.value,
        "credentialSubject": template_engine.credential_subject(lab.credential.value, lab.sample.value),
        "credentialFile": lab.credential.value,
        "backgroundImage": None,
        "locale": "en",
    }
    try:
        res = httpx.post(f"{RENDERER_URL}/render", json=request, timeout=120)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"the renderer at {RENDERER_URL} can't be reached: {e}")
    if res.status_code == 422:  # the template didn't render: the renderer's message, with its line, is the answer
        raise HTTPException(status_code=422, detail=res.json()["error"])
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"the renderer answered {res.status_code}: {res.text}")
    name = f"{Path(lab.template.filename).stem}.pdf"
    return Response(res.content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@app.get("/download")
def download() -> Response:
    """The set as a zip (template/, credential/, sample/, background/), each file as uploaded."""
    headers = {"Content-Disposition": 'attachment; filename="vc-lab-set.zip"'}
    return Response(labset.to_zip(_lab), media_type="application/zip", headers=headers)


def _status() -> dict[str, Any]:
    return {"loaded": _lab.loaded(), "missing": _lab.missing()}


def _require_complete(lab: LabSet) -> None:
    if missing := lab.missing():
        raise HTTPException(status_code=409, detail=f"upload these first: {', '.join(missing)}")


def _render(lab: LabSet, view: View) -> str:
    _require_complete(lab)
    try:  # the old Velocity subset needs balanced blocks; uploads no longer check them
        template_engine.check_template(lab.template.value)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return template_engine.render_credential(
        lab.template.value, lab.credential.value, lab.sample.value, wallet=view == "wallet"
    )


async def _read_files(request: Request) -> dict[str, tuple[str, bytes]]:
    """The request's files as {field: (filename, data)}, read into memory and capped at MAX_UPLOAD."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_UPLOAD:
            raise HTTPException(status_code=400, detail=f"upload is larger than {MAX_UPLOAD // (1024 * 1024)} MB")

    async def whole() -> AsyncGenerator[bytes, None]:
        yield bytes(body)

    try:
        form = await _InMemoryParser(request.headers, whole()).parse()
    except (MultiPartException, KeyError) as e:
        raise HTTPException(status_code=400, detail=f"expected a multipart file upload: {e}")
    files: dict[str, tuple[str, bytes]] = {}
    for field, value in form.multi_items():
        if field not in (*labset.SLOTS, "bundle") or not isinstance(value, UploadFile):
            fields = ", ".join((*labset.SLOTS, "bundle"))
            raise HTTPException(status_code=400, detail=f"unexpected field {field!r}; send files as {fields}")
        if field in files:
            raise HTTPException(status_code=400, detail=f"more than one {field} file")
        files[field] = (value.filename or field, await value.read())
    if not files:
        raise HTTPException(status_code=400, detail="no file uploaded")
    return files


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(_DASHBOARD)


_DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>VC Lab</title>
  <style>
    :root { --primary: #005696; --bg: #f8fafc; --text: #1e293b; --muted: #64748b; --border: #e2e8f0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); margin: 0; }
    header { background: var(--primary); color: #fff; padding: 14px 24px; }
    header h1 { margin: 0; font-size: 19px; }
    main { display: grid; grid-template-columns: 380px 1fr; gap: 24px; max-width: 1400px; margin: 24px auto; padding: 0 24px; }
    .card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 18px; margin-bottom: 20px; }
    .card h2 { margin: 0 0 10px; font-size: 15px; color: var(--primary); }
    .slot { margin-top: 14px; }
    .slot b { font-size: 13px; }
    .ext { font-size: 12px; color: var(--muted); font-family: ui-monospace, monospace; }
    .hint { font-size: 12px; color: var(--muted); margin: 2px 0 6px; line-height: 1.4; }
    .pick { display: flex; align-items: center; gap: 10px; font-size: 13px; }
    .pick label { padding: 5px 10px; border: 1px solid var(--border); border-radius: 6px; background: #f1f5f9; cursor: pointer; white-space: nowrap; }
    .pick label:hover { background: #e2e8f0; }
    .file { word-break: break-all; }
    .file.none { color: var(--muted); font-style: italic; }
    .file.set { color: #047857; font-weight: 600; }
    .note { font-size: 13px; color: #1e3a8a; background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; }
    .note.strong { color: #92400e; background: #fffbeb; border-color: #fde68a; font-weight: 600; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    button { flex: 1; padding: 8px 10px; border: 0; border-radius: 6px; background: var(--primary); color: #fff; font-weight: 600; cursor: pointer; }
    button.quiet { background: var(--muted); }
    button:disabled { opacity: .45; cursor: default; }
    .warn { font-size: 12px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 8px; margin-top: 6px; }
    #error { font-size: 13px; color: #b91c1c; white-space: pre-wrap; }
    .viewer-head { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .views label { display: inline; margin: 0 0 0 12px; font-weight: 400; }
    iframe { width: 100%; height: 860px; border: 1px solid var(--border); border-radius: 6px; background: #fff; }
    #empty { color: var(--muted); font-size: 14px; padding: 40px 0; text-align: center; }
  </style>
</head>
<body>
  <header><h1>VC Lab</h1></header>
  <main>
    <div>
      <div class="card">
        <h2>The set</h2>
        <div class="slot">
          <b>Template</b> <span class="ext">.html (A4)</span>
          <div class="hint">The layout: HTML where the data is placed. Each <code>#claimValue("name")</code> is filled with
            that claim.</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="template" accept=".html,.htm,.vm,text/html"></label>
            <span class="file" data-slot="template"></span></div>
        </div>
        <div class="slot">
          <b>Credential file</b> <span class="ext">.json</span>
          <div class="hint">Certify's credential file. Its <code>vc_template</code> maps each claim to a field of the
            data (<code>"registrationNo": "${studentId}"</code>).</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="credential" accept=".json,application/json"></label>
            <span class="file" data-slot="credential"></span></div>
        </div>
        <div class="slot">
          <b>Data</b> <span class="ext">.json</span>
          <div class="hint">One record, as the Adapter sends it. It gives the values.</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="sample" accept=".json,application/json"></label>
            <span class="file" data-slot="sample"></span></div>
        </div>
        <div class="slot">
          <b>Background</b> <span class="ext">.pdf (A4)</span>
          <div class="hint">The pre-printed paper (watermark, seal, signature, image); page 1 is used. It shows only in
            Export PDF.</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="background" accept=".pdf,application/pdf"></label>
            <span class="file" data-slot="background"></span></div>
        </div>
        <div class="warn">A background may be confidential. VC Lab has no login: upload one only on your own machine.
          It is kept in memory and forgotten on restart.</div>
        <div class="slot">
          <b>Or a whole set</b> <span class="ext">.zip</span>
          <div class="hint">A zip from Download. It replaces all four files.</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="bundle" accept=".zip,application/zip"></label></div>
        </div>
        <div id="error"></div>
        <div class="row">
          <button id="exportPdf">Export PDF</button>
          <button id="download">Download</button>
        </div>
        <div class="row">
          <button class="quiet" id="removeBackground">Remove background</button>
          <button class="quiet" id="clear">Clear</button>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="viewer-head">
        <h2 style="margin:0">Preview: the PDF the Wallet prints</h2>
        <div class="views">
          <label><input type="radio" name="view" value="lab" checked> Lab</label>
          <label><input type="radio" name="view" value="wallet"> Wallet (as Mimoto prints it)</label>
        </div>
      </div>
      <div class="note" id="backgroundNote"></div>
      <div class="hint" id="viewHint"></div>
      <div id="empty"></div>
      <iframe id="preview" hidden></iframe>
    </div>
  </main>
  <script>
    const view = () => document.querySelector('input[name=view]:checked').value;
    const showError = (text) => { document.getElementById('error').textContent = text || ''; };

    const VIEW_HINTS = {
      lab: 'Lab and Wallet apply to Export PDF only (the old renderer). Lab: lists are drawn.',
      wallet: 'Lab and Wallet apply to Export PDF only (the old renderer). Wallet: lists come through empty.',
    };
    const NAMES = {template: 'template', credential: 'credential file', sample: 'data'};

    async function show(status) {
      for (const el of document.querySelectorAll('[data-slot]')) {
        const name = status.loaded[el.dataset.slot];
        el.textContent = name ? '\\u2713 ' + name : 'not loaded';
        el.className = 'file ' + (name ? 'set' : 'none');
      }
      const background = status.loaded.background;
      const note = document.getElementById('backgroundNote');
      note.className = 'note' + (background ? ' strong' : '');
      note.textContent = background
        ? 'Background loaded (' + background + '). It shows only in Export PDF; the preview draws background_image from the credential file.'
        : 'The preview draws background_image from the credential file, if it has one.';
      document.getElementById('viewHint').textContent = VIEW_HINTS[view()];
      const ready = status.missing.length === 0;
      document.getElementById('exportPdf').disabled = !ready;
      document.getElementById('removeBackground').disabled = !status.loaded.background;
      document.getElementById('empty').textContent = ready ? '' : 'Upload these to see the preview: ' + status.missing.map(s => NAMES[s]).join(', ') + '.';
      const frame = document.getElementById('preview');
      frame.hidden = !ready;
      if (ready) await showPreview(frame);
    }

    // The Wallet's print: the renderer's PDF, or its error (a template error names its line) in red.
    async function showPreview(frame) {
      const res = await fetch('/preview.pdf');
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        showError(typeof data.detail === 'string' ? data.detail : 'preview failed: HTTP ' + res.status);
        frame.hidden = true;
        return;
      }
      if (frame.dataset.url) URL.revokeObjectURL(frame.dataset.url);
      frame.dataset.url = URL.createObjectURL(await res.blob());
      frame.src = frame.dataset.url;
    }

    async function call(method, url, body) {
      const res = await fetch(url, {method, body});
      const data = await res.json();
      if (!res.ok) { showError(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)); return; }
      showError('');
      await show(data);
    }

    for (const input of document.querySelectorAll('input[type=file]')) {
      input.addEventListener('change', async () => {
        if (!input.files[0]) return;
        const form = new FormData();
        form.append(input.dataset.field, input.files[0]);
        await call('POST', '/api/set', form);
        input.value = '';
      });
    }
    for (const radio of document.querySelectorAll('input[name=view]')) {
      radio.addEventListener('change', () => call('GET', '/api/set'));
    }
    document.getElementById('exportPdf').onclick = () => window.open('/export.pdf?view=' + view(), '_blank');
    document.getElementById('download').onclick = () => { window.location = '/download'; };
    document.getElementById('removeBackground').onclick = () => call('DELETE', '/api/set/background');
    document.getElementById('clear').onclick = () => call('DELETE', '/api/set');
    call('GET', '/api/set');
  </script>
</body>
</html>"""


def main() -> None:
    import uvicorn

    port = int(os.environ.get("PORT", 4200))
    host = os.environ.get("HOST", "0.0.0.0")
    print(f"Starting VC Lab on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
