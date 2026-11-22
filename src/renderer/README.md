# Renderer

The renderer prints a credential the way the Wallet's printer prints it, so VC Lab's preview is the Wallet's printout. It runs **Mimoto 0.21.0**'s HTML print path (`injistack/mimoto:0.21.0`, source `mosip/mimoto` tag `v0.21.0`) with the same library versions. It's a small Java service with no Spring. It writes nothing to disk (Compose runs it with a read-only filesystem). It keeps nothing between calls, as long as a template doesn't use reflection to reach past Velocity (see Limits).

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
- A template that Velocity or iText can't render answers 422. A Velocity error names its line and column; a template nested too deep to parse says so.
- A body that isn't the request above, or a credential file it can't read, answers 400.
- Running out of memory answers 503. `GET /health` answers 200.

## What it repeats from Mimoto 0.21

The copied code is in `src/main/java/asia/mosip/renderer/mimoto/`. Each file names the Mimoto file it comes from and keeps the MPL-2.0 notice.

- **Display properties:** every claim, in `display_order` first and then the rest. A claim with no display entry gets a fallback one, its name in title case (`courseRows` becomes `Course Rows`). `id` and the face claim are left out.
- **`formatValue`:**
  - text and numbers as they are;
  - an object becomes its `value`;
  - a list of text is joined with `", "`;
  - a list of objects becomes the `value` of the entry in the locale, else `""`.
- **Template variables:** `rowProperties` (claim → {display name: text}), `backgroundImage`, `logoUrl`, `textColor`, `backgroundColor`, `titleName`, `qrCodeImage`, `face`, `isMaskedOn`, `isSdJwtWithDisclosures`, `disclosures`, `credentialValidity`.
- **Velocity 1.7** with the properties Mimoto sets, otherwise its default settings, so a template can call Java string methods (`$text.split("\n")`).
- **iText html2pdf 5.0.3** with `DefaultFontProvider(true, false, false)`: the 14 standard PDF fonts only. Any other font comes in through `@font-face` with an absolute address. No base URL is set, so images and fonts need absolute addresses too.

Where it differs from Mimoto, because VC Lab has no signed credential and no issuers list:

- `qrCodeImage` is a placeholder QR code holding a fixed text, 400 × 400 like Mimoto's (`mosip.inji.qr.code.width` in `deploy/base/mimoto-default.properties`). The Wallet prints none when the credential's QR data is over 4096 bytes (`mosip.inji.qr.data.size.limit`); the preview still draws the placeholder.
- The order of the claims `display_order` leaves out. Both hand `rowProperties` in `display_order`, then the other claims in the order they get them: the Wallet in the signed credential's order, which Certify makes a Java `HashMap`'s; the preview in the credential file's. So a template that loops over `rowProperties` must name every claim it loops over in `display_order` to print the same order in both.
- `logoUrl` comes from the credential file's `display[0].logo.url`. Mimoto takes it from the issuers list.
- `credentialValidity` is `-1`, what Mimoto uses when the Wallet sends no limit.
- Each print gets a new Velocity engine. Mimoto renders with the Velocity singleton, where the first definition of a macro name stays until Mimoto restarts. So the preview always shows a template's own macro body, while the Wallet may print an older body, if a template defining the same macro name printed earlier since Mimoto's restart.

## Limits

A template runs inside the renderer, and Velocity 1.7's default settings let it reach Java reflection, while VC Lab has no login. Such a template can read the renderer's environment, call out over its network, change state that later calls see, or stop the JVM. So the renderer is contained:

- `docker/Dockerfile.renderer` runs it as uid 1000, with a fixed 640 MB heap (`-Xmx640m`).
- `compose.yaml` gives it a read-only filesystem, no capabilities, `no-new-privileges`, 1 GB of memory, at most 128 tasks (threads count against this, not only processes) and `restart: unless-stopped`. Its network stays open, because it fetches the images and fonts a template names, as Mimoto does.
- The server reads, prints and answers at most four requests at once; the others wait their turn.

Measured on 2026-11-22 inside the container at those limits: the AIT transcript template with an 8 MB A4 Background (2480 × 3508 PNG). Three in a row, then 4, 10 and 24 at once, all printed (`200`, the slowest 4.1 s in the wave of 24). The container's memory peaked at 775 MB of 1024 MB and its tasks at 42 of 128. A template calling `Runtime.exit` stopped the JVM; Docker restarted it, and the next prints passed. Before the queue and the fixed heap (a 1 GB limit, heap at 75% of it), 10 at once gave five 503s and 24 at once dropped four connections.

## Libraries

Pinned in `pom.xml` to the versions inside `injistack/mimoto:0.21.0`: Velocity 1.7, velocity-tools 2.0, html2pdf 5.0.3, itext7-core 8.0.3, Jackson 2.13.2, commons-collections 3.2.2 and ZXing 3.3.3. When the Wallet moves to another Mimoto version, update the versions, the copied code and the version named here together.

## Running

```bash
docker compose build renderer vc-lab
docker compose run --rm vc-lab python src/vc-lab/test_main.py   # VC Lab's API tests, with the renderer started beside it
```

The image is built from `docker/Dockerfile.renderer`; no Java or Maven is needed on the host.
