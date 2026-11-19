# Credential templates in VC Lab

How a credential's printed copy is built from four files, and what to change when a box needs new data. VC Lab ([`src/vc-lab/`](../../src/vc-lab/README.md)) previews the result and exports it as a PDF.

## How a value reaches the page

```
SIS response ──(credential file: vc_template)──► claims ──(template: #claimValue)──► page
 "studentId": "st990001"   "registrationNo": "${studentId}"   #claimValue("registrationNo")
```

1. **Certify** reads the Adapter's (SIS's) response and fills its credential file's `vc_template` with it (Apache Velocity). The right side names a field of the response (`${studentId}`); the left side is the claim name the issued credential carries (`registrationNo`).
2. **Mimoto**, the Wallet's backend, prints the credential with the template (Apache Velocity again). Each `#claimValue("registrationNo")` is replaced by that claim's value from the issued credential. The key inside the brackets is a **claim name**, the left side of the mapping, never a SIS field name.
3. **VC Lab** imitates both steps from the uploaded files (`src/vc-lab/template_engine.py`), so a template can be checked without issuing anything.

## The four files

| File | Extension | What it is | What it gives | If missing |
|---|---|---|---|---|
| Template | `.html`, A4 | HTML with Velocity: `#claimValue("name")` for a value, `#foreach` for a table, `#if`/`#else` | the page layout | nothing renders |
| Credential file | `.json` | Certify's credential file (as in `deploy/<installation>/certify/credentials/`); `vc_template.credentialSubject` is the mapping | the claims, plus the title, logo and colours from `display` | nothing renders |
| Data (the API's `sample`) | `.json` | one record, exactly as the Adapter sends it, with or without a `credentialSubject` envelope | the values | nothing renders; a field it lacks prints empty |
| Background | `.pdf`, A4 | the pre-printed paper (watermark, seal, signature, image); page 1, fitted on portrait A4 | the paper under page 1 of the PDF | optional: the PDF is the text alone, for pre-printed paper |

The background may be confidential and VC Lab has no login: upload it only on a VC Lab on your own machine, and never commit it.

## Adding or changing a box

1. **The template:** place `#claimValue("newClaim")` where the value goes.
2. **The credential file:** add `"newClaim": "${sisField}"` to `vc_template.credentialSubject` (and to `credential_subject` for its display name).
3. **The context:** a new claim name needs a term in the installation's JSON-LD context (`deploy/<installation>/vdr/contexts/`), which lists every claim. Keep today's claim names where possible.
4. **SIS:** if the response has no field for it, the box stays empty until the Adapter team adds one. Ask in their field names.

Check it in VC Lab with data that has the field, in both views.

## Lab and Wallet views

- **Lab** loops over lists, so `#foreach($t in $courses)` draws the course table.
- **Wallet** prints what Mimoto 0.21 prints: every list claim reaches the template as empty, so loops draw nothing. Give every loop an `#else` with a text fallback (for the transcript, a `courseList` text claim). Without that fallback's source, the Wallet copy has an empty table.

## Known limits (2026-11-19)

- **Certify takes only flat fields.** Its data-provider plugin passes the Adapter's top-level fields and lists named in `mosip.certify.adapter.structured-keys` (default `courses`); it refuses nested objects and does not unwrap `credentialSubject`. VC Lab accepts both, so a mapping that reads `${thesis.title}` or SIS's enveloped response works in VC Lab but not yet in Certify.
- **Numbers print as sent.** A credit sent as `3.0` prints `3.0`.
- **No Mimoto in the local stack**, so the Wallet view is VC Lab's imitation; no real Wallet PDF is checked.
- **Issuing with a credential file from VC Lab:** run the sync tool with its folder mounted; see [VC Lab's README](../../src/vc-lab/README.md#issuing-with-a-credential-file-from-vc-lab).
