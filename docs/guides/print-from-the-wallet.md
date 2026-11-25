---
title: "Print from the Wallet on the local stack"
description: "Reproduce the Wallet's PDF from a clean clone: start ait-mimoto beside the local stack, run the print check, swap a template, place a Background, and see what running it on dev takes."
tags:
  - guide
  - wallet
  - mimoto
  - print
---
# Print from the Wallet on the local stack

The Wallet's PDF is made by Mimoto, not by Certify. This guide starts `ait-mimoto` (Mimoto 0.21 with two changes, below) beside the local stack, prints a made-up student's transcript through it, and checks the PDF, course grid included. Thas proves it here; Jo runs it on dev from "Running it on dev", below. Thas owns this guide; Thas's team keeps it working.

Everything here is local. The Mimoto overlay (`compose.mimoto.yaml`) is never used by CD or any deployment, and all data is made up.

## What `ait-mimoto` is

Upstream Mimoto turns every claim into one string before the template sees it, and every list of objects becomes `""`. So a template can't loop over `courses`. `ait-mimoto` is upstream `injistack/mimoto:0.21.0` with two changes (`src/mimoto/`). First, the template also gets the claims as Mimoto received them, as `$credentialSubject`. `$rowProperties` and every other variable are unchanged, so a template written for upstream Mimoto prints the same. Second, the print step runs Velocity with `SecureUberspector`, so a template that reaches for Java internals (for example `$x.getClass().forName("java.lang.Runtime")`) prints its reference unevaluated instead of running it. VC Lab previews with the same setting (ADR 0002).

That lets a template loop over `courses`; it doesn't change what any template prints by itself. The grid prints only once the template on the VDR uses the convention in "Template conventions". The committed demo template (`deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html`) has no `$credentialSubject` branch: it prints `courseList` on either image. The print check swaps in a test template that does, and puts the committed one back.

## What you need

- A Linux shell with these tools on its `PATH`: `bash`, `docker` (with Compose v2 and, if Docker's config names one, its credential helper), `git`, `curl`, `jq`, `openssl`, `python3` (3.8 or later; standard library only), `awk` and the usual coreutils (`sed`, `grep`, `tr`, `cut`, `base64`, `mktemp`, `id`, `wc`, `seq`, `timeout`, `cp`, `chmod`). `jq` is the one most boxes lack: `scripts/deploy.sh` runs a smoke test that exits without it. On Windows, run everything in WSL, from a clone inside WSL's own home folder (bind mounts fail from `/mnt/c`).
- Ports 80 and 8088 free (Traefik publishes 80 and its dashboard on `TRAEFIK_DASHBOARD_PORT`, 8088 in `.env.example`), and `*.localhost` names resolving to this machine (Linux and recent Windows do this).
- The internet. Certify and Mimoto fetch a JSON-LD context from `https://w3id.org` every time they sign or verify, the print check installs a font from Debian's package mirrors, and the first build pulls `injistack/mimoto:0.21.0` and `eclipse-temurin:21-jdk`. When w3id.org is slow, a print can fail with `signature_verification_failed`; run it again.
- Free disk for the stack's four `ait-*` images, which are built from your clone, and for the base images they pull (`ait-mimoto` alone adds a layer of a few hundred MB).
- One stack at a time: the stack's Compose project is `vc-stack`, with fixed container names and ports.

## 1. Bring the stack up

```bash
git clone https://github.com/mosip-asia/ait-issuer-platform.git ait-transcript
cd ait-transcript
git switch feat/vc-lab-prints-like-wallet     # until this work reaches dev; then stay on dev
cp .env.example .env
```

The `.env` lines. Change these three and leave the rest as the example has them:

```
COMPOSE_FILE=compose.yaml:compose.mock.yaml
AUTH_SERVER_ISSUER=http://auth.localhost/realms/ait
AUTH_SERVER_JWKS_URL=http://auth.localhost/realms/ait/protocol/openid-connect/certs
```

- `compose.mock.yaml` adds the stand-in Keycloak (realm `ait`) and the mock Adapter, so there are made-up students to sign in.
- The two `AUTH_SERVER_*` lines make Certify trust that local Keycloak. `.env.example` sets the issuer to the dev OAuth server (and the JWKS URL to Certify's own), so Certify would publish the dev server as where a Wallet signs in, and Mimoto would send a student's login code there. The start command refuses to go on until they are set.

Then:

```bash
./scripts/deploy.sh ait --build
```

`--build` builds the images from your clone instead of pulling published ones. The print check itself is not in the `ait-vc` image: `scripts/print-check.sh` mounts `src/tools/print_check.py` from your checkout and runs it inside `ait-vc`, which supplies Python and the libraries the check imports, `pypdf` (its PDF reader) among them. So an `ait-vc` published before `pypdf` was added to `pyproject.toml` can't run it. A check that finds such an image says `FAIL setup: ... isn't in this ait-vc image: rebuild it with scripts/deploy.sh <installation> --build`.

## 2. Start Mimoto

```bash
./scripts/mimoto-up.sh
```

It is safe to run again, so retry it after any failure. It does these things in order, and each one converges:

1. Refuses, printing the two `.env` lines to set, unless Certify trusts the local Keycloak.
2. Generates Mimoto's client key once, in `deploy/ait/mimoto/` (git-ignored). Nothing secret is committed.
3. Writes Certify's live `did:key` into `.env` as `CERTIFY_DID` when `.env` holds another one: the example's placeholder, or the key `deploy.sh` read from a fresh keystore before Certify replaced it. Without the live DID every credential signs with a key nobody can resolve, and every verifier, Mimoto included, rejects it.
4. Builds the `ait-mimoto` image from this checkout (the first build takes a few minutes; a build with nothing changed takes seconds), then starts the overlay: Mimoto and its own Postgres database. The overlay passes `CERTIFY_DID` to `template-sync`, so Compose re-syncs the credential files with the live DID and recreates Certify. The VDR gains four files under `/templates/` (below).
5. Tells the local Keycloak's `wallet-demo` client to trust Mimoto's key, through Keycloak's admin CLI. The committed realm file is unchanged.
6. Waits until Mimoto serves its issuers list, and prints `Mimoto is up at http://mimoto.localhost/v1/mimoto`.

Mimoto has no host port; it is reached through Traefik at `http://mimoto.localhost`. A Mimoto already running keeps the settings it started with: after changing `deploy/base/mimoto-*.properties`, recreate it with `COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=<.env's COMPOSE_FILE>:compose.mimoto.yaml docker compose up -d --force-recreate mimoto`.

## 3. Run the print check

```bash
./scripts/print-check.sh
```

It signs the made-up student `st120001` in at the local Keycloak, takes the transcript from Certify and prints it through Mimoto, the way Inji Web does, twice (your template, then the check's own). Then it checks the PDF. Every check prints a `PASS` line. The run ends with these lines, in this order: `restored the original AITUniversity-ait-transcript-template.html`, `print check: PASS`, `PDFs: <folder>` and `restored the committed credential file in Certify`, and the exit status is 0. A run that ends without `print check: PASS` failed. When a step fails, the line names it (`FAIL sign-in`, `token exchange`, `issuance`, `signature check`, `template fetch` or `PDF content`) and the exit status is 1.

What it proves:

- the download answers `200 application/pdf` and the student's name is on the page;
- a template placed on the VDR prints at the next print, with Mimoto left running: the check swaps in a generic test template, prints again, and puts the original back;
- the test template's course grid holds the 2 term headings and 6 course rows of `st120001`, in order, looped over `$credentialSubject.courses` (`ait-mimoto`), and every row is drawn inside the page;
- the Background is drawn at the page's full size, a font loaded through `@font-face` is embedded, and Thai text prints, typed in the template and as a claim value;
- the VDR sends `Content-Type: text/html; charset=utf-8` for the template.

The check also publishes a test copy of the credential files to the local stack for the run, made from the files git holds: it points `display[0].background_image` at the VDR and sets a made-up Thai `notes`. The `courses` mapping is the committed one. When it ends it republishes the files git holds and recreates Certify, so the stack is as committed. Two consequences:

- A credential file you published by hand (below) takes no part in the check's prints: the copy replaces it when the check starts, and the committed file replaces the copy when it ends. Publish yours again after the check.
- If the restore fails, the check exits with status 1 and prints the command that does it by hand.

The PDFs of the run are kept in a temporary folder, named on the line `PDFs: <folder>`. `original.pdf` is the print of whatever template the VDR held, and `swapped.pdf` the print of the check's test template.

To see the grid, read the text of `swapped.pdf` (the `ait-vc` image has the PDF reader). Replace `<folder>` with the folder on the `PDFs:` line; the image tag is `.env`'s `IMAGE_TAG`:

```bash
docker run --rm -v <folder>:/pdf:ro ghcr.io/mosip-asia/ait-vc:$(grep ^IMAGE_TAG= .env | cut -d= -f2) \
  python -c "from pypdf import PdfReader; print(PdfReader('/pdf/swapped.pdf').pages[0].extract_text())" \
  | grep -E '^(TERM|COURSE) '
```

It prints one `TERM | <term> | <credits> | <gpa> | <cumGpa> ;` line for each of the 2 terms and one `COURSE | <no> | <title> | <lab> | <lec> | <credits> | <grade> ;` line for each of the 6 courses, under their terms.

Stop the stack, and remove its volumes:

```bash
COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=compose.yaml:compose.mock.yaml:compose.mimoto.yaml docker compose down -v --remove-orphans
```

## 4. Swap a template

Mimoto fetches `<issuer id>-<credential type>-template.html` from the VDR at every print and caches nothing, so a replaced file prints at the next print. The name is fixed by Mimoto: for the transcript it is `AITUniversity-ait-transcript-template.html`.

```bash
cp my-template.html deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html
./scripts/print-check.sh
```

Copy over the file or edit it however you like: the VDR mounts the whole `templates` folder, so a replaced file is still served. (The in-place rule, no `sed -i`, applies only to single-file bind mounts, such as the four files `compose.mimoto.yaml` adds; you don't edit those.) The VDR's nginx sends a 7-day `Cache-Control`, which Mimoto ignores; a browser or proxy in front doesn't.

The check's first print (`original`, saved as `original.pdf`) is from your template, with the check's copy of the credential file, and the check puts your template back after its swap. The check asserts the student's name is on the page, so a template of yours must print `fullName`. To print once with a credential file you published yourself, sign in as `st120001` (its password is in `deploy/ait/mock/keycloak-realm.json`, the stand-in realm) the way `src/tools/print_check.py` does: its `context()` and `print_once()` functions are that flow.

Git tracks this file. `git checkout -- deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html` puts the committed one back (and discards your own template if it is still there: keep a copy elsewhere), and CD's `git checkout -f` does it at every deploy, so a template placed this way lasts only until then. Real deployments need their own way to place it.

**A `#macro` is the one thing a swap doesn't replace.** Mimoto's Velocity engine is shared by every print, and it registers a template's `#macro` the first time it sees that name: a later template that defines a macro of the same name prints with the first body until Mimoto restarts. Everything else in the template (markup, `#set`, loops) is read fresh at each print. When you change a macro's body, give it a new name, or recreate Mimoto (`docker compose up -d --force-recreate mimoto`, with the command in section 2). Shown with Mimoto's own Velocity 1.7: the first of two templates that define the same macro wins, in either order. The AIT template's `claimValue` macro hit this: the print check's first print had registered the committed template's version, and the AIT template's corrected macro came out wrong until a fresh Mimoto printed it first.

If a run is killed between the swap and the restore, the next check refuses:
- `FAIL setup: ... is still the print check's test template`: restore the template with the `git checkout --` it prints. That discards whatever template git doesn't hold, so if the leftover replaced your own template, put your copy back instead.
- `FAIL setup: ...background.png's file is still the print check's made-up Background`: delete that file, and publish your real Background there again if you had one.

## Fonts

Any font other than the 14 built-in ones comes in through `@font-face`, and the file has to be on the VDR: place it yourself under `deploy/ait/vdr/templates/fonts/` (for example `narrow.ttf`) and name it by absolute address, `src: url("http://vdr.localhost/templates/fonts/narrow.ttf")`. VC Lab can't preview such a template: its renderer loads nothing but the set's files and answers 422 naming the font's address (section 6). If the file isn't there, the template falls back to a built-in face without telling you (the built-in faces have no Thai), so check the PDF, for example with `pdffonts`, for the font you expect. Git ignores `ttf`, `otf`, `woff` and `woff2` files under an Installation's `vdr/templates/` folder, as it does Backgrounds, because a font's licence may forbid publishing it in a repository. Which fonts an organisation may publish on its own VDR is its licensing question.

## 5. Place a Background

A Background is the picture of an organisation's pre-printed paper. The platform ships none; the printed page draws it from the VDR, which makes it public. Never commit one: git ignores every `png`, `jpg` and `jpeg` under `deploy/*/vdr/templates/`.

Two things connect it:

1. The file, at `<VDR>/templates/<credential configuration id>/<version>/background.png`. Locally, for version `v1`: `deploy/ait/vdr/templates/ait-transcript/v1/background.png`. It has to be an image of the paper, PNG, under that name: the template draws it with `<img>`. VC Lab makes it: it turns a PDF, PNG or JPEG into `background.png`, and Export Package writes it at that path (section 6).
2. The credential file's `display[0].background_image.uri`, set to `http://vdr.localhost/templates/ait-transcript/v1/background.png`. Export Package sets it in the Package's credential file. Certify publishes it in its metadata, and Mimoto hands it to the template as `$backgroundImage`.

An Installation therefore needs both: its credential file points `display[0].background_image.uri` at the Background on its VDR, and its template draws `$backgroundImage`. The committed demo files do neither (`deploy/ait/certify/credentials/ait-transcript.json` sets only `background_color`, and the committed template doesn't use `$backgroundImage`), so publish the credential file with an address (next section). The print check does both for its own run.

The template draws it as shown in "Template conventions".

To see your own Background in the print check: the check's test copy keeps a `display[0].background_image.uri` on the local VDR, such as the one a Package's credential file carries once it is in `deploy/ait/certify/credentials/` (section 6). A file without one is pointed at `<VDR>/templates/<credential configuration id>/background.png`, so a Background you place there prints in the check. `original.pdf` shows it behind your template. For the swapped print the check puts its own made-up Background at that path and afterwards puts yours back byte for byte.

### Publish a credential file by hand

There is no publish command yet. From the repository root, with the file's folder holding all the Installation's credential files (the sync reads a folder):

```bash
mkdir -p /tmp/creds && cp deploy/ait/certify/credentials/*.json /tmp/creds/
cp my-ait-transcript.json /tmp/creds/ait-transcript.json
chmod -R a+rX /tmp/creds
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(grep ^COMPOSE_FILE= .env | cut -d= -f2-):compose.mimoto.yaml" docker compose "$@"; }
compose run --rm -T -e CREDENTIALS_DIR=/test-credentials -v /tmp/creds:/test-credentials:ro template-sync
compose restart certify
```

`template-sync` keeps Certify's live DID because `.env` holds it as `CERTIFY_DID` and the overlay passes it on (steps 3 and 4 of the start command in section 2); with the placeholder every credential would fail to verify. Certify has to restart to serve the new metadata. Mimoto fetches that metadata from Certify with a cache, which the local Mimoto sets to 0 so a published address shows at once; a Mimoto that was already running keeps its old setting until it is recreated.

To put the committed files back: `compose up -d --force-recreate template-sync certify`, with the `compose` function above. The function sets the two variables for its own command only, so nothing leaks into a later `deploy.sh`.

## 6. Preview a set in VC Lab and print its Package

VC Lab (`http://lab.localhost`) previews a set (template, credential file, sample record, Background) as the PDF the Wallet prints, through its renderer (`src/renderer/`, ADR 0002). This section runs the whole loop once with a made-up set, and checks the claim: preview in VC Lab, export a Package, place it on the local VDR and in Certify by hand, print from the Wallet, and compare the two PDFs' text. Run it after section 3's print check passes, from the repository root. `deploy.sh` has already started VC Lab and the renderer (`compose.yaml`).

The made-up set:

- the template `tests/fixtures/vc-lab-parity-template.html`: every claim but `notes` (the print check replaces `notes` with a Thai text for its run), the course grid from `$credentialSubject`, the Background through `$backgroundImage`, and the QR code. It loads no font by address: VC Lab's renderer loads only the set's files and answers 422 naming any other address, so a template like `tests/fixtures/print-check-template.html`, whose font comes from the VDR, can't preview in VC Lab;
- the committed credential file, `deploy/ait/certify/credentials/ait-transcript.json`;
- the sample: the mock Adapter's answer for the made-up student `st120001`, as Certify gets it;
- a made-up Background, drawn below.

In a browser this is the dashboard at `http://lab.localhost`: choose the four files, read the PDF ("what the Wallet prints"), then fill the credential configuration id, version and VDR address and press Export Package. The commands make the same calls:

```bash
mkdir -p /tmp/vc-lab-parity
IMAGE=ghcr.io/mosip-asia/ait-vc:$(grep ^IMAGE_TAG= .env | cut -d= -f2)
curl -sf http://adapter.localhost/student/st120001/transcript -o /tmp/vc-lab-parity/st120001.json
docker run --rm "$IMAGE" python -c "
import sys
from PIL import Image, ImageDraw
page = Image.new('RGB', (1240, 1754), 'white')
ImageDraw.Draw(page).rectangle([0, 0, 1239, 150], fill=(210, 225, 240))
page.save(sys.stdout.buffer, 'PNG')" > /tmp/vc-lab-parity/background.png
SET=(-F template=@tests/fixtures/vc-lab-parity-template.html
     -F credential=@deploy/ait/certify/credentials/ait-transcript.json
     -F sample=@/tmp/vc-lab-parity/st120001.json
     -F background=@/tmp/vc-lab-parity/background.png)
curl -sf "${SET[@]}" http://lab.localhost/preview.pdf -o /tmp/vc-lab-parity/vclab.pdf
curl -sf "${SET[@]}" -F config_id=ait-transcript -F version=v1 -F vdr_address=http://vdr.localhost \
  http://lab.localhost/api/package/export -o /tmp/vc-lab-parity/package.zip
```

`curl -sf` exits non-zero on an error status; send the same call without `-f` to read VC Lab's message. The Package holds `vdr/templates/ait-transcript/v1/{template.html,background.png,manifest.json}`, `certify/credentials/ait-transcript.json` and `sample/st120001.json` (`src/vc-lab/README.md`, "The Package"). The config id has to be the credential file's `credential_config_key_id`.

Place it by hand. Locally the checkout is the VDR (`deploy/ait/vdr/templates/` is its `/templates/`) and Certify's credential folder. Mimoto reads the template only under its fixed name, `<issuer id>-<credential configuration id>-template.html`, so `template.html` is copied to that name too, until a version pointer exists. Certify serves the new credential file once template-sync has stored it and Certify is recreated:

```bash
python3 -m zipfile -e /tmp/vc-lab-parity/package.zip /tmp/vc-lab-parity/package
cp -r /tmp/vc-lab-parity/package/vdr/templates/ait-transcript deploy/ait/vdr/templates/
cp /tmp/vc-lab-parity/package/vdr/templates/ait-transcript/v1/template.html \
  deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html
cp /tmp/vc-lab-parity/package/certify/credentials/ait-transcript.json deploy/ait/certify/credentials/ait-transcript.json
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(grep ^COMPOSE_FILE= .env | cut -d= -f2-):compose.mimoto.yaml" docker compose "$@"; }
compose up -d --force-recreate template-sync certify
until curl -sf -o /dev/null http://issuer.localhost/.well-known/openid-credential-issuer; do sleep 5; done
curl -s http://issuer.localhost/.well-known/openid-credential-issuer \
  | jq -r '.credential_configurations_supported["ait-transcript"].display[0].background_image.uri'
```

The last line prints `http://vdr.localhost/templates/ait-transcript/v1/background.png`, the Package's Background. Then print from the Wallet with the check command, and compare:

```bash
./scripts/print-check.sh | tee /tmp/vc-lab-parity/print-check.log
PDFS=$(sed -n 's/^PDFs: //p' /tmp/vc-lab-parity/print-check.log)
docker run --rm --user "$(id -u):$(id -g)" -v /tmp/vc-lab-parity:/lab:ro -v "$PDFS:/wallet:ro" "$IMAGE" python -c "
import difflib
from pypdf import PdfReader
def lines(path):
    return [l.strip() for p in PdfReader(path).pages for l in (p.extract_text() or '').splitlines() if l.strip()]
lab, wallet = lines('/lab/vclab.pdf'), lines('/wallet/original.pdf')
diff = list(difflib.unified_diff(lab, wallet, 'VC Lab', 'Wallet', lineterm=''))
print('\n'.join(diff + ['FAIL parity: the texts differ']) if diff else f'PASS parity: the same {len(lab)} lines of text')"
```

The print check ends `print check: PASS`: its first print, `original.pdf`, is the Package's template with the Package's credential file (and its Thai `notes`), Background included. The compare ends `PASS parity: the same <n> lines of text`; on `FAIL parity` it prints the lines that differ. The QR code is an image and isn't compared: VC Lab draws a placeholder.

Put the committed files back:

```bash
git checkout -- deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html deploy/ait/certify/credentials/ait-transcript.json
rm -rf deploy/ait/vdr/templates/ait-transcript/v1 /tmp/vc-lab-parity
compose up -d --force-recreate template-sync certify
```

## Template conventions

What Mimoto does to a credential decides how a template is written (Velocity 1.7 and iText html2pdf 5.0.3):

- **Loop over `courses` through `$credentialSubject`, and fall back to `courseList`.** On `ait-mimoto` the grid comes from the structured `courses`: a list of terms, each with `term`, `credits`, `gpa`, `cumGpa` and its own `courses` (`no`, `title`, `lab`, `lec`, `credits`, `grade`). On upstream Mimoto `$credentialSubject` doesn't exist and `courses` arrives as `""`, so the same template prints `courseList` there, which arrives whole, one line per course:

  ```velocity
  #if($credentialSubject && $credentialSubject.courses)
  #foreach($term in $credentialSubject.courses)
  ## $!term.term, $!term.credits, $!term.gpa, $!term.cumGpa
  #foreach($c in $term.courses)
  ## $!c.no, $!c.title, $!c.lab, $!c.lec, $!c.credits, $!c.grade
  #end
  #end
  #else
  #set($courseList = "")
  #set($listed = $rowProperties.get("courseList"))
  #if($listed)#foreach($e in $listed.entrySet())#set($courseList = $e.value)#end#end
  ## one line per course: $courseList.split("\n")
  #end
  ```

  **Use quiet references (`$!c.grade`, not `$c.grade`) for every field.** A missing or null value then prints an empty cell. A plain reference prints its own name, `$c.grade`, in the cell. `$credentialSubject` is the claims as received, so a template that prints from it decides what shows: `ait-mimoto` doesn't mask SD-JWT disclosures or drop the face there as it does for `$rowProperties`.
- **Every claim reaches the template** as `$rowProperties` (claim to display name to text), whether or not it has a display name, ordered by the credential file's `display_order` first. A list of text is joined with `", "`. Claims `display_order` leaves out come in Certify's internal (HashMap) order, so name every claim a template loops over in `display_order`. A list of objects is `""` there, which is why the grid reads `$credentialSubject`.
- **A full-bleed Background needs two things.** Set `@page { margin: 0 }` and `body { margin: 0 }`, or iText's 36 pt page margin moves the image in from the edge. And wrap the layout in a page-sized `position: relative` box, with the image absolutely placed inside it. An `<img src="$backgroundImage">` placed straight in `<body>` is drawn above the page and is lost:

  ```html
  <style>
    @page { size: A4; margin: 0; }
    body { margin: 0; }
    .page { position: relative; width: 595.28pt; height: 841.89pt; }
    .background { position: absolute; left: 0; top: 0; width: 595.28pt; height: 841.89pt; }
  </style>
  <div class="page">
    #if($backgroundImage && $backgroundImage != "")<img class="background" src="$backgroundImage"/>#end
    <!-- layout -->
  </div>
  ```
- **`#set` with a missing claim keeps the old value.** Velocity 1.7 leaves a variable as it was when `#set` is given null, so `#set($v = $rowProperties.get("department"))` for a claim the credential lacks leaves `$v` holding the previous claim's text: the box prints the wrong value. Set the variable to `""` first, as the `#set($courseList = "")` above does, and test `#if($v && $v.size() > 0)` after.
- **Place a table through a `<div>`.** iText honours `position: absolute` with `left` and `top` on a `<div>` but not on a `<table>`, which lands at the page's top left. Put the table in an absolutely placed `<div>` and leave the table static.
- **Images and fonts use absolute addresses.** Mimoto sets no base URL.
- **Fonts:** only the 14 standard PDF fonts are built in, so Arial and Arial Narrow fall back. Any other font, Thai included, comes through `@font-face` with an absolute URL, see "Fonts" above for where the file goes and why git ignores it.
- **Non-ASCII text typed into a template** needs the VDR's `charset=utf-8` ("Running it on dev"), or HTML entities. Claim values are not affected.
- **Claim values reach the template as they are, unescaped,** in both `$rowProperties` and `$credentialSubject`.
- **A template must look right without the QR.** Mimoto 0.21 draws `$qrCodeImage` only when the credential's encoded QR data is under 4096 characters, and a long transcript may pass that.

The generic template the print check uses, `tests/fixtures/print-check-template.html`, shows the grid (with its fallback and quiet references), the Background, the font and Thai working. Its loop over the claims uses plain references, so it isn't a model for a missing claim.

## Running it on dev

Thas proves the Wallet's print here; Jo sets it up on dev and decides how. These are the pieces, each with where to see it working locally. None needs a change to the SIS Adapter contract.

### 1. The image

Run `ghcr.io/mosip-asia/ait-mimoto` where a plain Mimoto would run `injistack/mimoto:0.21.0`, with the same configuration, files and ports. `:latest` is published from commit `454e95e` and pulls without a login. A release tag also publishes `ait-mimoto:<tag>`, since `scripts/build.sh` builds it beside `ait-certify`.

**Why:** Mimoto 0.21 hands every list of objects to the template as `""`, so a template can't draw the course grid by term. `ait-mimoto` also hands the template the claims as received, as `$credentialSubject`, so a template can loop over `$credentialSubject.courses` (see "Template conventions"). The SIS Adapter sends nothing new: `courses` is already in contract 0.5.0.

**The image alone changes nothing a Wallet prints.** The grid prints only once the template on the VDR uses that convention. The committed demo template (`AITUniversity-ait-transcript-template.html`) has no `$credentialSubject` branch and keeps printing `courseList` on either image.

**Where the change is:** `src/mimoto/` holds the one changed file, two lines added to upstream's `CredentialPDFGeneratorService.java`, with its MPL-2.0 notice and the upstream tag and commit it came from (`src/mimoto/README.md`). `docker/Dockerfile.mimoto` puts it into `injistack/mimoto:0.21.0`.

**Where to see it working:**

- The grid: section 3's print check, whose test template follows the convention. `PASS PDF content (swapped): the course grid holds 2 term headings and 6 course rows, in order` is the grid printed from `courses`, compared with the record's structured `courses`.
- The one-image swap: `compose.mimoto.yaml`'s `mimoto` service differs from a plain Mimoto only by its `image:` (and `build:`, which only the local stack uses).
- The fallback, on upstream Mimoto: put `injistack/mimoto:0.21.0` back in place of `ait-mimoto` (a Compose file that overrides the image), then print again:

  ```bash
  printf 'services:\n  mimoto:\n    image: injistack/mimoto:0.21.0\n' > /tmp/upstream-mimoto.yaml
  COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(grep ^COMPOSE_FILE= .env | cut -d= -f2-):compose.mimoto.yaml:/tmp/upstream-mimoto.yaml" \
    docker compose up -d --no-build --force-recreate mimoto
  ./scripts/print-check.sh
  ```

  The check then ends `FAIL PDF content: st120001's grid holds 0 term headings and 0 course rows, not 2 and 6, ...`, because it expects the grid. In `swapped.pdf` the courses print as 6 `COURSE-LINE` lines and no `TERM` or `COURSE |` rows. Put `ait-mimoto` back with `./scripts/mimoto-up.sh`.

### 2. The files Mimoto reads

The local overlay hands Mimoto these files. On dev each one goes where Mimoto reads it.

| Repository file | Where Mimoto reads it | What dev changes |
|---|---|---|
| `deploy/base/mimoto-bootstrap.properties` | `/home/mosip/mimoto-bootstrap.properties` (`SPRING_CLOUD_BOOTSTRAP_LOCATION`) | Nothing: the template address comes from the environment variable in step 3. |
| `deploy/base/mimoto-default.properties` | `/home/mosip/mimoto-default.properties` (`SPRING_CONFIG_LOCATION`, `SPRING_CONFIG_NAME=mimoto`) | Its local addresses: `keycloak.internal.url` and `keycloak.external.url` (`http://auth.localhost`), `mosip.inji.web.url` (`http://wallet.localhost`), `mosip.security.origins`, and `mosip.api.public.url`. The Certify metadata cache is 0 here; see step 5. |
| `deploy/base/mimoto_init.sql` | Mimoto's own Postgres, as an init script (database `inji_mimoto`) | Nothing. |
| `deploy/<installation>/vcga/issuers.json` | `<VDR>/templates/mimoto-issuers-config.json` | Dev's issuer and OAuth addresses. |
| `deploy/base/vcga/trusted-verifiers.json` | `<VDR>/templates/mimoto-trusted-verifiers.json` | Nothing. |
| `deploy/base/mosip-cbeff.xsd` | `<VDR>/templates/mosip-cbeff.xsd` (Mimoto stops at startup without it) | Nothing. |
| `deploy/base/vdr/templates/credential-template.html` | `<VDR>/templates/credential-template.html`, the template for a credential with none of its own, such as `ait-student-id` (without it: `RESIDENT-APP-028`) | Nothing. The VDR already serves it at `/base-templates/`, which Mimoto doesn't read. |
| The client keystore, `deploy/<installation>/mimoto/oidckeystore.p12` (made by `mimoto-up.sh`, never committed) | `/home/mosip/certs/oidckeystore.p12` | Dev's own key, password in `oidc_p12_password`, trusted by dev's OAuth client for the Wallet. |

The rest of the container's environment is in `compose.mimoto.yaml`, the `mimoto` service. On dev, its passwords (`oidc_p12_password`, Postgres) are dev's own.

**Where to see it working:** `compose.mimoto.yaml` mounts each file. Locally the four VDR files land on empty, git-ignored files that `mimoto-up.sh` creates first, because Docker can't create a file inside the VDR's read-only `templates` mount.

### 3. The template address: one environment variable

```
CONFIG_SERVER_FILE_STORAGE_URI=<VDR>/templates/
```

With the trailing `/`. It overrides `config.server.file.storage.uri` in the bootstrap file, and `spring.cloud.config.uri` and `mosip.kernel.xsdstorage-uri` follow it, so Mimoto reads its template and the files in step 2 from the VDR. Mimoto fetches the template at every print and keeps nothing, so a template replaced on the VDR prints at the next print with no restart. The one exception is a changed `#macro` body (section 4).

**Proven on the local stack (2026-11-24):** with the bootstrap file pointing at an address that serves nothing, Mimoto exits at startup (`CbeffUtil init failed: ... nothing-here/mosip-cbeff.xsd`). With the same file and the variable set, every request Mimoto makes goes to `/templates/` and the print check passes.

**Where to see it working:** `docker compose exec mimoto printenv CONFIG_SERVER_FILE_STORAGE_URI` once set, and the VDR's access log after a print (`docker compose logs vdr`), which shows Mimoto's `GET /templates/AITUniversity-ait-transcript-template.html`, `mimoto-issuers-config.json` and `mosip-cbeff.xsd`.

### 4. `charset=utf-8` on the VDR's `/templates/`

The VDR's `/templates/` block carries `charset utf-8;` in `deploy/base/vdr-nginx.conf`. Without it Mimoto reads the template as ISO-8859-1 and Thai typed into it prints as `à¸ à¸²à¸©à¸²...`. Claim values aren't affected.

**Where to see it working:** `curl -I http://vdr.localhost/templates/AITUniversity-ait-transcript-template.html` answers `Content-Type: text/html; charset=utf-8`; the JSON files and the schema keep their types.

### 5. Short caches

A proxy or CDN between Mimoto and the VDR may honour the VDR's 7-day `Cache-Control` and serve an old template. Mimoto also caches Certify's metadata, 60 minutes by default (`cache.credential-issuer.wellknown.expiry-time-in-min`), so a Background address published into Certify may not show until then. The local Mimoto sets it to 0.

### Where Mimoto looks for the template and the Background

How a deployment places these is its own choice. Mimoto looks here:

- The template: `<VDR>/templates/AITUniversity-ait-transcript-template.html`. Mimoto fixes this name, `<issuer id>-<credential configuration id>-template.html`, at the top of its template address.
- The Background: wherever the credential file's `display[0].background_image.uri` points, as an image (PNG or JPEG). Locally that's `<VDR>/templates/ait-transcript/background.png`, and `template-sync` rewrites the address for each deployment's VDR (`VDR_BASE_URL`). The template has to draw `$backgroundImage`. The committed demo files do neither (section 5).

CD's `git checkout -f` puts back any tracked file replaced in the checkout, so a template copied over the committed one lasts only until the next deploy.

## When something fails

| What you see | Cause |
|---|---|
| `mimoto-up: refused: Certify must trust the local Keycloak` | The two `AUTH_SERVER_*` lines, or a variable exported in the shell (it wins over `.env`). |
| `FAIL setup: ... isn't in this ait-vc image` | The image is older than this branch: `./scripts/deploy.sh ait --build`. |
| `mimoto-up.sh` stops while building `ait-mimoto` | The build pulls `injistack/mimoto:0.21.0` and `eclipse-temurin:21-jdk` and installs `zip` from Debian's mirrors: check the network and Docker's free disk, then run it again. |
| `FAIL template fetch: the VDR answers 404 for /templates/mimoto-...` | `./scripts/mimoto-up.sh` has never run on this checkout, so the files the VDR serves for Mimoto aren't there: run it. |
| `FAIL setup: Mimoto's issuers list answered ...` | Mimoto isn't running (stopped, or the stack was brought down and only `deploy.sh` ran again). The four Mimoto files stay on the VDR as empty files once `mimoto-up.sh` has run, so the VDR still answers 200 and the check gets as far as asking Mimoto: run `./scripts/mimoto-up.sh`. |
| `FAIL signature check ... signature_verification_failed` | Certify's rows hold a DID other than the key it signs with (run `./scripts/mimoto-up.sh`), or w3id.org was slow or unreachable. |
| `FAIL token exchange ... invalid_request` | The local Keycloak doesn't trust Mimoto's key: run `./scripts/mimoto-up.sh`. |
| `FAIL PDF content: ... grid holds 0 term headings` and the PDF has `COURSE-LINE` lines | Mimoto is upstream's `injistack/mimoto:0.21.0`, not `ait-mimoto`: run `./scripts/mimoto-up.sh`, which recreates it from the built image. |
| The PDF shows Thai as garbage | The VDR doesn't send `charset=utf-8` ("Running it on dev", item 3). |
| A grid cell prints `$c.grade` (or another field's name) | The template uses a plain reference: write `$!c.grade`. |
| A hand-published credential file is gone | A print check ended and put the committed files back: publish it again. |
| A change to `mimoto-*.properties` has no effect | Mimoto keeps its settings until it is recreated (section 2). |
| A swapped template prints with an old macro body | Mimoto registers a `#macro` once; rename it or recreate Mimoto (section 4). |
