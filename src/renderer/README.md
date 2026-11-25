# Renderer

The renderer prints a credential the way the Wallet's printer, `ait-mimoto`, prints it, so VC Lab's preview is the Wallet's printout. It is VC Lab's own copy of that print code (ADR 0002): nothing keeps the two in step, so re-check parity by hand after changing either. It first maps the data to claims the way **Certify 0.14** does (see "How it maps the claims"), then runs **Mimoto 0.21.0**'s HTML print path (`injistack/mimoto:0.21.0`, source `mosip/mimoto` tag `v0.21.0`) with `ait-mimoto`'s changes (templates also get `$credentialSubject`, and Velocity runs with `SecureUberspector`, `src/mimoto/README.md`), on the same library versions. It's a small Java service with no Spring. It writes nothing to disk (Compose runs it with a read-only filesystem). It keeps nothing between calls, as long as a template doesn't use reflection to reach past Velocity (see Limits).

Only VC Lab calls it, at the address in VC Lab's `RENDERER_URL`. In `compose.yaml` it sits on a network marked internal that only VC Lab shares.

## The one call

```
POST /render  application/json  ->  200 application/pdf or text/html  |  422 {"error": "<message>"}  |  400 {"error": "<message>"}
{
  "template": "<HTML with Velocity>",
  "record": "<the Adapter's answer, as text>",
  "vcTemplate": "<the credential file's vc_template, as the text template-sync stores for Certify>",
  "credentialFile": { "display": [...], "display_order": [...], "credential_subject": {...}, ... },
  "backgroundImage": "data:image/png;base64,..." | "" | null,
  "locale": "en",
  "output": "pdf" | "html"
}
```

- `record` and `vcTemplate` give the claims, mapped as Certify maps them. `record` is text so the renderer can read it as the plugin does, strict JSON included. VC Lab makes `vcTemplate` with template-sync's own function (`build_vc_template_base64` in `src/certify_template_sync/sync.py`), so it holds that function's one change (`"courses": ${courses}` unquoted). Template-sync's file-level rewrites (`${CERTIFY_DID}`, `${VDR_BASE_URL}`, `${CDN_BASE_URL}`, `http://vdr.localhost`, `http://cdn.localhost`) are not applied to it.
- `credentialFile` is Certify's credential file. The renderer reads it the way Certify publishes it and Mimoto reads it: `display`, `display_order` as `order`, and `credential_subject` as `credential_definition.credentialSubject`. For the claims it reads `credential_type`, `context` and `credential_status_purpose`.
- `output` `html` answers the template as Velocity evaluated it, the HTML iText would print; `pdf` (or none) answers the PDF iText makes of that same HTML. VC Lab's quick view is the first, its PDF the second. Both print the PDF, so the quick view takes as long as the PDF.
- `backgroundImage`, when not null, replaces `display[0].background_image.uri`; `""` is no Background (`$backgroundImage` is empty and the credential file's address is not used; no file is served at the VDR address). VC Lab sends `""` without one. It is a `data:image/png;base64,` URI, and it is also the set's `background.png` (see "What it loads").
- A record or `vcTemplate` the renderer can't map answers 422 with the reason: `shape` refuses the record (a `null`, or a list or object other than `courses`), Velocity can't evaluate the text, or org.json can't read what it makes (`json_processing_error`, as in Certify). The renderer does not refuse everything Certify refuses: see "Where it differs from Certify".
- A template that Velocity or iText can't render answers 422. A Velocity error names its line and column; a template nested too deep to parse says so.
- A template that loads an address the renderer doesn't serve answers 422 naming the address, for `output` `html` too (see "What it loads").
- A body that isn't the request above, or a credential file it can't read, answers 400.
- Running out of memory answers 503. `GET /health` answers 200.

## What it loads

iText loads every address a template names (an image, a `@font-face`, a stylesheet) through `SetFiles.java`, which serves only:

- `data:` URIs, which iText decodes itself;
- the set's files, at their VDR address: an address under `http://vdr.localhost/templates/` whose file name is a file in the set, whatever the folders between. Today the set's one file is `background.png`, the request's `backgroundImage`, so a template that draws `http://vdr.localhost/templates/<config id>/<version>/background.png` previews with the Background before it is on the VDR.

Any other address, on any host or `file:`, and `background.png` when no Background is sent, fails the call with 422 naming it. iText alone would log the address and print without it, while the Wallet's `ait-mimoto` fetches it, so the preview would quietly differ from the print. `output` `html` is printed too, and an address iText asks for and can't get fails it the same way. That doesn't make the quick view the print: a browser lays it out and fetches what iText ignores and never asks `SetFiles` for (a stylesheet's `@import`, `<script src>`, `<iframe src>`, `srcset`, `<body background>`, a `@font-face` in a format iText doesn't read). So the quick view can show a web font the PDF doesn't; the PDF is the reference. Sandboxing the quick view is out of the spec's scope. An empty address (`<img src="">`, which the demo template draws with `$logoUrl` empty) loads nothing and is not refused: the Wallet loads nothing there either.

## How it maps the claims

`CertifyMapping.java` follows the steps Certify 0.14 takes for an `ldp_vc` credential, apart from the differences under "Where it differs from Certify", read from the bytecode of `certify-service.jar` in `ghcr.io/mosip-asia/ait-certify` (`CertifyIssuanceServiceImpl.getVerifiableCredential` and `VelocityTemplatingEngineImpl.format`), on Certify's library versions (`BOOT-INF/lib`): Velocity 1.7 and org.json 20241224.

1. The record goes through this platform's Data-provider plugin's step: `TemplateRecord`, the renderer's copy of the plugin's `strictObject`, `record` and `shape` (`src/issuer/.../IssuerDataProviderPlugin.java`); change both together. The answer is read as strict JSON (a duplicate key, a lenient form or text after the object is refused), a reserved or trace key (`id`, `_holderId`, `_issuer`, `validFrom`, `validUntil`, `credentialStatus`, `tokenSub`, `tokenClientId`) is refused, every string is JSON-escaped, `courses` becomes its JSON text, and a `null` or any other list or object is refused. Each refusal answers 422 with `adapter_error` and the plugin's reason.
2. Certify's variables are added, as Certify adds them. The values are fixed placeholders, since VC Lab issues nothing:

   | Variable | From | Preview value |
   |---|---|---|
   | `tokenSub`, `tokenClientId` | the plugin's `fetchData` | `preview-sub`, `preview-client` |
   | `type` | the Wallet's request (`credential_definition.type`); it replaces a record's own `type` | the credential file's `credential_type`, split at `,` |
   | `credentialStatus` | `StatusListCredentialService.addCredentialStatus`, when `credential_status_purpose` is set and `context` has the VC 2.0 context | `id`, `type` `BitstringStatusListEntry`, `statusPurpose` (the first purpose), `statusListIndex` `0`, `statusListCredential` |
   | `_holderId` | the holder's DID, from the proof | `did:example:holder` |
   | `templateName`, `didUrl`, `_issuer` | Certify's template key, and its DID (`mosip.certify.data-provider-plugin.did-url`) | `preview-template-name`, `did:example:issuer` |
   | `validFrom`, `validUntil` | the issuance time, and it plus `P730D` | `2000-01-01T00:00:00.000Z`, `2001-12-31T00:00:00.000Z` |
   | `_dateTool`, `_esc` | velocity-tools `DateTool` and `EscapeTool` | the same tools, from velocity-tools 2.0 (Certify has 3.1) |

   Not added: `credentialId` (both Installations set `mosip.certify.data-provider-plugin.id-field-prefix-uri`, so Certify adds it; the renderer does not) and `renderingTemplateId` (`rendering-template-id` is empty here).
3. A new Velocity engine with Certify's two settings (`input.encoding` and `output.encoding` UTF-8), plus `SecureUberspector` (see Limits), evaluates `vcTemplate` with those variables, and org.json reads the result. Its `credentialSubject` is the claims, handed to Mimoto's print as Mimoto would read them from the signed credential (Jackson, in org.json's order).

So a `${field}` the record lacks stays the text `${field}`, `$!{field}` gives nothing, `$name-$id` reads a variable `$name-` (a Velocity name may hold `-`), and `${name.toUpperCase()}` calls Java, all as in Certify.

Certify has one Velocity engine for every issuance, so a `#macro` in a `vc_template` would stay defined there, while the renderer starts a new engine per call.

### Where it differs from Certify

The preview can print a record or mapping that Certify signs differently or refuses. What a designer would see:

- An answer with a `credentialSubject` object is read as that object (VC Lab takes the Adapter's response with or without that envelope); the plugin refuses the envelope.
- Certify's `toJsonMap` and its extra variables (`rootContext`, `envConfigs`, `claim_169_values`, `credentialId`) are not reproduced: a mapping that uses them, or `$type` in quotes, previews differently from what Certify signs.
- Template-sync's file-level rewrites (`${CERTIFY_DID}`, `${VDR_BASE_URL}`, `${CDN_BASE_URL}`, `http://vdr.localhost`, `http://cdn.localhost`) are not applied to the preview's mapping, so they show literally inside a claim.
- The mapping runs with `SecureUberspector`, Certify's without: a `vc_template` that calls a method on Java's reflection or system classes shows the call as written in the preview, while Certify evaluates it.

## What it repeats from Mimoto 0.21

The copied code is in `src/main/java/asia/mosip/renderer/mimoto/`. Each file names the Mimoto file it comes from and keeps the MPL-2.0 notice.

- **Display properties:** every claim, in `display_order` first and then the rest. A claim with no display entry gets a fallback one, its name in title case (`courseRows` becomes `Course Rows`). `id` and the face claim are left out.
- **`formatValue`:**
  - text and numbers as they are;
  - an object becomes its `value`;
  - a list of text is joined with `", "`;
  - a list of objects becomes the `value` of the entry in the locale, else `""`.
- **Template variables:** `credentialSubject` (the claims whole, as `ait-mimoto` adds them), `rowProperties` (claim → {display name: text}), `backgroundImage`, `logoUrl`, `textColor`, `backgroundColor`, `titleName`, `qrCodeImage`, `face`, `isMaskedOn`, `isSdJwtWithDisclosures`, `disclosures`, `credentialValidity`.
- **Velocity 1.7** with the properties Mimoto sets plus `SecureUberspector`, as `ait-mimoto` runs it, otherwise its default settings, so a template can call Java string methods (`$text.split("\n")`) but not methods on reflection and system classes (see Limits).
- **iText html2pdf 5.0.3** with `DefaultFontProvider(true, false, false)`: the 14 standard PDF fonts only. In the Wallet, any other font comes in through `@font-face` with an absolute address, and images need absolute addresses too (no base URL is set). The renderer loads only data URIs and the set's files, and refuses any other address (see "What it loads").

Where it differs from Mimoto, because VC Lab has no signed credential and no issuers list:

- `qrCodeImage` is a placeholder QR code holding a fixed text, 400 × 400 like Mimoto's (`mosip.inji.qr.code.width` in `deploy/base/mimoto-default.properties`). The Wallet prints none when the credential's QR data is over 4096 bytes (`mosip.inji.qr.data.size.limit`); the preview still draws the placeholder.
- The order of the claims `display_order` leaves out. Both hand `rowProperties` in `display_order`, then the other claims in the order they get them: the Wallet in the signed credential's order, which Certify makes org.json's (a Java `HashMap`'s); the preview in the order org.json gives the same claims. They should agree. They did once, for the transcript's claims printed from the committed credential file (2026-11-25, `docs/guides/print-from-the-wallet.md` section 6), but nothing checks it for other files, so a template that loops over `rowProperties` names every claim it loops over in `display_order`.
- `logoUrl` is empty: the logo belongs in the Background. Mimoto takes it from the issuers list.
- `credentialValidity` is `-1`, what Mimoto uses when the Wallet sends no limit.
- Each print gets a new Velocity engine. Mimoto renders with the Velocity singleton, where the first definition of a macro name stays until Mimoto restarts. So the preview always shows a template's own macro body, while the Wallet may print an older body, if a template defining the same macro name printed earlier since Mimoto's restart.

## Limits

A template runs inside the renderer, while VC Lab has no login. Both Velocity engines (the `vc_template` mapping and the print template) run with `SecureUberspector`, which refuses method calls on `java.lang.reflect` and on classes such as `Class`, `ClassLoader`, `Runtime`, `System` and `Thread`: the call is left in the output as written. That is a second layer only. Velocity 1.7's list has a known bypass (CVE-2020-13936), and through it a template can read the renderer's environment, call out over its network, change state that later calls see, or stop the JVM. So the renderer is contained:

- `docker/Dockerfile.renderer` runs it as uid 1000, with a fixed 640 MB heap (`-Xmx640m`).
- `compose.yaml` gives it a read-only filesystem, no capabilities, `no-new-privileges`, 1 GB of memory, at most 128 tasks (threads count against this, not only processes) and `restart: unless-stopped`. Its only network is marked internal and shared with VC Lab alone: it has no route out, and nothing but VC Lab can reach it. iText doesn't try the network either: it loads only what `SetFiles.java` serves (see "What it loads").
- The server reads, prints and answers at most four requests at once; the others wait their turn.

Measured on 2026-11-22 inside the container at those limits: the AIT transcript template with an 8 MB A4 Background (2480 × 3508 PNG). Three in a row, then 4, 10 and 24 at once, all printed (`200`, the slowest 4.1 s in the wave of 24). The container's memory peaked at 775 MB of 1024 MB and its tasks at 42 of 128. A template calling `Runtime.exit` (the renderer then ran without `SecureUberspector`, as the bypass would let it) stopped the JVM; Docker restarted it, and the next prints passed. Before the queue and the fixed heap (a 1 GB limit, heap at 75% of it), 10 at once gave five 503s and 24 at once dropped four connections.

## Libraries

Pinned in `pom.xml` to the versions inside `injistack/mimoto:0.21.0`: Velocity 1.7, velocity-tools 2.0, html2pdf 5.0.3, itext7-core 8.0.3, Jackson 2.13.2, commons-collections 3.2.2 and ZXing 3.3.3; and, for the claims, Certify 0.14's org.json 20241224 (its Velocity is 1.7 too). When the Wallet moves to another Mimoto version, or the Issuer to another Certify, update the versions, the copied code and the version named here together.

## Running

```bash
docker compose build renderer vc-lab
docker compose run --rm vc-lab python src/vc-lab/test_main.py   # VC Lab's API tests, with the renderer started beside it
```

The image is built from `docker/Dockerfile.renderer`; no Java or Maven is needed on the host.
