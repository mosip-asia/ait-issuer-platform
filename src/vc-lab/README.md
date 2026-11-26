# VC Lab

VC Lab previews a credential's HTML template from files you upload as the PDF the Wallet prints, with an HTML quick view beside it. It knows nothing about any organisation: it has no built-in template, data or branding, and it reads nothing from the repo's folders, so a deployed VC Lab behaves the same as a local one.

## The set

What each file is, and how a value travels from SIS to the page, is in [the template guide](../../docs/guides/vc-lab-templates.md). The set lives in the browser: the dashboard holds the files in page memory and sends all of them with every call. The server keeps nothing between calls, so two visitors never see each other's files, and no endpoint returns a set (a reload forgets it; the dashboard asks before leaving while a set is loaded):

| Slot | File | What VC Lab reads from it |
|---|---|---|
| `template` | the HTML (Velocity) render template | the whole file |
| `credential` | Certify's whole credential configuration file | its `vc_template` (the mapping) and `display`, as Certify and the Wallet read them |
| `sample` | the Adapter's response, exactly as the Adapter sends it: the flat record | the whole file; one with a `credentialSubject` is a credential, refused with 422 as the plugin refuses it |
| `background` (optional) | the organisation's pre-printed paper, as the PNG the Wallet draws (`background.png`) | the whole picture, as the template's `$backgroundImage` |

Choosing a file replaces that slot only; loading a Package replaces the whole set. Each file is checked on every call: the background must be a PNG, the credential file JSON with a `vc_template` object (holding a `credentialSubject` object), the sample a JSON object, and the template UTF-8 text. VC Lab checks nothing inside a template: Velocity does, in the renderer (an unbalanced `#if` answers 422 with its line and column). One request may carry at most 20 MB.

## From sample to page

VC Lab renders nothing itself. It sends the set to the renderer (`src/renderer`, at `RENDERER_URL`; ADR 0002), VC Lab's own copy of `ait-mimoto`'s print code and Certify's claim mapping:

1. The record is the whole sample, as the Adapter sends it.
2. The credential file's `vc_template` goes through template-sync's own transform (`build_vc_template_base64`, which unquotes `"courses": ${courses}`), so the renderer evaluates the text Certify stores.
3. The renderer maps the record to claims as Certify does, then evaluates the template with the variables `ait-mimoto` gives (`$credentialSubject`, `$rowProperties`, `$titleName`, `$qrCodeImage`, ...), and hands back that HTML (the quick view) or the PDF iText prints from it (what the Wallet prints). Both come from the same evaluation. The renderer's README lists the variables and where it differs from Certify and `ait-mimoto`.

## Dashboard and API

The dashboard (`/`) has a file input per slot plus Load Package, the list of loaded files, the preview with a choice of the PDF ("what the Wallet prints") or the HTML ("quick view"), the three fields Export Package asks for (credential configuration id, version, VDR address) and Open PDF, Export Package, Remove background and Clear. Loading a Package fills the three fields from its manifest.

| Call | Does |
|---|---|
| `POST /preview` | the set as multipart (`template`, `credential`, `sample`, optional `background`, a PNG); answers the quick view: the HTML the PDF is printed from. The Background is drawn only through the template's `$backgroundImage` |
| `POST /preview.pdf` | the same set; answers what the Wallet prints: the renderer's PDF |
| `POST /api/background` | a PDF, PNG or JPEG as the `background` field; answers the Background PNG (`image/png`), or 400 with the reason. The dashboard calls it when a file is chosen and keeps only the PNG |
| `POST /api/package/export` | the same set, plus the text fields `config_id`, `version` and `vdr_address`; answers the Package zip ([The Package](#the-package)). 409 names what the set lacks, 400 a missing field or an address that is no URL |
| `POST /api/package/read` | multipart with one `package` (a zip from Export Package); answers `{set: {slot: {filename, data}}, export: {configId, version, vdrAddress}}`, `data` in base64, for the dashboard to hold. 400 for anything but the exported layout |
| `GET /health` | liveness |

Rendering needs the template, the credential file and the sample; without them both previews answer 409, naming what is missing. A wrong file answers 400 with the reason. A template Velocity can't evaluate, or a sample or mapping Certify would refuse, answers 422 with the renderer's message (a Velocity error names its line and column). Without `RENDERER_URL` the previews answer 503.

## The Background (`background.py`)

The Wallet draws a Background only as the template's `$backgroundImage`, a PNG, so VC Lab keeps nothing else. `to_png(filename, data)` makes that PNG from what a staff member has:

- a PDF: page 1, drawn by `pypdfium2` at its own page size and 150 dpi, with its `/Rotate` and crop box respected;
- a PNG: kept as is;
- a JPEG: re-encoded to PNG at its own size.

Anything else, or a file that can't be read (a PDF with no pages is one), is refused with the reason. The dashboard sends the upload to `POST /api/background`, keeps the PNG it gets back, and sends that PNG as the `background` slot with every call. The renderer gets it as `backgroundImage` and draws `$backgroundImage`; the logo of the organisation is part of the picture, as the Wallet prints it.

The quick view draws it too, as the same data URI. A template draws the Background only with `$backgroundImage`, which the Wallet fills from the credential file's `display[0].background_image.uri`; one that loads it by its VDR address (`http://vdr.localhost/templates/<...>/background.png`) answers 422 naming it, like any other address. Remove Background drops the slot, and the template previews on plain paper.

> **A background may be confidential** (an organisation's watermark, seal and signature). It stays in your browser and goes to VC Lab only with each preview, which keeps nothing; another visitor can't get it back. But a deployed VC Lab has no login and is reached over whatever network its address crosses, so send a confidential one only to a VC Lab you trust.

## The Package

Export Package turns the set into the files the VDR and Certify take, for one credential configuration id and version. It is also your save file: Load Package gives the set back. A Package is not tied to one Installation (ADR 0003): its files keep the local stack's addresses, `http://vdr.localhost` and `http://cdn.localhost`, and template-sync makes the credential file the Installation's (its `VDR_BASE_URL`) when it stores it in Certify. Export also asks for the VDR address (`https://vdr.example.org`; a trailing slash is dropped), but only as a label in `manifest.json`: no file depends on it.

```
vdr/templates/<config id>/<version>/template.html
vdr/templates/<config id>/<version>/background.png      only when a Background is loaded
vdr/templates/<config id>/<version>/manifest.json
certify/credentials/<config id>.json
sample/sample.json                                      whatever the uploaded sample is called; never deployed
```

- `template.html` is the uploaded template, byte for byte. The credential file is the uploaded one, apart from `display[0].background_image.uri` (next points).
- A template loads nothing by address. The Background comes only through `$backgroundImage`; a template's own addresses aren't rewritten anywhere (template-sync rewrites the credential file only), and anything a template loads by address answers 422 in VC Lab.
- The config id must be the credential file's `credential_config_key_id` (template-sync stores the file under that key); export answers 400 naming both when they differ. Choosing a credential file fills the config id field from its key.
- With a Background, the credential file's `display[0].background_image.uri` is the fixed path, `http://vdr.localhost/templates/<config id>/<version>/background.png` (other keys of `background_image` stay). Without one, no `background.png` is written, and a `uri` on that fixed path for this config id (any version: a Background since removed) is dropped, with `background_image` if nothing else is left in it. Any other `uri`, such as the hackathon files' card image `http://vdr.localhost/assets/AIT_globe.png`, stays as it was.
- `manifest.json` holds `format` (`vc-lab-package`), `formatVersion`, `credentialConfigId`, `version`, `vdrAddress` and `components`: one `{role, path, deploy}` for each of `template`, `background`, `credential` and `sample`. The sample has `deploy: false`.
- Load Package accepts exactly this layout and gives the files back as they are, so the set previews the same as the one exported.
- Placing the files stays by hand. Mimoto reads the template under a fixed name, `<issuer>-<config id>-template.html`, so copy `template.html` to that name until a version pointer exists.

Placing a Package on the local stack, printing it from the Wallet and comparing the print with VC Lab's PDF is section 6 of [Print from the Wallet](../../docs/guides/print-from-the-wallet.md): the credential file goes in through template-sync, and Certify serves it once recreated. Placing one on dev is that guide's "Running it on dev", item 9.

## Templates the preview refuses

The renderer loads only `data:` URIs, so a template that loads anything by address, a font from the VDR included (`@font-face` with `http://vdr.localhost/templates/fonts/...`), answers 422 naming it, though the Wallet would print it. Use the 14 built-in fonts in a template you preview here. A template that calls a method on Java's reflection or system classes gets null for the call, in the preview and in the Wallet alike (both run Velocity with `SecureUberspector`): printed, the call shows as written, and inside `#if` or `#foreach` the template takes the other branch. That holds for the template only: a credential file's `vc_template` that does it previews with 200 but differently from what Certify, which runs no `SecureUberspector`, signs (`src/renderer/README.md`, "Where it differs from Certify").

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
├── labset.py     # the set a request carries: its slots, parsing and validation
├── package.py    # the Package: export a set, read one back
├── background.py # the Background: a PDF, PNG or JPEG made into one PNG
└── test_main.py  # API tests
```
