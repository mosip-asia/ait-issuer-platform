---
title: "Print from the Wallet on the local stack"
description: "Reproduce the Wallet's PDF from a clean clone: start the real Mimoto beside the local stack, run the print check, swap a template, place a Background, and see what asks T2-T4 ask of other teams."
tags:
  - guide
  - wallet
  - mimoto
  - print
---
# Print from the Wallet on the local stack

The Wallet's PDF is made by Mimoto, not by Certify. This guide starts the real Mimoto 0.21 beside the local stack, prints a made-up student's transcript through it, and checks the PDF. It is the reproduction behind three asks to other teams (T2, T3, T4, below). Thas owns it; Thas's team keeps it working.

Everything here is local. The Mimoto overlay (`compose.mimoto.yaml`) is never used by CD or any deployment, and all data is made up.

## What you need

- A Linux shell with these tools on its `PATH`: `bash`, `docker` (with Compose v2 and, if Docker's config names one, its credential helper), `git`, `curl`, `jq`, `openssl`, `python3` (3.8 or later; standard library only), `awk` and the usual coreutils (`sed`, `grep`, `tr`, `cut`, `base64`, `mktemp`, `id`, `wc`, `seq`, `timeout`, `cp`, `chmod`). `jq` is the one most boxes lack: `scripts/deploy.sh` runs a smoke test that exits without it. On Windows, run everything in WSL, from a clone inside WSL's own home folder (bind mounts fail from `/mnt/c`).
- Ports 80 and 8088 free (Traefik publishes 80 and its dashboard on `TRAEFIK_DASHBOARD_PORT`, 8088 in `.env.example`), and `*.localhost` names resolving to this machine (Linux and recent Windows do this).
- The internet. Certify and Mimoto fetch a JSON-LD context from `https://w3id.org` every time they sign or verify, and the print check installs a font from Debian's package mirrors. When w3id.org is slow, a print can fail with `signature_verification_failed`; run it again.
- One stack at a time: the stack's Compose project is `vc-stack`, with fixed container names and ports.

## 1. Bring the stack up

```bash
git clone https://github.com/mosip-asia/ait-transcript.git
cd ait-transcript
git switch feat/print-template-from-vdr     # until this work reaches dev; then stay on dev
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

`--build` matters until PR #21 (`feat/transcript-hardcopy-layout`, which this branch is stacked on) reaches `dev`: that PR adds `pypdf` to `pyproject.toml`, `dev` and `main` don't declare it, and the image installs from `pyproject.toml`, so a `ghcr.io/mosip-asia/ait-vc` image published from `dev` or `main` lacks the print check's PDF reader. This branch adds no dependency of its own. A check that finds an old image says `FAIL setup: ... isn't in this ait-vc image: rebuild it with scripts/deploy.sh <installation> --build`.

## 2. Start Mimoto

```bash
./scripts/mimoto-up.sh
```

It is safe to run again, so retry it after any failure. It does these things in order, and each one converges:

1. Refuses, printing the two `.env` lines to set, unless Certify trusts the local Keycloak.
2. Generates Mimoto's client key once, in `deploy/ait/mimoto/` (git-ignored). Nothing secret is committed.
3. Writes Certify's live `did:key` into `.env` when `.env` holds another one: the example's placeholder, or the key `deploy.sh` read from a fresh keystore before Certify replaced it. Then Compose re-syncs the credential files and recreates Certify. Without the live DID every credential signs with a key nobody can resolve, and every verifier, Mimoto included, rejects it.
4. Starts the overlay: Mimoto and its own Postgres database. The VDR gains three files under `/templates/` (below).
5. Tells the local Keycloak's `wallet-demo` client to trust Mimoto's key, through Keycloak's admin CLI. The committed realm file is unchanged.
6. Waits until Mimoto serves its issuers list, and prints `Mimoto is up at http://mimoto.localhost/v1/mimoto`.

Mimoto has no host port; it is reached through Traefik at `http://mimoto.localhost`. A Mimoto already running keeps the settings it started with: after changing `deploy/base/mimoto-*.properties`, recreate it with `COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=<.env's COMPOSE_FILE>:compose.mimoto.yaml docker compose up -d --force-recreate mimoto`.

## 3. Run the print check

```bash
./scripts/print-check.sh
```

It takes about a minute. It signs the made-up student `st120001` in at the local Keycloak, takes the transcript from Certify and prints it through Mimoto, the way Inji Web does. Then it checks the PDF. Every step prints `PASS`, and the last line is `print check: PASS`. When a step fails, the line names it (`FAIL sign-in`, `token exchange`, `issuance`, `signature check`, `template fetch` or `PDF content`) and the exit status is 1.

What it proves:

- the download answers `200 application/pdf` and the student's name is on the page;
- a template placed on the VDR prints at the next print, with Mimoto left running: the check swaps in a generic test template, prints again, and puts the original back;
- the test template's course grid holds the 2 term headings and 6 course rows of `st120001`, built from `courseRows` (T4);
- the Background is drawn at the page's full size, a font loaded through `@font-face` is embedded, and Thai text prints, typed in the template and as a claim value;
- the VDR sends `Content-Type: text/html; charset=utf-8` for the template (T2).

The check also publishes a test copy of the credential files to the local stack for the run, made from the files git holds: it maps `courseRows`, points `display[0].background_image` at the VDR, and sets a made-up Thai `notes`. When it ends it republishes the files git holds and recreates Certify, so the stack is as committed. Two consequences:

- A credential file you published by hand (below) takes no part in the check's prints: the copy replaces it when the check starts, and the committed file replaces the copy when it ends. Publish yours again after the check.
- If the restore fails, the check exits with status 1 and prints the command that does it by hand.

The PDFs of the run are kept in a temporary folder, named on the line `PDFs: <folder>`. `original.pdf` is the print of whatever template the VDR held, and `swapped.pdf` the print of the check's test template.

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

Copy over the file or edit it however you like: the VDR mounts the whole `templates` folder, so a replaced file is still served. (The in-place rule, no `sed -i`, applies only to single-file bind mounts, such as the three files `compose.mimoto.yaml` adds; you don't edit those.) The VDR's nginx sends a 7-day `Cache-Control`, which Mimoto ignores; a browser or proxy in front doesn't.

The check's first print (`original`, saved as `original.pdf`) is from your template, with the check's copy of the credential file, and the check puts your template back after its swap. The check asserts the student's name is on the page, so a template of yours must print `fullName`. To print once with a credential file you published yourself, sign in as `st120001` (its password is in `deploy/ait/mock/keycloak-realm.json`, the stand-in realm) the way `src/tools/print_check.py` does: its `context()` and `print_once()` functions are that flow.

Git tracks this file. `git checkout -- deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html` puts the committed one back (and discards your own template if it is still there: keep a copy elsewhere), and CD's `git checkout -f` does it at every deploy, so a template placed this way lasts only until then. Real deployments need their own way to place it (T3).

**A `#macro` is the one thing a swap doesn't replace.** Mimoto's Velocity engine is shared by every print, and it registers a template's `#macro` the first time it sees that name: a later template that defines a macro of the same name prints with the first body until Mimoto restarts. Everything else in the template (markup, `#set`, loops) is read fresh at each print. When you change a macro's body, give it a new name, or recreate Mimoto (`docker compose up -d --force-recreate mimoto`, with the command from step 2). Shown with Mimoto's own Velocity 1.7: the first of two templates that define the same macro wins, in either order. The AIT template's `claimValue` macro hit this: the print check's first print had registered the committed template's version, and the AIT template's corrected macro came out wrong until a fresh Mimoto printed it first.

If a run is killed between the swap and the restore, the next check refuses:
- `FAIL setup: ... is still the print check's test template`: restore the template with the `git checkout --` it prints. That discards whatever template git doesn't hold, so if the leftover replaced your own template, put your copy back instead.
- `FAIL setup: ...background.png's file is still the print check's made-up Background`: delete that file, and publish your real Background there again if you had one.

## Fonts

Any font other than the 14 built-in ones comes in through `@font-face`, and the file has to be on the VDR: place it yourself under `deploy/ait/vdr/templates/fonts/` (for example `narrow.ttf`) and name it by absolute address, `src: url("http://vdr.localhost/templates/fonts/narrow.ttf")`. If the file isn't there, the template falls back to a built-in face without telling you (the built-in faces have no Thai), so check the PDF, for example with `pdffonts`, for the font you expect. Git ignores `ttf`, `otf`, `woff` and `woff2` files under an Installation's `vdr/templates/` folder, as it does Backgrounds, because a font's licence may forbid publishing it in a repository. Which fonts an organisation may publish on its own VDR is its licensing question.

## 5. Place a Background

A Background is the picture of an organisation's pre-printed paper. The platform ships none; the printed page draws it from the VDR, which makes it public. Never commit one: git ignores every `png`, `jpg` and `jpeg` under `deploy/*/vdr/templates/`.

Two things connect it:

1. The file, at `<VDR>/templates/<credential configuration id>/background.png`. Locally: `deploy/ait/vdr/templates/ait-transcript/background.png` (make the folder). Use any PNG or JPEG of the paper, saved under that name. VC Lab's Background is still a PDF today, and its download returns it as uploaded, so it doesn't produce this file; after PR B, VC Lab takes a PNG or JPEG and its download holds it ready to place.
2. The credential file's `display[0].background_image.uri`, set to `http://vdr.localhost/templates/ait-transcript/background.png`. Certify publishes it in its metadata, and Mimoto hands it to the template as `$backgroundImage`. The file git holds sets no address, so publish the credential file with one (next section).

The template then draws it. See "Template conventions".

To see your own Background in the print check: the check's test copy of the credential file already points `display[0].background_image` at `<VDR>/templates/<credential configuration id>/background.png`, so a Background you place there prints in the check. `original.pdf` shows it behind your template. For the swapped print the check puts its own made-up Background at that path and afterwards puts yours back byte for byte.

### Publish a credential file by hand

There is no publish command yet. From the repository root, with the file's folder holding all the Installation's credential files (the sync reads a folder):

```bash
mkdir -p /tmp/creds && cp deploy/ait/certify/credentials/*.json /tmp/creds/
cp my-ait-transcript.json /tmp/creds/ait-transcript.json
chmod -R a+rX /tmp/creds
export COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(grep ^COMPOSE_FILE= .env | cut -d= -f2-):compose.mimoto.yaml"
docker compose run --rm -T -e CREDENTIALS_DIR=/test-credentials -v /tmp/creds:/test-credentials:ro template-sync
docker compose restart certify
```

`template-sync` keeps Certify's live DID because `.env` holds it (step 2 of the start command); with the placeholder every credential would fail to verify. Certify has to restart to serve the new metadata. Mimoto fetches that metadata from Certify with a cache, which the local Mimoto sets to 0 so a published address shows at once; a Mimoto that was already running keeps its old setting until it is recreated.

To put the committed files back: `docker compose up -d --force-recreate template-sync certify`.

## Template conventions

What Mimoto does to a credential decides how a template is written (Velocity 1.7 and iText html2pdf 5.0.3):

- **Rows come from delimited text.** Mimoto hands every list of objects, `courses` included, to the template as an empty string, so a template can't loop over it. Anything drawn as rows reaches the credential as one text claim (`courseRows`, T4), which the template splits:

  ```velocity
  #set($cr = "")
  #set($crMap = $rowProperties.get("courseRows"))
  #if($crMap)#foreach($e in $crMap.entrySet())#set($cr = $e.value)#end#end
  #foreach($row in $cr.split("\n"))
  #set($f = $row.split("\|", -1))
  ## $f.get(0) is T (term heading) or C (course)
  #end
  ```

  **The `-1` is required.** Java's `String.split` drops trailing empty fields, so an ungraded course (`C|CS701|X|0|45|3|`) splits into 6 fields, not 7, and `$f.get(6)` fails. Use `split("\|", -1)` wherever a template reads the last field of a row.
- **Every claim reaches the template** as `$rowProperties` (claim to display name to text), whether or not it has a display name, ordered by the credential file's `display_order` first. A list of text is joined with `", "`.
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
- **`#set` with a missing claim keeps the old value.** Velocity 1.7 leaves a variable as it was when `#set` is given null, so `#set($v = $rowProperties.get("department"))` for a claim the credential lacks leaves `$v` holding the previous claim's text: the box prints the wrong value. Set the variable to `""` first, as the `#set($cr = "")` above does, and test `#if($v && $v.size() > 0)` after.
- **Place a table through a `<div>`.** iText honours `position: absolute` with `left` and `top` on a `<div>` but not on a `<table>`, which lands at the page's top left. Put the table in an absolutely placed `<div>` and leave the table static.
- **Images and fonts use absolute addresses.** Mimoto sets no base URL.
- **Fonts:** only the 14 standard PDF fonts are built in, so Arial and Arial Narrow fall back. Any other font, Thai included, comes through `@font-face` with an absolute URL, see "Fonts" above for where the file goes and why git ignores it.
- **Non-ASCII text typed into a template** needs the VDR's `charset=utf-8` (T2), or HTML entities. Claim values are not affected.

The generic template the print check uses, `tests/fixtures/print-check-template.html`, shows each of these working.

## T2: Mimoto reads its files from the VDR

**The ask, for whoever runs Mimoto and the VDR on a deployment:** set Mimoto's `config.server.file.storage.uri` to the VDR's `/templates/` (with a trailing `/`), so a template replaced on the VDR prints at the next print with no restart (a changed `#macro` body is the one exception, see section 4). Three conditions come with it:

1. **Mimoto's own config files are served from the same address.** Mimoto fetches `mimoto-issuers-config.json` and `mimoto-trusted-verifiers.json` from it, and its CBEFF schema `mosip-cbeff.xsd` from `mosip.kernel.xsdstorage-uri`. The VDR's `/templates/` serves them, or something in front of it does. Today VCGA serves the first two.
2. **`charset=utf-8`.** The VDR's `/templates/` block carries `charset utf-8;` in `deploy/base/vdr-nginx.conf`. Without it Mimoto reads the template as ISO-8859-1 and Thai typed into it prints as `à¸ à¸²à¸©à¸²...`.
3. **Short caches.** Mimoto fetches the template at every print and keeps nothing, but a proxy or CDN between Mimoto and the VDR may honour the VDR's 7-day `Cache-Control` and serve an old template. Mimoto also caches Certify's metadata (60 minutes by default, `cache.credential-issuer.wellknown.expiry-time-in-min`), so a Background address published into Certify may not show until then.

**Where to see it working:**

- Mimoto's settings: `deploy/base/mimoto-bootstrap.properties` (`config.server.file.storage.uri=http://vdr.localhost/templates/`) and `deploy/base/mimoto-default.properties` (`mosip.kernel.xsdstorage-uri`, and the cache line, set to 0 locally).
- The three files on the VDR: `compose.mimoto.yaml` mounts them into `/templates/`.
- `curl -I http://vdr.localhost/templates/AITUniversity-ait-transcript-template.html` answers `Content-Type: text/html; charset=utf-8`; the JSON files and the schema keep their types.
- The VDR's access log after a print (`docker compose logs vdr`) shows Mimoto's `GET /templates/AITUniversity-ait-transcript-template.html`.

Locally the three mount points are empty files that `mimoto-up.sh` creates first, because Docker can't create a file inside the VDR's read-only `templates` mount. Without the overlay the regular VDR serves them as empty files.

## T3: A place for the template and the Background on each VDR

**The ask, for infra:** give each deployment a way to place two files on its VDR by hand. The template comes from VC Lab's download. The Background is a PNG or JPEG of the organisation's paper: VC Lab's own Background is a PDF today and its download returns it as uploaded, so for now the organisation supplies the image, and after PR B VC Lab's download holds it. Neither comes from git, and CD's `git checkout -f` puts back any tracked file replaced in the checkout.

- The template: `<VDR>/templates/AITUniversity-ait-transcript-template.html`. Mimoto fixes this name and looks only at the top of its template address.
- The Background: `<VDR>/templates/ait-transcript/background.png`. The credential file's `display[0].background_image.uri` points there; `template-sync` rewrites that address for each deployment's VDR (`VDR_BASE_URL`).

**Where to see it working:** sections 4 and 5. The file places are the same on the local VDR: `deploy/ait/vdr/templates/` is the VDR's `/templates/`. The print check places a made-up Background at the second place and finds it drawn on the PDF.

## T4: `courseRows`, a text copy of the course grid

**The ask, for the SIS Adapter's builders:** send `courseRows` beside `courses`. One line per row (`\n`), `|` between fields:

- a term heading: `T|<term>|<credits>|<gpa>|<cumGpa>`;
- a course, under its term: `C|<no>|<title>|<lab>|<lec>|<credits>|<grade>`.

No field may hold `|` or a line break (replace them before sending). A field may be empty, including the last. This is Thas's proposal, and SIS may counter. `courses` stays in the credential for verifiers; `courseRows` exists only for printing.

**Where to see it working:**

- The mock Adapter builds it from each record's `courses` (`mock/adapter/ait_courses.py`, served from the `courseRows` column of `deploy/ait/adapter/student_identity_data.csv`).
- The transcript's JSON-LD context defines the term (`deploy/ait/vdr/contexts/transcript/v1.json`), so the claim is signed. The credential file `dev` uses doesn't map it yet; the print check publishes a copy that does (`src/tools/map_course_rows.py` adds `"courseRows": "${courseRows}"` after `courseList`).
- In the print check, `PASS PDF content (swapped): the course grid holds 2 term headings and 6 course rows, in order` is the grid printed from `courseRows`, compared with the record's structured `courses`. verify-service accepts the signed claim.

## When something fails

| What you see | Cause |
|---|---|
| `mimoto-up: refused: Certify must trust the local Keycloak` | The two `AUTH_SERVER_*` lines, or a variable exported in the shell (it wins over `.env`). |
| `FAIL setup: ... isn't in this ait-vc image` | The image is older than this branch: `./scripts/deploy.sh ait --build`. |
| `FAIL template fetch: the VDR answers 404 for /templates/mimoto-...` | `./scripts/mimoto-up.sh` has never run on this checkout, so the three files the VDR serves for Mimoto aren't there: run it. |
| `FAIL setup: Mimoto's issuers list answered ...` | Mimoto isn't running (stopped, or the stack was brought down and only `deploy.sh` ran again). The three Mimoto files stay on the VDR as empty files once `mimoto-up.sh` has run, so the VDR still answers 200 and the check gets as far as asking Mimoto: run `./scripts/mimoto-up.sh`. |
| `FAIL signature check ... signature_verification_failed` | Certify's rows hold a DID other than the key it signs with (run `./scripts/mimoto-up.sh`), or w3id.org was slow or unreachable. |
| `FAIL token exchange ... invalid_request` | The local Keycloak doesn't trust Mimoto's key: run `./scripts/mimoto-up.sh`. |
| The PDF shows Thai as garbage | The VDR doesn't send `charset=utf-8` (T2). |
| A hand-published credential file is gone | A print check ended and put the committed files back: publish it again. |
| A change to `mimoto-*.properties` has no effect | Mimoto keeps its settings until it is recreated (step 2). |
| A swapped template prints with an old macro body | Mimoto registers a `#macro` once; rename it or recreate Mimoto (step 4). |
