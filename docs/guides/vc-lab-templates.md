---
title: "Credential templates in VC Lab"
description: "How to write a template that prints right in the Wallet the first time: what the Wallet does to the data, the conventions that follow, the four files VC Lab takes, and publishing a set locally."
tags:
  - guide
  - vc-lab
  - wallet
  - print
---
# Credential templates in VC Lab

How to write a template that prints right in the Wallet the first time. VC Lab ([`src/vc-lab/`](../../src/vc-lab/README.md)) has one view: the PDF the Wallet prints. Its preview is drawn by the [renderer](../../src/renderer/README.md), which runs the Wallet's own print path (Mimoto 0.21), so what you see is what the Wallet prints, with the differences under "Known limits". VC Lab prints with the locale fixed to `en`.

Every snippet below was previewed through VC Lab with made-up data. Thas owns this guide; Thas's team keeps it working.

## How a value reaches the page

```
SIS response ──(credential file: vc_template)──► claims ──(template)──► page
 "studentId": "st990001"   "registrationNo": "${studentId}"   $rowProperties.get("registrationNo")
```

1. **Certify** reads the Adapter's (SIS's) response and fills the credential file's `vc_template` with it (Apache Velocity). The right side names a field of the response (`${studentId}`); the left side is the claim name the issued credential carries (`registrationNo`).
2. **Mimoto**, the Wallet's backend, prints the credential with your template (Velocity 1.7, then iText html2pdf 5.0.3). The template reads claim names, the left side of the mapping, never SIS field names.
3. **VC Lab** has the renderer map the uploaded data to claims with Certify's own steps (the Data-provider plugin's escaping, then Velocity 1.7 and org.json on the `vc_template` text the sync tool stores) and print them, so you can check a template without issuing anything. Data or a `vc_template` that Certify would refuse is refused in VC Lab too, with the reason.

## The four files

| File | Extension | What it is | If missing |
|---|---|---|---|
| Template | `.html`, A4 | HTML with Velocity | nothing renders |
| Credential file | `.json` | Certify's credential file; `vc_template.credentialSubject` is the mapping, `display` and `display_order` shape the print | nothing renders |
| Data (the API's `sample`) | `.json` | one record, as the Adapter sends it, with or without a `credentialSubject` envelope | nothing renders; a `${field}` it lacks is signed and printed as the literal text `${field}`, a `$!{field}` as nothing |
| Background | `.png` or `.jpg` | a picture of the organisation's paper (watermark, seal, signature) | optional: the preview uses the credential file's `display[0].background_image.uri`, or draws none |

How a reference in `vc_template` previews is how Certify signs it:

- A `${field}` (or `$field`) the data lacks is the literal text `${field}`; a quiet `$!{field}` is nothing.
- A `null` in the data, or a list or object other than `courses`, is refused, as Certify's plugin refuses it (`adapter_error`). A list of text or an object can still be a claim, written as JSON in `vc_template` itself.
- A Velocity name may hold `-`: `"$name-$id"` reads a variable `name-`. Write `"${name}-${id}"`.
- `##` starts a Velocity comment to the end of the line, so `"## note"` breaks the JSON and is refused; so is any text that doesn't make JSON.
- References are Java: `${name.toUpperCase()}` works, as do Thai or other text right after a name (`"คุณ${name}ครับ"`).

The Background reaches the template as `$backgroundImage`. A Background may be confidential and VC Lab has no login: upload it only on a VC Lab on your own machine, and never commit it.

**Rotate a photo before you upload it.** A JPEG can carry an EXIF "orientation" tag that tells a viewer to turn it. Mimoto and VC Lab both ignore the tag, so a phone photo of the paper prints sideways. Open the picture, rotate it until the paper is upright, and save it again, so the pixels themselves are upright. Check it in VC Lab's preview.

A small set to start a **preview** from (made-up data). It is for VC Lab only: a set you will publish starts from the Installation's own credential file instead (see "Publish it locally"). The credential file:

```json
{
  "credential_config_key_id": "example-card",
  "display": [
    { "name": "Example Card", "locale": "en", "text_color": "#000000", "background_color": "#ffffff" }
  ],
  "display_order": ["registrationNo", "fullName", "courses", "courseRows"],
  "credential_subject": {
    "registrationNo": { "display": [{ "name": "Registration No.", "locale": "en" }] },
    "fullName": { "display": [{ "name": "Full Name", "locale": "en" }] },
    "courses": { "display": [{ "name": "Courses", "locale": "en" }] }
  },
  "vc_template": {
    "credentialSubject": {
      "registrationNo": "${studentId}",
      "fullName": "${fullName}",
      "courses": "${courses}",
      "courseRows": "${courseRows}"
    }
  }
}
```

The data:

```json
{
  "studentId": "st000001",
  "fullName": "Somchai Example",
  "courses": [{ "no": "CS101", "grade": "A" }],
  "courseRows": "T|Term 1|6|3.50|3.50\nC|CS101|Intro to Computing|0|45|3|A\nC|CS102|Algorithms|0|45|3|"
}
```

## What the Wallet does to your data

Mimoto prepares the claims before your template sees them. Write the template for what it hands over, not for what the credential holds.

- **Nearly every claim is there.** The template gets them as `$rowProperties`: claim name, to display name, to text. A claim with no display name in the credential file still arrives, under its name in title case (`courseRows` shows as `Course Rows`). Not in it: `id` when the credential file gives it no display entry (with one, it arrives); any null claim; and the first non-empty claim named `image`, `face`, `photo`, `picture` or `portrait`, which arrives as `$face` instead.
- **`display_order` sets the order** of `$rowProperties`: the claims it lists come first, in its order. **Name every claim a template loops over in `display_order`.** The claims it leaves out reach the Wallet in Certify's internal (HashMap) order; VC Lab builds them the same way, but that is not checked claim for claim, so don't rely on the order of the claims after the listed ones. A claim read by name (`#claimText("fullName")`) is not affected.
- **`formatValue` flattens each value to text:**
  - text and numbers stay as they are;
  - an object becomes its `value` field, or `""` when it has none;
  - a list of text is joined with `", "` (`Dean's list, Cum laude`);
  - a list of numbers prints as `[1, 2]`;
  - a list of objects becomes the `value` of the entry whose `language` matches the locale, else `""`. A template can't loop over `courses`: see "Rows" below.
- **Values go into the HTML as they are.** A `<` in a value is read as a tag: `R&D <Lab>` prints as `R&D`.
- **Send anything whose formatting matters as text.** Parsing the JSON can turn `3.50` into `3.5`, so a GPA or a credit count that must print as written goes as a string.

To see what a template really gets, print everything:

```velocity
#foreach($claim in $rowProperties.entrySet())
#foreach($shown in $claim.value.entrySet())
<p>$claim.key | $shown.key | $shown.value</p>
#end
#end
```

To read one claim, use a macro. It prints nothing for a claim the credential lacks:

```velocity
#macro(claimText $claimName)
#set($__claim = false)
#set($__claim = $rowProperties.get($claimName))
#if($__claim && $__claim.size() > 0)
#foreach($__entry in $__claim.entrySet())$__entry.value#break#end
#end
#end
```

The first `#set` is needed: Velocity 1.7 keeps a variable's old value when `#set` is given null, so without it a missing claim would print the previous claim's value (macro variables are shared by every call). Then `#claimText("fullName")` where the value goes.

**A macro name must be new to the Wallet.** Mimoto's Velocity engine is shared by every print and keeps the first body it saw for a macro name until Mimoto restarts. Don't reuse a name that another template on that Mimoto already defines (a committed template may define `claimValue`, for one): your body would be ignored. When you change a macro's body, give it a new name too (see [print from the Wallet](./print-from-the-wallet.md#4-swap-a-template)).

## Conventions

### The page: `@page { margin: 0 }` and `$backgroundImage`

Set `@page { margin: 0 }` and `body { margin: 0 }`, or the printer's default 36 pt page margin moves the Background in from the edge. Wrap the layout in a page-sized `position: relative` box and put the Background in it as an absolutely placed image. An `<img src="$backgroundImage">` placed straight in `<body>` is drawn above the page and lost.

```html
<style>
  @page { size: A4; margin: 0; }
  body { margin: 0; font-family: Helvetica, sans-serif; font-size: 10pt; }
  .page { position: relative; width: 595.28pt; height: 841.89pt; }
  .background { position: absolute; left: 0; top: 0; width: 595.28pt; height: 841.89pt; }
  .content { position: absolute; left: 40pt; top: 40pt; width: 515pt; }
</style>
<div class="page">
  #if($backgroundImage && $backgroundImage != "")<img class="background" src="$backgroundImage"/>#end
  <div class="content">
    <!-- the layout goes here -->
  </div>
</div>
```

**Keep the layout out of the page box's flow.** A flowing block such as a `<p>` with a top margin, placed as a child of `.page`, has that margin collapse through the box and push the whole box, Background included, down (a 12 pt margin moved the image 12 pt off the top). Put the layout in an absolutely placed box, as `.content` is above, whose margins stay inside it. Nothing then sits in `.page` but the image and that box.

**The page is one page.** An absolutely placed box never breaks onto a second page: what doesn't fit is cut off, with no error (120 course rows gave one page with only the first part of them visible; how many depends on the layout). Design for the longest record you expect, and check it in the preview.

### Rows: delimited text and the split idiom

A list of objects reaches the template as `""`, so a template can't loop over `courses`. Anything drawn as rows must reach the credential as one text claim (here `courseRows`): one line per row, `|` between fields, no field holding `|` or a line break. The template splits it:

```velocity
#set($cr = "")
#set($crMap = false)
#set($crMap = $rowProperties.get("courseRows"))
#if($crMap)#foreach($e in $crMap.entrySet())#set($cr = $e.value)#end#end
<table>
#foreach($row in $cr.split("\n"))
#set($f = $row.split("\|", -1))
#if($f.size() > 1)
<tr>#foreach($x in $f)<td>$x</td>#end</tr>
#end
#end
</table>
```

- **The `-1` is required.** Java's `String.split` drops trailing empty fields, so `C|CS102|Algorithms|0|45|3|` (no grade yet) would split into 6 fields, not 7, and `$f.get(6)` fails.
- **Reset both variables first.** Velocity 1.7 keeps the old value when `#set` is given null, so for a claim the credential lacks, `$crMap` would keep the previous claim's map and refill `$cr` from it. The `#set($cr = "")` and `#set($crMap = false)` lines stop that. Reset them again if you read a second claim the same way.
- **Place a table through a `<div>`.** iText honours `position: absolute` with `left` and `top` on a `<div>`. On a `<table>` it honours `left` but ignores `top`: the table lands at the top of the box it sits in. Put the table in an absolutely placed `<div>` and leave the table static.

For the transcript, the Adapter's `courseRows` format and what the template does with it are in [print from the Wallet](./print-from-the-wallet.md#t4-courserows-a-text-copy-of-the-course-grid) (an AIT example).

### The QR code

Mimoto 0.21 hands the template `$qrCodeImage` (a bare base64 PNG, so the `src` needs the `data:image/png;base64,` prefix) only when the issuer's `qr_code_type` is `EmbeddedVC` and the encoded QR data is under 4096 characters. Above that, the Wallet prints no QR, and a long credential (a transcript with many courses) can pass it. With `OnlineSharing` there is no such limit, and any other type gives `""`. VC Lab always draws a placeholder QR, so its preview can show one where the Wallet prints none. Guard it, and design the page so it looks right without it:

```velocity
#if($qrCodeImage && $qrCodeImage != "")<img src="data:image/png;base64,$qrCodeImage" style="width:80pt; height:80pt"/>#end
```

### Absolute addresses

Mimoto sets no base URL, so every image and font in a template needs a full `http://` or `https://` address. A relative one prints nothing. The renderer fetches the address itself, so it must be reachable from the renderer.

### Fonts: `@font-face`, Thai included

Only the 14 standard PDF fonts are built in, so Arial and Arial Narrow fall back to a built-in face, and the built-in faces have no Thai. Any other font, Thai included, comes in through `@font-face` with an absolute address. Name it first in `font-family`:

```html
<style>
  @font-face { font-family: "ThaiFace"; src: url("http://vdr.localhost/templates/fonts/thai.ttf"); }
  body { font-family: ThaiFace, Helvetica, sans-serif; }
</style>
```

If the file isn't at that address, the page falls back silently. Check the PDF's fonts (for example `pdffonts`) for the one you expect. A font's licence may forbid publishing it, so keep font files out of git; where one goes on the local VDR is in [print from the Wallet](./print-from-the-wallet.md#fonts).

### UTF-8 or HTML entities

Save the template as UTF-8. Text typed into it (Thai, accents) is read by Mimoto as ISO-8859-1 unless the VDR serves the template with `charset=utf-8` (ask T2 in [print from the Wallet](./print-from-the-wallet.md#t2-mimoto-reads-its-files-from-the-vdr)). A `<meta charset="UTF-8"/>` in the `<head>` is for browsers only: it does not change what Mimoto reads. The safe form is an HTML entity:

```html
<p>&#x0E20;&#x0E32;&#x0E29;&#x0E32;&#x0E44;&#x0E17;&#x0E22;</p>
```

VC Lab prints raw Thai correctly, because it hands the renderer the file as UTF-8, so its preview can look right where the Wallet's print would not: use entities for text typed into the template. Claim values are not affected: they arrive as the credential holds them.

## Adding or changing a box

1. **The template:** place `#claimText("newClaim")` where the value goes.
2. **The credential file:** add `"newClaim": "${sisField}"` (`"$!{sisField}"` when the Adapter may not send the field yet, see step 4) to `vc_template.credentialSubject` (and to `credential_subject` for its display name), and add the claim to `display_order`.
3. **The context:** a new claim name needs a term in the installation's JSON-LD context (`deploy/<installation>/vdr/contexts/`), which lists every claim. Keep today's claim names where possible.
4. **SIS:** if the response has no field for it yet, write the reference quiet: `"newClaim": "$!{sisField}"`. Certify gives a quiet reference nothing when the field is missing, and a plain `${sisField}` would sign the literal text `${sisField}` (VC Lab previews it the same way, by Certify's own steps). The box stays empty until the Adapter team adds the field. Ask in their field names.

Check it in VC Lab with data that has the field.

## Publish it locally

VC Lab's Download gives a zip of the four files. To print with it from the real Wallet on the local stack, start Mimoto (`./scripts/mimoto-up.sh`), then, from the repository root:

```bash
./scripts/publish-set.sh ~/Downloads/vc-lab-set.zip AITUniversity
```

The second argument is the issuer id, the Wallet's `issuer_id` (`AITUniversity` is the AIT example). The command puts the template and the Background on the local VDR and loads the credential file into Certify, and the next Wallet print uses them. What to know before you publish:

- **Start from the Installation's own credential file** (`deploy/<installation>/certify/credentials/`) and keep its `credential_config_key_id`. The starter above is for previews only. Certify's plugin refuses any list or object in the Adapter's response except `courses`, and the sync tool unquotes only `"courses": "${courses}"`; VC Lab's preview does both too.
- **`print-check.sh --published`** prints once and keeps the PDF, but it prints the Installation's smoke credential (`ait-transcript` for AIT) and asserts the student's name is on the page.
- **"Git tracks the template" holds only when the ids match a committed file.** Publishing a set whose issuer id and credential id match a committed template replaces that tracked file: the next checkout puts it back, so a published set is a test, not a release.
- It works only on the local stack. On a deployment, placing the files is infra's step (T3).

What each step does, and how to put the committed files back: [Publish a set](./print-from-the-wallet.md#publish-a-set). To check that VC Lab's preview and the real Wallet print the same page for a set, run `./scripts/parity-check.sh`: see [section 6](./print-from-the-wallet.md#6-check-that-vc-lab-shows-what-the-wallet-prints).

## Known limits

- **Certify takes only flat fields.** Its data-provider plugin refuses any list or object in the Adapter's response except `courses` (and the lists named in `mosip.certify.adapter.structured-keys`, default `courses`); it does not unwrap `credentialSubject`. VC Lab refuses the same lists and objects (it knows only the default, `courses`), but it does unwrap a `credentialSubject` envelope in the data.
- **VC Lab's preview is the renderer's copy of Mimoto's print**, not Mimoto itself. [The renderer's README](../../src/renderer/README.md) lists what it repeats and where it differs: the QR code is a placeholder, the logo comes from the credential file, the locale is fixed to `en`, each print gets a new Velocity engine so a `#macro` body is never stale, and the order of claims outside `display_order` is not checked against the Wallet's. Certify's own variables (`${_holderId}`, `${validFrom}` and the rest) get fixed placeholders.
- **Issuing with a credential file from VC Lab:** run the sync tool with its folder mounted; see [VC Lab's README](../../src/vc-lab/README.md#issuing-with-a-credential-file-from-vc-lab).
