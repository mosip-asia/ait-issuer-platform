# VC Lab

VC Lab renders a credential's HTML template from files you upload and shows the PDF the Wallet prints from them. Its preview comes from the [renderer](../renderer/README.md), which runs Mimoto 0.21's print path; VC Lab gets its address from `RENDERER_URL`, which Compose sets. It knows nothing about any organisation: it has no built-in template, data or branding, and it reads nothing from the repo's folders, so a deployed VC Lab behaves the same as a local one.

## The set

What each file is, and how a value travels from SIS to the page, is in [the template guide](../../docs/guides/vc-lab-templates.md). VC Lab works on one set of files at a time, held in memory and forgotten on restart:

| Slot | File | What VC Lab reads from it |
|---|---|---|
| `template` | the HTML (Velocity) render template | the whole file |
| `credential` | Certify's whole credential configuration file | `vc_template.credentialSubject` (the mapping) and the first `display` entry |
| `sample` | the Adapter's response, exactly as the Adapter sends it | its `credentialSubject`, or the whole file when it has none |
| `background` (optional) | a PDF page, such as the organisation's pre-printed paper | page 1 |

Uploading a file replaces that slot only; uploading a zip from Download replaces the whole set. Each file is checked when it is uploaded: the background must be a PDF, the credential file JSON with a `vc_template` object (holding a `credentialSubject` object), the sample a JSON object, and the template's `#if`/`#foreach`/`#macro` must each have their `#end`. One request may carry at most 8 MB.

## From sample to page

1. The record is the sample's `credentialSubject`, or the whole sample.
2. The mapping is evaluated against the record. `${name}`, `$name` and dotted paths (`${thesis.title}`) read the record; a value that is exactly one reference passes a list or object through unchanged. Certify's own variables (`${_holderId}`, `${_issuer}`, any name starting with `_`) get placeholders. The result is the credential's claims, keyed by the mapping's left side.
3. The template sees Mimoto's variables (`titleName`, `logoUrl`, `backgroundColor`, `textColor` from the credential file's first `display` entry, a mock `qrCodeImage`, `credentialValidity`) plus every claim that holds a list, or text holding a JSON list, under its claim name, so `#foreach($t in $terms)` with `$t.field` and nested loops works.
4. `#claimValue("name")` reads the claims last, and loop values are escaped (`$` and `#` included), so data is never read as template code.

**Wallet view** renders the same way, but every list claim is `""` and no list reaches the template, as Mimoto 0.21 does. A template that loops over a list should keep an `#else` for the Wallet's copy.

## Dashboard and API

The dashboard (`/`) has a file input per slot (or one for a zip), the list of loaded files, the preview (the PDF from `/preview.pdf`, or its error in red), and Export PDF with a Lab/Wallet switch, Download, Remove background and Clear.

| Call | Does |
|---|---|
| `POST /api/set` | multipart; any of `template`, `credential`, `sample`, `background`, or one `bundle` (a zip from Download); answers what is loaded |
| `GET /api/set` | which slots are loaded, with their file names, and which required ones are missing |
| `DELETE /api/set` | clears the set |
| `DELETE /api/set/background` | removes the background only |
| `GET /preview.pdf` | the PDF the Wallet prints from the set, drawn by the renderer; a template that doesn't print answers 422 with the renderer's message (a Velocity error names its line) |
| `GET /preview?view=lab\|wallet` | the rendered HTML, never with the background |
| `GET /export.pdf?view=lab\|wallet` | the PDF, with the background under page 1 when one is loaded |
| `GET /download` | a zip with `template/`, `credential/`, `sample/` and `background/`, each file as uploaded |
| `GET /health` | liveness |

Rendering needs the template, the credential file and the sample; without them the previews and export answer 409, naming what is missing. `/preview.pdf` answers 503 without `RENDERER_URL` and 502 when the renderer can't be reached. A wrong file answers 400 with the reason.

## The hard copy (`hardcopy.py`)

`make_background(filename, data)` takes page 1 of an uploaded PDF, with its own `/Rotate` and crop box respected, and fits it on a portrait A4 page without redrawing it. `render_pdf(html, background=None)` renders the template through WeasyPrint and lays that page under page 1 only, so later pages (the verification QR) print clean. Without a background the PDF is the information alone, for printing on pre-printed paper. The Admin Portal's hard copy can use `render_pdf` the same way.

> **A background may be confidential** (an organisation's watermark, seal and signature). VC Lab keeps it in memory only, but has no login: anyone who can reach a deployed VC Lab can download it. Upload one only on a VC Lab running on your own machine.

## Issuing with a credential file from VC Lab

Download gives the credential file back as uploaded, the same shape as the files Certify's sync tool reads. Put it in a folder outside git and run the sync tool with that folder mounted; it replaces the stored version by its key:

```bash
docker compose run --rm -v <folder>:/app/config/credentials:ro template-sync
```

Not checked yet: whether Certify needs a restart to pick up the new version.

## Running

```bash
docker compose up -d vc-lab   # starts the renderer first; then open http://lab.localhost
python3 src/vc-lab/main.py    # or locally, on port 4200 (set RENDERER_URL for /preview.pdf)
```

Tests (script-style). The `/preview.pdf` tests need the renderer and the `/export.pdf` tests need WeasyPrint's system libraries, so they run in the `ait-vc` image through Compose and skip on a host:

```bash
docker compose build renderer vc-lab
docker compose run --rm vc-lab python src/vc-lab/test_main.py  # the web API, with small made-up sets
.venv/bin/python src/vc-lab/test_template_engine.py            # Velocity details
```

## Layout

```
src/vc-lab/
├── main.py                  # the web app: dashboard and API over the one set
├── labset.py                # the set: its slots, upload parsing and validation, the zip
├── template_engine.py       # pure: mapping, template context and the Velocity subset
├── hardcopy.py              # the background page and the PDF
├── test_main.py             # API tests
└── test_template_engine.py  # Velocity tests
```
