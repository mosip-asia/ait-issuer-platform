# Credential templates in VC Lab

How a credential's printed copy is built from four files, and what to change when a box needs new data. VC Lab ([`src/vc-lab/`](../../src/vc-lab/README.md)) previews the result as the PDF the Wallet prints.

## How a value reaches the page

```
SIS response ──(credential file: vc_template)──► claims ──(template: #claimValue)──► page
 "studentId": "st990001"   "registrationNo": "${studentId}"   #claimValue("registrationNo")
```

1. **Certify** reads the Adapter's (SIS's) response and fills its credential file's `vc_template` with it (Apache Velocity). The right side names a field of the response (`${studentId}`); the left side is the claim name the issued credential carries (`registrationNo`).
2. **`ait-mimoto`**, the Wallet's printer, prints the credential with the template (Apache Velocity again). The template gets each claim as `$rowProperties` (claim name → {display name: text}) and the claims whole as `$credentialSubject`. `#claimValue("registrationNo")` is a macro the template defines over `$rowProperties`; the key inside the brackets is a **claim name**, the left side of the mapping, never a SIS field name.
3. **VC Lab** runs both steps in its renderer ([`src/renderer/`](../../src/renderer/README.md)), its own copy of Certify's mapping and `ait-mimoto`'s print code, so a template can be checked without issuing anything.

## The four files

| File | Extension | What it is | What it gives | If missing |
|---|---|---|---|---|
| Template | `.html`, A4 | HTML with Velocity: `#claimValue("name")` (a macro it defines) for a value, `#foreach` over `$credentialSubject` for a table, `#if`/`#else` | the page layout | nothing renders |
| Credential file | `.json` | Certify's credential file (as in `deploy/<installation>/certify/credentials/`); `vc_template.credentialSubject` is the mapping | the claims, plus the title and colours from `display` | nothing renders |
| Data (the API's `sample`) | `.json` | one record, exactly as the Adapter sends it, with or without a `credentialSubject` envelope | the values | nothing renders; a field it lacks prints as the mapping's text (`${field}`), as in Certify |
| Background | `.pdf`, `.png` or `.jpg` | the pre-printed paper (watermark, seal, signature, logo), kept as one PNG (a PDF's page 1 at its own size, 150 dpi) | whatever the template draws with `$backgroundImage`, or loads from `http://vdr.localhost/templates/<any folders>/background.png`, in the PDF and the quick view | optional: without it the template prints on plain paper |

The background may be confidential and VC Lab has no login: upload it only on a VC Lab on your own machine, and never commit it.

## Adding or changing a box

1. **The template:** place `#claimValue("newClaim")` where the value goes.
2. **The credential file:** add `"newClaim": "${sisField}"` to `vc_template.credentialSubject` (and to `credential_subject` for its display name).
3. **The context:** a new claim name needs a term in the installation's JSON-LD context (`deploy/<installation>/vdr/contexts/`), which lists every claim. Keep today's claim names where possible.
4. **SIS:** if the response has no field for it, the box stays empty until the Adapter team adds one. Ask in their field names.

Check it in VC Lab with data that has the field.

## The PDF and the quick view

- **PDF, what the Wallet prints:** iText lays out the evaluated template, as `ait-mimoto` does. This is the reference.
- **HTML, quick view:** the same evaluated template, laid out by your browser. The layout can differ from iText's, and the browser can load addresses the PDF doesn't (see Known limits).

A course table loops over the claim as a list: `#foreach($t in $credentialSubject.courses)`. Only `ait-mimoto` gives `$credentialSubject`; upstream Mimoto doesn't, so a template meant for both keeps an `#else` with a text fallback.

## Known limits (2026-11-25)

- **Certify takes only flat fields.** Its data-provider plugin passes the Adapter's top-level fields and lists named in `mosip.certify.adapter.structured-keys` (default `courses`); it refuses nested objects, `null`s, keys Certify reserves (`id`, `validFrom`, ...) and JSON that isn't strict (a duplicate key). The renderer refuses the same, with the reason, so a mapping that reads `${thesis.title}` fails in VC Lab as in Certify.
- **Numbers print as sent.** A credit sent as `3.0` prints `3.0`.
- **The PDF loads only the set.** iText draws `data:` URIs and the set's files at their VDR address (`http://vdr.localhost/templates/<any folders>/background.png` is the uploaded Background). An image, font or stylesheet the template loads from any other address fails the preview with 422 naming the address. `$logoUrl` is empty, and `<img src="$logoUrl">` draws nothing without an error: the logo belongs in the background. The quick view is your browser's and may still load addresses iText ignores (an `@import`, a `srcset`), so trust the PDF.
- **Issuing with a credential file from VC Lab:** run the sync tool with its folder mounted; see [VC Lab's README](../../src/vc-lab/README.md#issuing-with-a-credential-file-from-vc-lab).
