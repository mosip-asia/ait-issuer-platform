"""Parity: VC Lab's preview and the Wallet's print of one made-up set give the same page. Local only; made-up data.

Run it through scripts/parity-check.sh, after scripts/mimoto-up.sh. It has two steps, with the publish between them:

    parity_check.py preview --installation DIR --template FILE --out DIR [--student ID]
        builds the made-up set and runs it through VC Lab's HTTP API: uploads the template, the credential file, the
        sample and the Background one at a time, then keeps /preview.pdf as preview.pdf and /download as set.zip.
    parity_check.py compare PREVIEW WALLET
        compares the two PDFs: each page's text (whitespace collapsed), the pixel sizes of the images each page
        draws, and the names of the fonts. Any difference fails and is named.

The set exercises what the Wallet does to data. The credential file is the Installation's own (the one smoke.json
prints), with a made-up display name, courseRows mapped (a claim with no display entry), a Thai notes claim and a
programCommittee given as a list of text, and every claim in display_order (the claims it leaves out come in the
order Certify signs them, a Java HashMap's, which VC Lab doesn't reproduce). The sample is the mock Adapter's record for a made-up student, so VC Lab and
Certify fill the claims from the same data (mapped values, and courses, a list of objects). The template is
tests/fixtures/parity-template.html: every claim, the courseRows grid, the Background, the logo and a Thai font
through @font-face. The Background is print_check's made-up PNG.
"""

from __future__ import annotations

import argparse
import difflib
import io
import json
import sys
from pathlib import Path

import httpx
from pypdf import PdfReader

from map_course_rows import map_course_rows
from print_check import BACKGROUND_PX, FONT_NAME, drawn_images, make_background_png

VC_LAB = "http://lab.localhost"
ADAPTER = "http://adapter.localhost"
TIMEOUT = 120
SET_NAME = "Parity Set (made-up)"
THAI_NOTE = "ทดสอบความเท่ากัน (made-up)"
LIST_OF_TEXT = ["Dr. Ada Example", "Dr. Ben Example"]
SHOWN_DIFFERENCES = 10  # per kind; enough to name what differs without flooding the output


class Failed(Exception):
    pass


def made_up_set(installation: Path, template: Path, student: str | None) -> list[tuple[str, str, bytes]]:
    """The set's four files as (slot, file name, bytes), in the order VC Lab's dashboard takes them."""
    entry = next(e for e in json.loads((installation / "smoke.json").read_text(encoding="utf-8"))
                 if e.get("mimotoTemplate"))
    student = student or (entry["eligible"] if isinstance(entry["eligible"], str) else entry["eligible"][0])
    credential = next(c for p in sorted((installation / "certify" / "credentials").glob("*.json"))
                      if (c := json.loads(p.read_text(encoding="utf-8")))["credential_config_key_id"]
                      == entry["credentialConfig"])
    credential = map_course_rows(credential)
    credential["display"][0]["name"] = SET_NAME
    credential["display"][0].pop("background_image", None)  # the uploaded Background, then the published address
    subject = credential["vc_template"]["credentialSubject"]
    subject["notes"] = THAI_NOTE
    subject["programCommittee"] = LIST_OF_TEXT
    # Every claim in display_order. Mimoto prints the claims display_order leaves out in the order of the signed
    # credential, and Certify signs them in a Java HashMap's order, which VC Lab doesn't reproduce (docs/guides/print-from-the-wallet.md, section 6).
    credential["display_order"] = [k for k in subject if k != "id"]
    record = httpx.get(f"{ADAPTER}/student/{student}/transcript", timeout=TIMEOUT)
    if record.status_code != 200:
        raise Failed(f"setup: the mock Adapter answered {record.status_code} for {student}")
    return [
        ("template", template.name, template.read_bytes()),
        ("credential", f"{entry['credentialConfig']}.json",
         json.dumps(credential, indent=2, ensure_ascii=False).encode()),
        ("sample", f"{student}.json", record.content),
        ("background", "paper.png", make_background_png(*BACKGROUND_PX)),
    ]


def through_vc_lab(files: list[tuple[str, str, bytes]], out: Path) -> None:
    """Upload the set to VC Lab one file at a time; keep its preview and its download. VC Lab holds one set, in
    memory only, so the set it held before (a designer's work) is downloaded first and uploaded back at the end."""
    def check(resp: httpx.Response, what: str, kind: str) -> httpx.Response:
        if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith(kind):
            raise Failed(f"VC Lab: {what} answered {resp.status_code} {resp.headers.get('content-type', '')}: "
                         f"{resp.text[:400]}")
        return resp

    with httpx.Client(base_url=VC_LAB, timeout=TIMEOUT) as lab:
        held = any(check(lab.get("/api/set"), "reading the set", "application/json").json()["loaded"].values())
        # Kept in memory, as VC Lab keeps it: a Background may be an organisation's paper. Written to disk only when
        # it can't be put back.
        before = check(lab.get("/download"), "/download of the set it held", "application/zip").content if held else b""
        try:
            check(lab.delete("/api/set"), "clearing the set", "application/json")
            for slot, name, data in files:
                check(lab.post("/api/set", files={slot: (name, data)}), f"uploading the {slot}", "application/json")
            print(f"PASS VC Lab: uploaded {', '.join(f'{slot} {name}' for slot, name, _ in files)}")
            pdf = check(lab.get("/preview.pdf"), "/preview.pdf", "application/pdf").content
            (out / "preview.pdf").write_bytes(pdf)
            print(f"PASS VC Lab: /preview.pdf, {len(pdf)} bytes, saved preview.pdf")
            zipped = check(lab.get("/download"), "/download", "application/zip").content
            (out / "set.zip").write_bytes(zipped)
            print(f"PASS VC Lab: /download, {len(zipped)} bytes, saved set.zip")
        finally:
            if held:
                back = lab.post("/api/set", files={"bundle": ("vc-lab-set.zip", before)})
                if back.status_code != 200:
                    (out / "vc-lab-set-before.zip").write_bytes(before)
                    raise Failed(f"VC Lab: couldn't put back the set it held ({back.status_code}: {back.text[:200]}); "
                                 "it is saved as vc-lab-set-before.zip in the folder named above: upload it as a set")
                print("PASS VC Lab: put back the set it held before the check")
            else:
                check(lab.delete("/api/set"), "clearing the made-up set", "application/json")


def font_names(reader: PdfReader) -> set[str]:
    """Every font the pages name, embedded or built in, without the subset prefix."""
    return {str(font.get_object().get("/BaseFont", "")).lstrip("/").split("+")[-1]
            for page in reader.pages
            for font in ((page.get("/Resources") or {}).get("/Font") or {}).values()}


def page_facts(pdf: bytes) -> dict:
    """Per page, its words and the images it draws as (pixels, width, height), the width and height in points as
    drawn; and the font names of the whole PDF."""
    reader = PdfReader(io.BytesIO(pdf))
    return {
        "words": [(p.extract_text() or "").split() for p in reader.pages],
        "images": [sorted((i["px"], round(i["w"]), round(i["h"])) for i in drawn_images(reader, n))
                   for n in range(len(reader.pages))],
        "fonts": font_names(reader),
    }


def missing_features(facts: dict) -> list[str]:
    """What the made-up set prints that the preview lacks, so a loss on both sides can't pass as a match."""
    page1 = facts["images"][0] if facts["images"] else []
    text = " ".join(" ".join(words) for words in facts["words"])
    checks = [
        (FONT_NAME in facts["fonts"], f"the @font-face font {FONT_NAME} (fonts: {sorted(facts['fonts'])})"),
        (any(px == BACKGROUND_PX for px, _, _ in page1),
         f"the Background, {BACKGROUND_PX[0]}x{BACKGROUND_PX[1]} px, on page 1 (images: {page1})"),
        (any("฀" <= ch <= "๿" for ch in text), "Thai text"),
        ("TERM" in text.split(), "the courseRows grid (no TERM row)"),
        (", ".join(LIST_OF_TEXT) in text, f"the list of text joined: {', '.join(LIST_OF_TEXT)!r}"),
    ]
    return [f"VC Lab's preview lacks {what}" for present, what in checks if not present]


def differences(preview: bytes, wallet: bytes) -> dict[str, list[str]]:
    """What differs between VC Lab's preview and the Wallet's print, by kind, and what the preview lacks of the set;
    an empty list is a match."""
    a, b = page_facts(preview), page_facts(wallet)
    found: dict[str, list[str]] = {"page text": [], "image sizes": [], "font names": [],
                                   "the set's features": missing_features(a)}
    if len(a["words"]) != len(b["words"]):
        found["page text"].append(f"VC Lab has {len(a['words'])} pages, the Wallet {len(b['words'])}")
    for n, (mine, theirs) in enumerate(zip(a["words"], b["words"]), start=1):
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=mine, b=theirs, autojunk=False).get_opcodes():
            if tag != "equal":
                after = " ".join(mine[max(0, i1 - 6):i1])
                found["page text"].append(f"page {n}, after '{after}': VC Lab has {' '.join(mine[i1:i2])!r}, "
                                          f"the Wallet has {' '.join(theirs[j1:j2])!r}")
    for n, (mine, theirs) in enumerate(zip(a["images"], b["images"]), start=1):
        if mine != theirs:
            found["image sizes"].append(f"page {n}: VC Lab draws {mine}, the Wallet {theirs} "
                                        "((pixels), width and height drawn in points)")
    if a["fonts"] != b["fonts"]:
        found["font names"].append(f"only VC Lab has {sorted(a['fonts'] - b['fonts'])}, only the Wallet has "
                                   f"{sorted(b['fonts'] - a['fonts'])}")
    return found


def compare(preview: Path, wallet: Path) -> bool:
    preview_pdf, wallet_pdf = preview.read_bytes(), wallet.read_bytes()
    found = differences(preview_pdf, wallet_pdf)
    facts = page_facts(preview_pdf)
    shown = {"page text": f"the same, {len(facts['words'])} page(s), {sum(map(len, facts['words']))} words",
             "image sizes": f"the same, {facts['images']} ((pixels), width and height drawn in points, per page)",
             "font names": f"the same, {sorted(facts['fonts'])}",
             "the set's features": f"the preview shows the {FONT_NAME} font, the Background, Thai text, the "
                                   "courseRows grid and the list of text joined"}
    for kind, lines in found.items():
        if not lines:
            print(f"PASS {kind}: {shown[kind]}")
            continue
        print(f"FAIL {kind}: {len(lines)} difference(s)")
        for line in lines[:SHOWN_DIFFERENCES]:
            print(f"  {line}")
        if len(lines) > SHOWN_DIFFERENCES:
            print(f"  ... and {len(lines) - SHOWN_DIFFERENCES} more")
    return not any(found.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = parser.add_subparsers(dest="step", required=True)
    preview = steps.add_parser("preview", help="run the made-up set through VC Lab's HTTP API")
    preview.add_argument("--installation", type=Path, required=True)
    preview.add_argument("--template", type=Path, required=True)
    preview.add_argument("--out", type=Path, required=True)
    preview.add_argument("--student")
    both = steps.add_parser("compare", help="compare VC Lab's preview with the Wallet's print")
    both.add_argument("preview", type=Path)
    both.add_argument("wallet", type=Path)
    args = parser.parse_args()
    try:
        if args.step == "preview":
            through_vc_lab(made_up_set(args.installation, args.template, args.student), args.out)
            return 0
        same = compare(args.preview, args.wallet)
    except (Failed, httpx.HTTPError) as e:
        print(f"FAIL {e}")
        return 1
    print("parity: PASS" if same else "parity: FAIL: VC Lab's preview and the Wallet's print differ (above)")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
