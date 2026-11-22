# Credential templates in VC Lab

How to write a template that prints right in the Wallet the first time. VC Lab ([`src/vc-lab/`](../../src/vc-lab/README.md)) has one view: the PDF the Wallet prints. Its preview is drawn by the [renderer](../../src/renderer/README.md), which runs the Wallet's own print path (Mimoto 0.21), so what you see is what the Wallet prints.

Every snippet below was previewed through VC Lab with made-up data. Thas owns this guide; Thas's team keeps it working.

## How a value reaches the page

```
SIS response ──(credential file: vc_template)──► claims ──(template)──► page
 "studentId": "st990001"   "registrationNo": "${studentId}"   $rowProperties.get("registrationNo")
```

1. **Certify** reads the Adapter's (SIS's) response and fills the credential file's `vc_template` with it (Apache Velocity). The right side names a field of the response (`${studentId}`); the left side is the claim name the issued credential carries (`registrationNo`).
2. **Mimoto**, the Wallet's backend, prints the credential with your template (Velocity 1.7, then iText html2pdf 5.0.3). The template reads claim names, the left side of the mapping, never SIS field names.
3. **VC Lab** maps the uploaded data to claims the same way (`src/vc-lab/template_engine.py`) and has the renderer print them, so you can check a template without issuing anything.

## The four files

| File | Extension | What it is | If missing |
|---|---|---|---|
| Template | `.html`, A4 | HTML with Velocity | nothing renders |
| Credential file | `.json` | Certify's credential file; `vc_template.credentialSubject` is the mapping, `display` and `display_order` shape the print | nothing renders |
| Data (the API's `sample`) | `.json` | one record, as the Adapter sends it, with or without a `credentialSubject` envelope | nothing renders; a field it lacks prints empty |
| Background | `.png` or `.jpg` | a picture of the organisation's paper (watermark, seal, signature) | optional: the preview uses the credential file's `display[0].background_image.uri`, or draws none |

The Background reaches the template as `$backgroundImage`. A Background may be confidential and VC Lab has no login: upload it only on a VC Lab on your own machine, and never commit it.

**Rotate a photo before you upload it.** A JPEG can carry an EXIF "orientation" tag that tells a viewer to turn it. Mimoto and VC Lab both ignore the tag, so a phone photo of the paper prints sideways. Open the picture, rotate it until the paper is upright, and save it again, so the pixels themselves are upright. Check it in VC Lab's preview.

A small set to start from (made-up data). The credential file:

```json
{
  "credential_config_key_id": "example-card",
  "display": [
    { "name": "Example Card", "locale": "en", "text_color": "#000000", "background_color": "#ffffff" }
  ],
  "display_order": ["registrationNo", "fullName"],
  "credential_subject": {
    "registrationNo": { "display": [{ "name": "Registration No.", "locale": "en" }] },
    "fullName": { "display": [{ "name": "Full Name", "locale": "en" }] },
    "honours": { "display": [{ "name": "Honours", "locale": "en" }] },
    "courses": { "display": [{ "name": "Courses", "locale": "en" }] }
  },
  "vc_template": {
    "credentialSubject": {
      "registrationNo": "${studentId}",
      "fullName": "${fullName}",
      "honours": "${honours}",
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
  "honours": ["Dean's list", "Cum laude"],
  "courses": [{ "no": "CS101", "grade": "A" }],
  "courseRows": "T|Term 1|6|3.50|3.50\nC|CS101|Intro to Computing|0|45|3|A\nC|CS102|Algorithms|0|45|3|"
}
```

## What the Wallet does to your data

Mimoto prepares the claims before your template sees them. Write the template for what it hands over, not for what the credential holds.

- **Every claim is there.** The template gets all of them as `$rowProperties`: claim name, to display name, to text. A claim with no display name in the credential file still arrives, under its name in title case (`courseRows` shows as `Course Rows`).
- **`display_order` sets the order** of `$rowProperties`: the claims it lists come first, in its order, then the rest. A loop over `$rowProperties` prints them in that order.
- **`formatValue` flattens each value to text:**
  - text and numbers stay as they are (`3.0` prints `3.0`);
  - an object becomes its `value` field;
  - a list of text is joined with `", "` (`Dean's list, Cum laude`);
  - a list of objects becomes `""`. A template can't loop over `courses`: see "Rows" below.

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
#macro(claimValue $claimName)
#set($__claim = "")
#set($__claim = $rowProperties.get($claimName))
#if($__claim && $__claim.size() > 0)
#foreach($__entry in $__claim.entrySet())$__entry.value#break#end
#end
#end
```

The first `#set` to `""` is needed: Velocity 1.7 keeps a variable's old value when `#set` is given null, so without it a missing claim would print the previous claim's value (macro variables are shared by every call). Then `#claimValue("fullName")` where the value goes. The Wallet's Velocity engine is shared by every print and keeps the first body it saw for a macro name, so when you change a macro's body, give it a new name (see [print from the Wallet](./print-from-the-wallet.md#4-swap-a-template)).

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

**Keep the layout out of the page box's flow.** A flowing block such as a `<p>` with a top margin, placed as the first child of `.page`, has that margin collapse through the box and push the whole box, Background included, down (a 12 pt margin moved the image 12 pt off the top). Put the layout in an absolutely placed box, as `.content` is above, whose margins stay inside it. Nothing then sits in `.page` but the image and that box.

### Rows: delimited text and the split idiom

A list of objects reaches the template as `""`, so a template can't loop over `courses`. Anything drawn as rows must reach the credential as one text claim (here `courseRows`): one line per row, `|` between fields, no field holding `|` or a line break. The template splits it:

```velocity
#set($cr = "")
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
- **Set the variable to `""` first.** Velocity 1.7 keeps the old value when `#set` is given null, so for a claim the credential lacks, `$cr` would keep the previous text. The `#set($cr = "")` line is what stops that.
- **Place a table through a `<div>`.** iText honours `position: absolute` with `left` and `top` on a `<div>`. On a `<table>` it honours `left` but ignores `top`: the table lands at the top of the box it sits in. Put the table in an absolutely placed `<div>` and leave the table static.

For the transcript, the Adapter's `courseRows` format and what the template does with it are in [print from the Wallet](./print-from-the-wallet.md#t4-courserows-a-text-copy-of-the-course-grid) (an AIT example).

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

Put `<meta charset="UTF-8"/>` in the `<head>` and save the file as UTF-8. Text typed into a template (Thai, accents) is read by Mimoto as ISO-8859-1 unless the VDR serves the template with `charset=utf-8` (ask T2 in [print from the Wallet](./print-from-the-wallet.md#t2-mimoto-reads-its-files-from-the-vdr)). The safe form is an HTML entity:

```html
<p>&#x0E20;&#x0E32;&#x0E29;&#x0E32;&#x0E44;&#x0E17;&#x0E22;</p>
```

VC Lab prints raw Thai correctly, because it hands the renderer the file as UTF-8, so its preview can look right where the Wallet's print would not: use entities for text typed into the template. Claim values are not affected: they arrive as the credential holds them.

More about how these conventions follow from Mimoto, and the asks T2 to T4: [Template conventions](./print-from-the-wallet.md#template-conventions) in the print guide.

## Adding or changing a box

1. **The template:** place `#claimValue("newClaim")` where the value goes.
2. **The credential file:** add `"newClaim": "${sisField}"` to `vc_template.credentialSubject` (and to `credential_subject` for its display name).
3. **The context:** a new claim name needs a term in the installation's JSON-LD context (`deploy/<installation>/vdr/contexts/`), which lists every claim. Keep today's claim names where possible.
4. **SIS:** if the response has no field for it, the box stays empty until the Adapter team adds one. Ask in their field names.

Check it in VC Lab with data that has the field.

## Publish it locally

VC Lab's Download gives a zip of the four files. To print with it from the real Wallet on the local stack, start Mimoto (`./scripts/mimoto-up.sh`), then, from the repository root:

```bash
./scripts/publish-set.sh ~/Downloads/set.zip AITUniversity
```

The second argument is the issuer id, the Wallet's `issuer_id` (`AITUniversity` is the AIT example). The command puts the template and the Background on the local VDR and loads the credential file into Certify, and the next Wallet print uses them. Run `./scripts/print-check.sh --published` to print once and keep the PDF. It works only on the local stack, and git tracks the template file it replaces, so a published set is a test, not a release. On a deployment, placing the files is infra's step (T3). What each step does, and how to put the committed files back: [Publish a set](./print-from-the-wallet.md#publish-a-set).

## Known limits

- **Certify takes only flat fields.** Its data-provider plugin passes the Adapter's top-level fields and lists named in `mosip.certify.adapter.structured-keys` (default `courses`); it refuses nested objects and does not unwrap `credentialSubject`. VC Lab accepts both, so a mapping that reads `${thesis.title}` works in VC Lab but not yet in Certify.
- **Numbers print as sent.** A credit sent as `3.0` prints `3.0`.
- **VC Lab's preview is the renderer's copy of Mimoto's print**, not Mimoto itself. [The renderer's README](../../src/renderer/README.md) lists what it repeats and where it differs (the QR code is a placeholder, the logo comes from the credential file, each print gets a new Velocity engine so a `#macro` body is never stale).
- **Issuing with a credential file from VC Lab:** run the sync tool with its folder mounted; see [VC Lab's README](../../src/vc-lab/README.md#issuing-with-a-credential-file-from-vc-lab).
