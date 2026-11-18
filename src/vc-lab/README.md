# VC Lab: Verifiable Credential Design & Authoring Studio

**VC Lab** is the dedicated module and toolkit for **VC Developers** and **VC Operators** to author, model, preview, and export Verifiable Credentials (VCs) before deploying them to the runtime infrastructure.

---

## 1. Core Responsibilities

VC Lab empowers credential designers and operators across three primary workflows:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   VC LAB                                    │
│                 (Credential Design, Authoring & Versioning)                 │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ 1. Schema &      │         │ 2. HTML Template │         │ 3. Visual & UI   │
│    Data Contract │         │    & Rendering   │         │    Presentation  │
│ - Versioned      │         │ - Apache Velocity│         │ - Wallet Card    │
│   @context JSON  │         │   Layouts        │   Thumbnails     │
│ - Certify        │         │ - Offline Live   │ - Verify Input   │
│   Blueprints     │         │   Preview Engine │   Descriptors    │
│ - Canonical URIs │         │ - A4 Page Grid   │ - Claim Render   │
│   (v1, v2...)    │         │   & Verification │   Orders         │
│                  │         │   QR Code        │                  │
└────────┬─────────┘         └────────┬─────────┘         └────────┬─────────┘
         │                            │                            │
         ▼                            ▼                            ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ Export Target:   │         │ Export Target:   │         │ Export Target:   │
│ deploy/<tenant>/ │         │ deploy/<tenant>/ │         │ deploy/base/     │
│ vdr/contexts/    │         │ vdr/templates/   │         │ verify-config    │
│ credentials/<vc> │         │                  │         │ .json            │
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

### 1. Define / Render / Export Schema (Version-Controlled)
- **W3C JSON-LD `@context` Definitions**: Authors schema definitions with immutable canonical URIs under institutional production domains (e.g. `https://vdr.dpi.ait.ac.th/contexts/<vc>/v1.json`). Versioning is strictly controlled via directory increments (`v1.json`, `v2.json`).
- **Inji Certify Blueprints**: Exports credential configurations (`deploy/<tenant>/credentials/<vc>.json`) with matching `scope`, `credential_format` (`ldp_vc` or `mso_mdoc`), signing algorithms (`Ed25519Signature2020` or `ES256`), and velocity template mappings (`vc_template`).

### 2. Define / Render / Export HTML Template (Version-Controlled)
- **Printable Certificate & Transcript Layouts**: Creates Apache Velocity templates (e.g. `deploy/<tenant>/vdr/templates/<Issuer>-<vc>-template.html`) styled for A4 portrait printing with precise margins, typography, and borders.
- **Offline Template Preview Engine**: Evaluates `#macro(claimValue $claimName)`, `#if ... #else ... #end`, and `$rowProperties` to generate instant preview HTML files from mock student personas (`tests/fixtures/students.json`) without running Docker or backend services.

### 3. Define / Render / Export Visual Presentation & Button Renders
- **Wallet Card Display**: Generates the display JSON properties (`display`, `display_order`, background color, text color, and logo) for Inji Web and Inji Mobile card lists.
- **Inji Verify Button & Descriptors**: Exports verification rule blocks for `deploy/base/verify-config.json` (`verifiableClaims` descriptor, proof format checks, and `<CredentialType>RenderOrder`).

---

## 2. In-Memory Velocity Template Engine (`template_engine.py`)

VC Lab includes a pure-Python Velocity template engine for live rendering in the studio dashboard and REST APIs without requiring Java, Inji Certify, or Docker.

It supports `#claimValue`, `#if`/`#else`, and `#foreach($x in $list)` over lists in the context, with `$x.field` access and nested loops. Besides Mimoto's variables, VC Lab passes two of its own (`lab_context`), and the transcript template uses each only inside an `#if`, so Mimoto, which has neither, falls back:
- `$terms` is the `courses` claim as a list, so the template can draw the semester table. Mimoto 0.21 hands that claim to Velocity as `""`, so its PDF falls back to `courseList`.
- `$backgroundUrl` is the HTML preview's background image.

### Running Unit Tests:
```bash
python3 src/vc-lab/test_template_engine.py
.venv/bin/python src/vc-lab/test_main.py
```

The PDF test in `test_main.py` needs WeasyPrint's system libraries (Pango). It runs in the `ait-vc` image and is skipped on a host without them.

---

## Hard-copy PDF and backgrounds (`hardcopy.py`)

AIT prints a transcript in two passes: first the watermark paper (the "AIT" pattern, the seal and the Director's signature), then the information. VC Lab does the same in one PDF:
- **Background** (the dashboard's "Background" card, or `POST /api/background` with `template`, `rotation` and `file`). Upload a PDF, PNG or JPEG for the selected template. It is used as uploaded, page 1 only, turned clockwise by the chosen rotation and fitted on a portrait A4 page. A PDF's own page rotation counts, so AIT's watermark PDF needs 0°. The default is no background, which gives the information only, for printing on pre-printed paper.
- **Export PDF** (`GET /export.pdf?template=…&student=…`). The template rendered with the mock student, through WeasyPrint, with the background laid under page 1 as a PDF layer. `hardcopy.render_pdf` is the same function the Portal's hard copy calls.
- **Download template** (`GET /download?template=…`). A zip of the template file, plus the background as uploaded and its rotation (`background/background.json`).

> **A background such as AIT's watermark is confidential.** VC Lab keeps backgrounds in memory only: they are never written to the mounted folders, git or the VDR, never put in the template that wallets use, and a restart forgets them. VC Lab has no login, and Traefik routes it on a Host header anyone can send. **Upload a confidential background only on a VC Lab running on your own machine, never on a deployed one.**

---

## 3. Docker Service & Compose Integration

VC Lab is containerized with [`docker/Dockerfile.ait-vc`](../../docker/Dockerfile.ait-vc) and runs as a service in [`compose.yaml`](../../compose.yaml).

### Running with Docker:
```bash
# Start the VC Lab studio container:
docker compose up -d vc-lab

# Access the interactive Web Studio:
open http://lab.localhost
```

---

## 4. Directory Layout

```
src/vc-lab/
├── README.md                  # Module architecture & developer documentation
├── main.py                    # FastAPI Web Studio & REST API server
├── template_engine.py         # In-memory Velocity template parser and QR generator
├── test_main.py               # Unit tests for FastAPI studio endpoints
└── test_template_engine.py    # Unit test suite verifying template rendering
```
