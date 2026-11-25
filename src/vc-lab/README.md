# VC Lab

VC Lab previews a credential's HTML template from files you upload as the PDF the Wallet prints, with an HTML quick view beside it. It knows nothing about any organisation: it has no built-in template, data or branding, and it reads nothing from the repo's folders, so a deployed VC Lab behaves the same as a local one.

## The set

What each file is, and how a value travels from SIS to the page, is in [the template guide](../../docs/guides/vc-lab-templates.md). The set lives in the browser: the dashboard holds the files in page memory and sends all of them with every call. The server keeps nothing between calls, so two visitors never see each other's files, and no endpoint returns a set (a reload forgets it; the dashboard asks before leaving while a set is loaded):

| Slot | File | What VC Lab reads from it |
|---|---|---|
| `template` | the HTML (Velocity) render template | the whole file |
| `credential` | Certify's whole credential configuration file | its `vc_template` (the mapping) and `display`, as Certify and the Wallet read them |
| `sample` | the Adapter's response, exactly as the Adapter sends it | its `credentialSubject`, or the whole file when it has none |
| `background` (optional) | a PDF page, such as the organisation's pre-printed paper | page 1 |

Choosing a file replaces that slot only; choosing a zip from Download replaces the whole set. Each file is checked on every call: the background must be a PDF, the credential file JSON with a `vc_template` object (holding a `credentialSubject` object), the sample a JSON object, and the template's `#if`/`#foreach`/`#macro` must each have their `#end`. One request may carry at most 20 MB.

## From sample to page

VC Lab renders nothing itself. It sends the set to the renderer (`src/renderer`, at `RENDERER_URL`; ADR 0002), VC Lab's own copy of `ait-mimoto`'s print code and Certify's claim mapping:

1. The record is the sample's `credentialSubject`, or the whole sample.
2. The credential file's `vc_template` goes through template-sync's own transform (`build_vc_template_base64`, which unquotes `"courses": ${courses}`), so the renderer evaluates the text Certify stores.
3. The renderer maps the record to claims as Certify does, then evaluates the template with the variables `ait-mimoto` gives (`$credentialSubject`, `$rowProperties`, `$titleName`, `$qrCodeImage`, ...), and hands back that HTML (the quick view) or the PDF iText prints from it (what the Wallet prints). Both come from the same evaluation. The renderer's README lists the variables and where it differs from Certify and `ait-mimoto`.

## Dashboard and API

The dashboard (`/`) has a file input per slot (or one for a zip), the list of loaded files, the preview with a choice of the PDF ("what the Wallet prints") or the HTML ("quick view"), and Open PDF, Download, Remove background and Clear.

| Call | Does |
|---|---|
| `POST /preview` | the set as multipart (`template`, `credential`, `sample`, optional `background`); answers the quick view: the HTML the PDF is printed from, never with the background |
| `POST /preview.pdf` | the same set; answers what the Wallet prints: the renderer's PDF, with the background under page 1 when one is sent |
| `POST /download` | the same set; answers a zip with `template/`, `credential/`, `sample/` and `background/`, each file as sent |
| `POST /api/bundle` | multipart with one `bundle` (a zip from Download); answers its files as `{slot: {filename, data}}`, `data` in base64, for the dashboard to hold |
| `GET /health` | liveness |

Rendering needs the template, the credential file and the sample; without them both previews answer 409, naming what is missing. A wrong file answers 400 with the reason. A template Velocity can't evaluate, or a sample or mapping Certify would refuse, answers 422 with the renderer's message (a Velocity error names its line and column). Without `RENDERER_URL` the previews answer 503.

## The background (`hardcopy.py`)

`make_background(filename, data)` takes page 1 of an uploaded PDF, with its own `/Rotate` and crop box respected, and fits it on a portrait A4 page without redrawing it. `lay_background(pdf, background)` lays that page under page 1 of the renderer's PDF only, so later pages (the verification QR) print clean. This is VC Lab's own step, not the Wallet's: the Wallet draws a background only as the template's `$backgroundImage`.

> **A background may be confidential** (an organisation's watermark, seal and signature). It stays in your browser and goes to VC Lab only with each preview, which keeps nothing; another visitor can't get it back. But a deployed VC Lab has no login and is reached over whatever network its address crosses, so send a confidential one only to a VC Lab you trust.

## Issuing with a credential file from VC Lab

Download gives the credential file back as uploaded, the same shape as the files Certify's sync tool reads. Put it in a folder outside git and run the sync tool with that folder mounted; it replaces the stored version by its key:

```bash
docker compose run --rm -v <folder>:/app/config/credentials:ro template-sync
```

Not checked yet: whether Certify needs a restart to pick up the new version.

## Running

```bash
docker compose up -d vc-lab   # starts the renderer too; then open http://lab.localhost
```

Tests (script-style, the web API with a small made-up set). The preview tests need the renderer and skip without `RENDERER_URL`; the background tests also need WeasyPrint's system libraries to draw their paper. Inside Compose both are there:

```bash
docker compose run --rm vc-lab python src/vc-lab/test_main.py   # everything
.venv/bin/python src/vc-lab/test_main.py                       # on a host: the preview tests skip
```

## Layout

```
src/vc-lab/
├── main.py       # the web app: dashboard (which holds the set) and stateless API, rendering through the renderer
├── labset.py     # the set a request carries: its slots, parsing and validation, the zip
├── hardcopy.py   # the background page, laid under the renderer's PDF
└── test_main.py  # API tests
```
