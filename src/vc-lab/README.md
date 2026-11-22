# VC Lab

VC Lab renders a credential's HTML template from files you upload and shows the PDF the Wallet prints from them. Its preview comes from the [renderer](../renderer/README.md), which runs Mimoto 0.21's print path; VC Lab gets its address from `RENDERER_URL`, which Compose sets. It knows nothing about any organisation: it has no built-in template, data or branding, and it reads nothing from the repo's folders, so a deployed VC Lab behaves the same as a local one.

## The set

What each file is, and how a value travels from SIS to the page, is in [the template guide](../../docs/guides/vc-lab-templates.md). VC Lab works on one set of files at a time, held in memory and forgotten on restart:

| Slot | File | What VC Lab reads from it |
|---|---|---|
| `template` | the HTML (Velocity) render template | the whole file |
| `credential` | Certify's whole credential configuration file | `vc_template.credentialSubject` (the mapping) and the first `display` entry |
| `sample` | the Adapter's response, exactly as the Adapter sends it | its `credentialSubject`, or the whole file when it has none |
| `background` (optional) | a PNG or JPEG of the organisation's paper | the whole image: the preview hands it to the template as `$backgroundImage`, overriding `display[0].background_image.uri` |

Uploading a file replaces that slot only; uploading a zip from Download replaces the whole set. Each file is checked when it is uploaded: the background must be a PNG or JPEG (read from its header, not its name: a PNG's IHDR, a JPEG's start-of-frame; a file whose header can't be read is refused, as is one that decodes to more than 40 MB: pixels x channels x bytes per sample, so A4 at 300 dpi, 2480 x 3508, fits in RGBA but not in 16-bit RGBA. **Only the header is read:** a PNG with a good IHDR but no image data, or a JPEG with a start-of-frame but no scan, is accepted, and the preview then draws no Background. If the Background doesn't show, open the file in an image viewer first), the credential file JSON with a `vc_template` object (holding a `credentialSubject` object), the sample a JSON object, and the template UTF-8 text. Velocity itself checks the template when it renders: `/preview.pdf` answers a template error with 422 and its line. One request may carry at most 8 MB, and the files of a set together at most 64 KB less, so that Download's zip (its headers, and file names cut to 255 bytes) uploads back; an upload that would take the set over that is refused with how many bytes over. A zip from an older VC Lab, whose `background/` holds a PDF, is refused with what to do: remove `background/` from the zip, or upload the files one at a time. The background is kept in memory only, as the image uploaded; Download gives it back as that image, and uploading the zip restores the same preview. With no background, the preview uses the credential file's `display[0].background_image.uri` as it is (VC Lab doesn't rewrite addresses; on the local stack the renderer reaches `vdr.localhost` through `host-gateway`).

## From sample to page

1. The record is the sample's `credentialSubject`, or the whole sample.
2. The mapping is evaluated against the record. `${name}`, `$name` and dotted paths (`${thesis.title}`) read the record; a value that is exactly one reference passes a list or object through unchanged. Certify's own variables (`${_holderId}`, `${_issuer}`, any name starting with `_`) get placeholders. The result is the credential's claims, keyed by the mapping's left side.
3. VC Lab sends the template, the claims, the credential file and the Background (if any) to the renderer, which hands the template Mimoto's variables (`$rowProperties`, `$titleName`, `$logoUrl`, `$textColor`, `$backgroundColor`, `$qrCodeImage`, `$backgroundImage`, and the rest) as Mimoto 0.21 does, and draws the PDF. A list of objects reaches the template as `""` and a list of text joined with `", "`, as in the Wallet. Where it differs: the claims `display_order` leaves out come in the credential file's order here and in Certify's (a Java `HashMap`'s) in the Wallet, so a template that loops over `$rowProperties` names every claim it loops over in `display_order`; and the QR is always a placeholder here, while the Wallet prints none above 4096 bytes of QR data. See [the renderer's README](../renderer/README.md).

## Dashboard and API

The dashboard (`/`) has a file input per slot (or one for a zip), the list of loaded files, the preview (the PDF from `/preview.pdf`, or its error in red), Download, Remove background and Clear.

| Call | Does |
|---|---|
| `POST /api/set` | multipart; any of `template`, `credential`, `sample`, `background`, or one `bundle` (a zip from Download); answers what is loaded |
| `GET /api/set` | which slots are loaded, with their file names, and which required ones are missing |
| `DELETE /api/set` | clears the set |
| `DELETE /api/set/background` | removes the background only |
| `GET /preview.pdf` | the PDF the Wallet prints from the set, drawn by the renderer. The renderer's refusals pass through with its reason: 422 when the set doesn't print (a Velocity error names its line), 400 when it can't read the credential file, 503 when it runs out of memory |
| `GET /download` | a zip with `template/`, `credential/`, `sample/` and `background/`, each file as uploaded |
| `GET /health` | liveness |

Rendering needs the template, the credential file and the sample; without them `/preview.pdf` answers 409, naming what is missing. `/preview.pdf` answers 503 without `RENDERER_URL`, and 502 when the renderer can't be reached or answers anything else. A wrong file answers 400 with the reason.

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

Tests (script-style). The tests that need a real renderer run in the `ait-vc` image through Compose and skip on a host; the rest use a stand-in renderer and run anywhere:

```bash
docker compose build renderer vc-lab
docker compose run --rm vc-lab python src/vc-lab/test_main.py  # the web API, with small made-up sets
```

## Layout

```
src/vc-lab/
├── main.py                  # the web app: dashboard and API over the one set
├── labset.py                # the set: its slots, upload parsing and validation, the zip
├── template_engine.py       # pure: the claim mapping (the credential file's vc_template)
└── test_main.py             # API tests
```
