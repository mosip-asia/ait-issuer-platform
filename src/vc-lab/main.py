"""VC Lab: preview a credential template as the PDF the Wallet prints, from uploaded files.

VC Lab knows nothing about any organisation and reads nothing from the repo. The user uploads one set (the
template, Certify's credential file, the Adapter's sample response and an optional Background PNG); the dashboard
holds it in the browser and sends it with every call, so the server keeps nothing. The renderer (src/renderer, at RENDERER_URL) maps the sample
as Certify does and prints it as ait-mimoto does. See README.md.

Usage (src/ on PYTHONPATH, as the image has it, for template-sync's vc_template transform):
    PYTHONPATH=src RENDERER_URL=http://localhost:8080 python3 src/vc-lab/main.py
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any, AsyncGenerator, Literal
from urllib.parse import quote

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

import background
import labset
import package
from certify_template_sync.sync import build_vc_template_base64
from labset import MAX_UPLOAD, LabSet

app = FastAPI(title="VC Lab", description="Render a credential template from uploaded files", version="0.3.0")

# The renderer, VC Lab's own copy of ait-mimoto's print code and Certify's mapping (src/renderer). Compose sets it.
RENDERER_URL = os.environ.get("RENDERER_URL", "").rstrip("/")


class _InMemoryParser(MultiPartParser):
    """Starlette spools uploads over 1 MB to a temporary file; the request is capped at MAX_UPLOAD, so with this
    limit every uploaded file, a confidential background included, stays in memory."""

    spool_max_size = MAX_UPLOAD + 1


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "UP", "service": "vc-lab"}


# The body is read on the event loop; everything after it (parsing, the renderer call, the PDF and zip work) blocks,
# so it runs in the threadpool, and one visitor's slow render never holds up another's request.


@app.post("/preview", response_class=HTMLResponse)
async def preview(request: Request) -> HTMLResponse:
    """The quick view: the HTML the renderer hands iText, with the Background drawn where the template asks for it."""
    files = await _read_files(request, labset.SLOTS)
    return await run_in_threadpool(_preview, files)


def _preview(files: dict[str, tuple[str, bytes]]) -> HTMLResponse:
    lab = _parse_set(files)
    page = _render(lab, "html").decode("utf-8")
    if lab.background:
        # A browser can't reach the VDR address the Wallet loads the Background from, so it gets the picture itself.
        page = _VDR_BACKGROUND.sub(lambda _: _data_uri(lab.background.value), page)
    return HTMLResponse(page)


# Where a template loads the Background from, once an organisation has put it on its VDR (the renderer serves the same
# addresses to the PDF).
_VDR_BACKGROUND = re.compile(r"http://vdr\.localhost/templates/[^\s\"'()<>]*/background\.png")


def _data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


@app.post("/preview.pdf")
async def preview_pdf(request: Request) -> Response:
    """What the Wallet prints: the renderer's PDF."""
    files = await _read_files(request, labset.SLOTS)
    return await run_in_threadpool(_preview_pdf, files)


def _preview_pdf(files: dict[str, tuple[str, bytes]]) -> Response:
    lab = _parse_set(files)
    pdf = _render(lab, "pdf")
    # RFC 6266: filename* carries a name in any script (a Thai template name); filename is its ASCII stand-in.
    name = f"{Path(lab.template.filename).stem}.pdf"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_")
    disposition = f"inline; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": disposition})


@app.post("/api/package/export")
async def export_package(request: Request) -> Response:
    """Export Package: the set (as for a preview) plus config_id, version and vdr_address; answers the Package zip."""
    files, params = await _read_form(request, labset.SLOTS, PACKAGE_PARAMS)
    return await run_in_threadpool(_export_package, files, params)


PACKAGE_PARAMS = ("config_id", "version", "vdr_address")


def _export_package(files: dict[str, tuple[str, bytes]], params: dict[str, str]) -> Response:
    lab = _parse_set(files)
    if missing := lab.missing():
        raise HTTPException(status_code=409, detail=f"upload these first: {', '.join(missing)}")
    try:
        zipped = package.export(lab, *(params.get(name, "") for name in PACKAGE_PARAMS))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    name = f"{params['config_id'].strip()}-{params['version'].strip()}-package.zip"
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace("?", "_").replace('"', "")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(zipped, media_type="application/zip", headers={"Content-Disposition": disposition})


@app.post("/api/background")
async def make_background(request: Request) -> Response:
    """An uploaded PDF, PNG or JPEG in (as the background field), the Background PNG out: what the dashboard holds."""
    files = await _read_files(request, ("background",))
    return await run_in_threadpool(_make_background, files)


def _make_background(files: dict[str, tuple[str, bytes]]) -> Response:
    name, data = files["background"]
    try:
        return Response(background.to_png(labset.safe_filename(name, "background"), data), media_type="image/png")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/package/read")
async def read_package(request: Request) -> dict[str, Any]:
    """A Package zip in (as the package field); the set it holds out ({set: {slot: {filename, data}}}, data in
    base64, for the dashboard to hold) with the export it was made for ({export: {configId, version, vdrAddress}})."""
    files, _ = await _read_form(request, ("package",))
    return await run_in_threadpool(_read_package, files)


def _read_package(files: dict[str, tuple[str, bytes]]) -> dict[str, Any]:
    try:
        unpacked, export = package.read(files["package"][1])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"set": {slot: {"filename": name, "data": base64.b64encode(data).decode("ascii")}
                    for slot, (name, data) in unpacked.items()},
            "export": export}


def _parse_set(files: dict[str, tuple[str, bytes]]) -> LabSet:
    """The set a request carries, each file checked. The server keeps nothing of it."""
    try:
        return LabSet.from_files(files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

def _render(lab: LabSet, output: Literal["html", "pdf"]) -> bytes:
    """The renderer's one evaluation of the set: the HTML it hands iText, or the PDF iText makes of it.
    Its 400 (a request it can't read) and 422 (a template or mapping that fails) reach the caller with its message."""
    if missing := lab.missing():
        raise HTTPException(status_code=409, detail=f"upload these first: {', '.join(missing)}")
    if not RENDERER_URL:
        raise HTTPException(status_code=503, detail="VC Lab has no renderer: set RENDERER_URL (Compose sets it)")
    request = {
        "template": lab.template.value,
        # The Adapter's answer as uploaded, so the renderer reads it as the plugin does (strict JSON). An answer with
        # a credentialSubject object is read as that object.
        "record": lab.sample.data.decode("utf-8-sig"),
        # The vc_template through template-sync's own transform: the text Certify stores and evaluates.
        "vcTemplate": base64.b64decode(build_vc_template_base64(lab.credential.value["vc_template"])).decode("utf-8"),
        "credentialFile": lab.credential.value,
        # $backgroundImage is the Background as a data URI, and empty without one. Never null: the renderer would fall
        # back to the credential file's background_image address, which it refuses to load.
        "backgroundImage": _data_uri(lab.background.value) if lab.background else "",
        "locale": "en",
        "output": output,
    }
    try:
        res = httpx.post(f"{RENDERER_URL}/render", json=request, timeout=120)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"the renderer at {RENDERER_URL} can't be reached: {e}")
    if res.status_code in (400, 422):
        raise HTTPException(status_code=res.status_code, detail=res.json()["error"])
    if res.status_code != 200:
        raise HTTPException(status_code=502, detail=f"the renderer answered {res.status_code}: {res.text}")
    return res.content


async def _read_files(request: Request, fields: tuple[str, ...]) -> dict[str, tuple[str, bytes]]:
    """The request's files as {field: (filename, data)}, read into memory and capped at MAX_UPLOAD."""
    return (await _read_form(request, fields))[0]


async def _read_form(request: Request, fields: tuple[str, ...], params: tuple[str, ...] = ()
                     ) -> tuple[dict[str, tuple[str, bytes]], dict[str, str]]:
    """The request's files as {field: (filename, data)} and its text fields named in params, read into memory and
    capped at MAX_UPLOAD."""
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
    values: dict[str, str] = {}
    for field, value in form.multi_items():
        if field in params and not isinstance(value, UploadFile):
            values[field] = value
        elif field not in fields or not isinstance(value, UploadFile):
            raise HTTPException(status_code=400,
                                detail=f"unexpected field {field!r}; send files as {', '.join(fields)}")
        elif field in files:
            raise HTTPException(status_code=400, detail=f"more than one {field} file")
        else:
            files[field] = (value.filename or field, await value.read())
    if not files:
        raise HTTPException(status_code=400, detail="no file uploaded")
    return files, values


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
    .exportform { display: grid; gap: 6px; margin-top: 10px; font-size: 12px; color: var(--muted); }
    .exportform input { width: 100%; box-sizing: border-box; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
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
          <div class="hint">The layout: HTML with Velocity, given what <code>ait-mimoto</code> gives it
            (<code>$rowProperties</code>, <code>$credentialSubject</code>, <code>$titleName</code>, ...).</div>
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
          <b>Background</b> <span class="ext">.pdf, .png or .jpg</span>
          <div class="hint">The pre-printed paper (watermark, seal, signature, logo) as the Wallet draws it: one
            picture, kept here as a PNG for the template's <code>$backgroundImage</code>. A PDF's page 1 is drawn at
            its own size, 150 dpi.</div>
          <div class="pick"><label>Choose file<input type="file" hidden data-field="background" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg"></label>
            <span class="file" data-slot="background"></span></div>
        </div>
        <div class="warn">A background may be confidential. Your files stay in this page and go to the server only with
          each call, which keeps nothing; another visitor can't get them back. VC Lab has no login and is reached over
          whatever network its address crosses, so send a confidential one only to a VC Lab you trust. Reloading the
          page forgets your files.</div>
        <div class="slot">
          <b>Package</b> <span class="ext">.zip</span>
          <div class="hint">The files as they go onto the VDR and into Certify. Load one to get its set back
            (it replaces all four files); export one when the set is ready. The sample goes in it, marked as not for
            deployment.</div>
          <div class="pick"><label>Load Package<input type="file" hidden data-field="package" accept=".zip,application/zip"></label></div>
          <div class="exportform">
            <label>Credential configuration id <input id="configId" placeholder="ait-transcript"></label>
            <label>Version <input id="version" placeholder="v1"></label>
            <label>VDR address <input id="vdrAddress" placeholder="https://vdr.example.org"></label>
          </div>
        </div>
        <div id="error"></div>
        <div class="row">
          <button id="exportPdf">Open PDF</button>
          <button id="exportPackage">Export Package</button>
        </div>
        <div class="row">
          <button class="quiet" id="removeBackground">Remove background</button>
          <button class="quiet" id="clear">Clear</button>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="viewer-head">
        <h2 style="margin:0">Preview</h2>
        <div class="views">
          <label><input type="radio" name="output" value="/preview.pdf" checked> PDF: what the Wallet prints</label>
          <label><input type="radio" name="output" value="/preview"> HTML: quick view</label>
        </div>
      </div>
      <div class="note" id="backgroundNote"></div>
      <div class="hint" id="viewHint"></div>
      <div id="empty"></div>
      <iframe id="preview" hidden></iframe>
    </div>
  </main>
  <script>
    // The set lives here, in this page's memory: {slot: File}. Every call carries all of it; the server keeps none.
    // A reload loses it, so leaving asks first while any file is loaded.
    let set = {};
    let seen = 0;        // the latest preview asked for; an older answer that arrives late is dropped
    let shownUrl = null; // the blob the preview frame shows
    const output = () => document.querySelector('input[name=output]:checked').value;
    const showError = (text) => { document.getElementById('error').textContent = text || ''; };
    const missing = () => ['template', 'credential', 'sample'].filter(slot => !set[slot]);
    const form = () => { const f = new FormData(); for (const [slot, file] of Object.entries(set)) f.append(slot, file, file.name); return f; };

    const OUTPUT_HINTS = {
      '/preview.pdf': 'The PDF the Wallet prints: the sample mapped as Certify maps it, printed as ait-mimoto prints it.',
      '/preview': 'A quick view: the same HTML the PDF is printed from, laid out by your browser. Trust the PDF.',
    };
    const NAMES = {template: 'template', credential: 'credential file', sample: 'data'};

    window.addEventListener('beforeunload', (event) => {
      if (Object.keys(set).length) { event.preventDefault(); event.returnValue = ''; }
    });

    async function post(url) {
      const res = await fetch(url, {method: 'POST', body: form()});
      if (res.ok) return res;
      const data = await res.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || res.statusText));
    }

    async function show() {
      for (const el of document.querySelectorAll('[data-slot]')) {
        const file = set[el.dataset.slot];
        el.textContent = file ? '✓ ' + file.name : 'not loaded';
        el.className = 'file ' + (file ? 'set' : 'none');
      }
      const note = document.getElementById('backgroundNote');
      note.className = 'note' + (set.background ? ' strong' : '');
      note.textContent = set.background
        ? 'Background loaded (' + set.background.name + '). A template that draws it shows it in the PDF and the quick view.'
        : 'No Background: the template previews on plain paper.';
      document.getElementById('viewHint').textContent = OUTPUT_HINTS[output()];
      const need = missing();
      document.getElementById('exportPdf').disabled = need.length > 0;
      document.getElementById('exportPackage').disabled = need.length > 0;
      document.getElementById('removeBackground').disabled = !set.background;
      document.getElementById('empty').textContent = need.length ? 'Upload these to see the preview: ' + need.map(s => NAMES[s]).join(', ') + '.' : '';
      const frame = document.getElementById('preview');
      frame.hidden = need.length > 0;
      const mine = ++seen; // even when incomplete, so a preview still in flight is dropped when it lands
      if (need.length) return;
      try {
        const blob = await (await post(output())).blob();
        if (mine !== seen) return;
        showError('');
        if (shownUrl) URL.revokeObjectURL(shownUrl);
        shownUrl = URL.createObjectURL(blob);
        frame.src = shownUrl;
      } catch (e) {
        if (mine !== seen) return;
        showError(e.message);
        frame.hidden = true; // never leave the previous set's preview under the error
        frame.removeAttribute('src');
        if (shownUrl) URL.revokeObjectURL(shownUrl);
        shownUrl = null;
      }
    }

    for (const input of document.querySelectorAll('input[type=file]')) {
      input.addEventListener('change', async () => {
        const file = input.files[0];
        input.value = '';
        if (!file) return;
        if (input.dataset.field === 'package') {
          try {
            const res = await fetch('/api/package/read', {method: 'POST', body: (() => { const f = new FormData(); f.append('package', file); return f; })()});
            const data = await res.json();
            if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
            set = {};
            document.getElementById('configId').value = data.export.configId;
            document.getElementById('version').value = data.export.version;
            document.getElementById('vdrAddress').value = data.export.vdrAddress;
            for (const [slot, f] of Object.entries(data.set)) {
              const bytes = Uint8Array.from(atob(f.data), c => c.charCodeAt(0));
              set[slot] = new File([bytes], f.filename);
            }
          } catch (e) { showError(e.message); return; }
        } else if (input.dataset.field === 'background') {
          try { // the server makes the PNG; this page keeps only that
            const f = new FormData(); f.append('background', file, file.name);
            const res = await fetch('/api/background', {method: 'POST', body: f});
            if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : res.statusText); }
            set.background = new File([await res.blob()], 'background.png', {type: 'image/png'});
          } catch (e) { showError(e.message); return; }
        } else {
          set[input.dataset.field] = file;
        }
        showError('');
        await show();
      });
    }
    for (const radio of document.querySelectorAll('input[name=output]')) radio.addEventListener('change', show);
    document.getElementById('exportPdf').onclick = async () => {
      const tab = window.open('', '_blank'); // opened now, while the click still counts, filled when the PDF is back
      try {
        const blob = await (await post('/preview.pdf')).blob();
        tab.location = URL.createObjectURL(blob);
      } catch (e) { tab.close(); showError(e.message); }
    };
    document.getElementById('exportPackage').onclick = async () => {
      try {
        const f = form();
        for (const [name, id] of [['config_id', 'configId'], ['version', 'version'], ['vdr_address', 'vdrAddress']])
          f.append(name, document.getElementById(id).value);
        const res = await fetch('/api/package/export', {method: 'POST', body: f});
        if (!res.ok) { const data = await res.json().catch(() => ({})); throw new Error(typeof data.detail === 'string' ? data.detail : res.statusText); }
        const link = document.createElement('a');
        link.href = URL.createObjectURL(await res.blob());
        link.download = document.getElementById('configId').value.trim() + '-' + document.getElementById('version').value.trim() + '-package.zip';
        link.click();
        URL.revokeObjectURL(link.href);
      } catch (e) { showError(e.message); }
    };
    document.getElementById('removeBackground').onclick = () => { delete set.background; show(); };
    document.getElementById('clear').onclick = () => { set = {}; showError(''); show(); };
    show();
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
