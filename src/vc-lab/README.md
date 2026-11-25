# VC Lab

VC Lab previews a credential's HTML template from files you upload as the PDF the Wallet prints, with an HTML quick view beside it. It knows nothing about any organisation: it has no built-in template, data or branding, and it reads nothing from the repo's folders, so a deployed VC Lab behaves the same as a local one.

## The set

What each file is, and how a value travels from SIS to the page, is in [the template guide](../../docs/guides/vc-lab-templates.md). The set lives in the browser: the dashboard holds the files in page memory and sends all of them with every call. The server keeps nothing between calls, so two visitors never see each other's files, and no endpoint returns a set (a reload forgets it; the dashboard asks before leaving while a set is loaded):

| Slot | File | What VC Lab reads from it |
|---|---|---|
| `template` | the HTML (Velocity) render template | the whole file |
| `credential` | Certify's whole credential configuration file | its `vc_template` (the mapping) and `display`, as Certify and the Wallet read them |
| `sample` | the Adapter's response, exactly as the Adapter sends it | its `credentialSubject`, or the whole file when it has none |
| `background` (optional) | the organisation's pre-printed paper, as the PNG the Wallet draws (`background.png`) | the whole picture, as the template's `$backgroundImage` |

Choosing a file replaces that slot only; choosing a zip from Download replaces the whole set. Each file is checked on every call: the background must be a PNG, the credential file JSON with a `vc_template` object (holding a `credentialSubject` object), the sample a JSON object, and the template's `#if`/`#foreach`/`#macro` must each have their `#end`. One request may carry at most 20 MB.

## From sample to page

VC Lab renders nothing itself. It sends the set to the renderer (`src/renderer`, at `RENDERER_URL`; ADR 0002), VC Lab's own copy of `ait-mimoto`'s print code and Certify's claim mapping:

1. The record is the sample's `credentialSubject`, or the whole sample.
2. The credential file's `vc_template` goes through template-sync's own transform (`build_vc_template_base64`, which unquotes `"courses": ${courses}`), so the renderer evaluates the text Certify stores.
3. The renderer maps the record to claims as Certify does, then evaluates the template with the variables `ait-mimoto` gives (`$credentialSubject`, `$rowProperties`, `$titleName`, `$qrCodeImage`, ...), and hands back that HTML (the quick view) or the PDF iText prints from it (what the Wallet prints). Both come from the same evaluation. The renderer's README lists the variables and where it differs from Certify and `ait-mimoto`.

## Dashboard and API

The dashboard (`/`) has a file input per slot (or one for a zip), the list of loaded files, the preview with a choice of the PDF ("what the Wallet prints") or the HTML ("quick view"), and Open PDF, Download, Remove background and Clear.

| Call | Does |
|---|---|
| `POST /preview` | the set as multipart (`template`, `credential`, `sample`, optional `background`, a PNG); answers the quick view: the HTML the PDF is printed from, with the Background drawn where the template asks for it |
| `POST /preview.pdf` | the same set; answers what the Wallet prints: the renderer's PDF |
| `POST /api/background` | a PDF, PNG or JPEG as the `background` field; answers the Background PNG (`image/png`), or 400 with the reason. The dashboard calls it when a file is chosen and keeps only the PNG |
| `POST /download` | the same set; answers a zip with `template/`, `credential/`, `sample/` and `background/`, each file as sent |
| `POST /api/bundle` | multipart with one `bundle` (a zip from Download); answers its files as `{slot: {filename, data}}`, `data` in base64, for the dashboard to hold |
| `GET /health` | liveness |

Rendering needs the template, the credential file and the sample; without them both previews answer 409, naming what is missing. A wrong file answers 400 with the reason. A template Velocity can't evaluate, or a sample or mapping Certify would refuse, answers 422 with the renderer's message (a Velocity error names its line and column). Without `RENDERER_URL` the previews answer 503.

## The Background (`background.py`)

The Wallet draws a Background only as the template's `$backgroundImage`, a PNG, so VC Lab keeps nothing else. `to_png(filename, data)` makes that PNG from what a staff member has:

- a PDF: page 1, drawn by `pypdfium2` at its own page size and 150 dpi, with its `/Rotate` and crop box respected;
- a PNG: kept as is;
- a JPEG: re-encoded to PNG at its own size.

Anything else, or a file that can't be read (a PDF with no pages is one), is refused with the reason. The dashboard sends the upload to `POST /api/background`, keeps the PNG it gets back, and sends that PNG as the `background` slot with every call. The renderer gets it as `backgroundImage` and draws `$backgroundImage`; the logo of the organisation is part of the picture, as the Wallet prints it.

The quick view draws it too. A template that loads it by its VDR address (`http://vdr.localhost/templates/<...>/background.png`) reaches the renderer's own copy in the PDF; a browser can't reach that address, so VC Lab replaces it in the quick view with the picture itself. Remove Background drops the slot, and the template previews on plain paper.

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

Tests (script-style, the web API with a small made-up set). The preview tests need the renderer and skip without `RENDERER_URL`; the background conversion tests need nothing. Inside Compose the renderer is there:

```bash
docker compose run --rm vc-lab python src/vc-lab/test_main.py   # everything
.venv/bin/python src/vc-lab/test_main.py                       # on a host: the preview tests skip
```

## Layout

```
src/vc-lab/
├── main.py       # the web app: dashboard (which holds the set) and stateless API, rendering through the renderer
├── labset.py     # the set a request carries: its slots, parsing and validation, the zip
├── background.py # the Background: a PDF, PNG or JPEG made into one PNG
└── test_main.py  # API tests
```
