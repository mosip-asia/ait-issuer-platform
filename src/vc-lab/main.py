"""VC Lab: render a credential template from uploaded files, and export its hard copy as a PDF.

VC Lab knows nothing about any organisation and reads nothing from the repo. The user uploads one set (the
template, Certify's credential file, the Adapter's sample response and an optional background PDF); VC Lab
holds it in memory only and forgets it on restart. See README.md.

Usage:
    python3 src/vc-lab/main.py
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Any, AsyncGenerator, Literal

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


@app.get("/download")
def download() -> Response:
    """The set as a zip (template/, credential/, sample/, background/), each file as uploaded."""
    headers = {"Content-Disposition": 'attachment; filename="vc-lab-set.zip"'}
    return Response(labset.to_zip(_lab), media_type="application/zip", headers=headers)


def _status() -> dict[str, Any]:
    return {"loaded": _lab.loaded(), "missing": _lab.missing()}


def _render(lab: LabSet, view: View) -> str:
    if missing := lab.missing():
        raise HTTPException(status_code=409, detail=f"upload these first: {', '.join(missing)}")
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
    label { display: block; font-size: 13px; font-weight: 600; margin: 12px 0 4px; }
    .loaded { font-weight: 400; color: var(--muted); }
    input[type=file] { width: 100%; font-size: 13px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 14px; }
    button { flex: 1; padding: 8px 10px; border: 0; border-radius: 6px; background: var(--primary); color: #fff; font-weight: 600; cursor: pointer; }
    button.quiet { background: var(--muted); }
    button:disabled { opacity: .45; cursor: default; }
    .warn { font-size: 12px; color: #92400e; background: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 8px; margin-top: 6px; }
    #error { font-size: 13px; color: #b91c1c; white-space: pre-wrap; }
    .viewer-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
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
        <label>Template (HTML, Velocity) <span class="loaded" data-slot="template"></span></label>
        <input type="file" data-field="template" accept=".html,.htm,.vm,text/html">
        <label>Credential file (Certify JSON, with vc_template) <span class="loaded" data-slot="credential"></span></label>
        <input type="file" data-field="credential" accept=".json,application/json">
        <label>Sample (the Adapter's response, JSON) <span class="loaded" data-slot="sample"></span></label>
        <input type="file" data-field="sample" accept=".json,application/json">
        <label>Background (optional, PDF, page 1) <span class="loaded" data-slot="background"></span></label>
        <input type="file" data-field="background" accept=".pdf,application/pdf">
        <div class="warn">A background such as an organisation's watermark paper may be confidential. VC Lab has no
          login, so upload it only on a VC Lab running on your own machine. It is kept in memory and forgotten on restart.</div>
        <label>Or a whole set (a zip from Download)</label>
        <input type="file" data-field="bundle" accept=".zip,application/zip">
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
        <h2 style="margin:0">Preview <span class="loaded">(HTML, without the background; Export PDF shows it)</span></h2>
        <div class="views">
          <label><input type="radio" name="view" value="lab" checked> Lab</label>
          <label><input type="radio" name="view" value="wallet"> Wallet (as Mimoto prints it)</label>
        </div>
      </div>
      <div id="empty"></div>
      <iframe id="preview" hidden></iframe>
    </div>
  </main>
  <script>
    const view = () => document.querySelector('input[name=view]:checked').value;
    const showError = (text) => { document.getElementById('error').textContent = text || ''; };

    async function show(status) {
      for (const el of document.querySelectorAll('[data-slot]')) {
        const name = status.loaded[el.dataset.slot];
        el.textContent = name ? '· ' + name : '';
      }
      const ready = status.missing.length === 0;
      document.getElementById('exportPdf').disabled = !ready;
      document.getElementById('removeBackground').disabled = !status.loaded.background;
      document.getElementById('empty').textContent = ready ? '' : 'Upload these to see the preview: ' + status.missing.join(', ') + '.';
      const frame = document.getElementById('preview');
      frame.hidden = !ready;
      if (ready) frame.src = '/preview?view=' + view() + '&t=' + Date.now();
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
