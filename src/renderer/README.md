# Renderer

The renderer prints a credential the way the Wallet's printer prints it, so VC Lab's preview is the Wallet's printout. It runs **Mimoto 0.21.0**'s HTML print path (`injistack/mimoto:0.21.0`, source `mosip/mimoto` tag `v0.21.0`) with the same library versions. It's a small Java service with no Spring. It keeps nothing between calls and writes nothing to disk (Compose runs it with a read-only filesystem).

Only VC Lab calls it, at the address in VC Lab's `RENDERER_URL`.

## The one call

```
POST /render  application/json  ->  200 application/pdf  |  422 {"error": "<message>"}  |  400 {"error": "<message>"}
{
  "template": "<HTML with Velocity>",
  "credentialSubject": { ...the claims as Certify signs them... },
  "credentialFile": { "display": [...], "display_order": [...], "credential_subject": {...} },
  "backgroundImage": "data:image/png;base64,..." | null,
  "locale": "en"
}
```

- `credentialFile` is Certify's credential file. The renderer reads it the way Certify publishes it and Mimoto reads it: `display`, `display_order` as `order`, and `credential_subject` as `credential_definition.credentialSubject`.
- `backgroundImage`, when not null, replaces `display[0].background_image.uri`.
- A template that Velocity or iText can't render answers 422. A Velocity error names its line and column.
- A body that isn't the request above answers 400. `GET /health` answers 200.

## What it repeats from Mimoto 0.21

The copied code is in `src/main/java/asia/mosip/renderer/mimoto/`. Each file names the Mimoto file it comes from and keeps the MPL-2.0 notice.

- **Display properties:** every claim, in `display_order` first and then the rest. A claim with no display entry gets a fallback one, its name in title case (`courseRows` becomes `Course Rows`). `id` and the face claim are left out.
- **`formatValue`:**
  - text and numbers as they are;
  - an object becomes its `value`;
  - a list of text is joined with `", "`;
  - a list of objects becomes the `value` of the entry in the locale, else `""`.
- **Template variables:** `rowProperties` (claim → {display name: text}), `backgroundImage`, `logoUrl`, `textColor`, `backgroundColor`, `titleName`, `qrCodeImage`, `face`, `isMaskedOn`, `isSdJwtWithDisclosures`, `disclosures`, `credentialValidity`.
- **Velocity 1.7** initialised as Mimoto initialises it, otherwise with its default settings, so a template can call Java string methods (`$text.split("\n")`).
- **iText html2pdf 5.0.3** with `DefaultFontProvider(true, false, false)`: the 14 standard PDF fonts only. Any other font comes in through `@font-face` with an absolute address. No base URL is set, so images and fonts need absolute addresses too.

Where it differs from Mimoto, because VC Lab has no signed credential and no issuers list:

- `qrCodeImage` is a placeholder QR code holding a fixed text, 400 × 400 like Mimoto's (`mosip.inji.qr.code.width` in `deploy/base/mimoto-default.properties`).
- `logoUrl` comes from the credential file's `display[0].logo.url`. Mimoto takes it from the issuers list.
- `credentialValidity` is `-1`, what Mimoto uses when the Wallet sends no limit.

## Limits

A template runs inside the renderer, and Velocity 1.7's default settings let it reach Java reflection, while VC Lab has no login. So Compose contains the container: a read-only filesystem, uid 1000, no capabilities, `no-new-privileges`, 1 GB of memory and 128 processes. Its network stays open, because it fetches the images and fonts a template names, as Mimoto does. The JVM takes 75% of the memory limit as heap (`docker/Dockerfile.renderer`).

Measured on 2026-11-22: the AIT transcript template with an 8 MB A4 Background (2480 × 3508 PNG), three times in a row and then four at once, all printed; the container peaked at about 860 MB and 39 processes. At the JVM's default heap (25% of the limit), three of the four at once ran out of heap.

## Libraries

Pinned in `pom.xml` to the versions inside `injistack/mimoto:0.21.0`: Velocity 1.7, velocity-tools 2.0, html2pdf 5.0.3, itext7-core 8.0.3, Jackson 2.13.2, commons-collections 3.2.2 and ZXing 3.3.3. When the Wallet moves to another Mimoto version, update the versions, the copied code and the version named here together.

## Running

```bash
docker compose build renderer vc-lab
docker compose run --rm vc-lab python src/vc-lab/test_main.py   # VC Lab's API tests, with the renderer started beside it
```

The image is built from `docker/Dockerfile.renderer`; no Java or Maven is needed on the host.
