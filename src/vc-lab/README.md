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
│ contexts/<vc>/   │         │ *-template.html  │         │ verify-config    │
│ credentials/<vc> │         │                  │         │ .json            │
└──────────────────┘         └──────────────────┘         └──────────────────┘
```

### 1. Define / Render / Export Schema (Version-Controlled)
- **W3C JSON-LD `@context` Definitions**: Authors schema definitions with immutable canonical URIs under institutional production domains (e.g. `https://vdr.dpi.ait.ac.th/contexts/<vc>/v1.json`). Versioning is strictly controlled via directory increments (`v1.json`, `v2.json`).
- **Inji Certify Blueprints**: Exports credential configurations (`deploy/<tenant>/credentials/<vc>.json`) with matching `scope`, `credential_format` (`ldp_vc` or `mso_mdoc`), signing algorithms (`Ed25519Signature2020` or `ES256`), and velocity template mappings (`vc_template`).

### 2. Define / Render / Export HTML Template (Version-Controlled)
- **Printable Certificate & Transcript Layouts**: Creates Apache Velocity templates (e.g. `deploy/<tenant>/<Issuer>-<vc>-template.html`) styled for A4 portrait printing with precise margins, typography, and borders.
- **Offline Template Preview Engine**: Evaluates `#macro(claimValue $claimName)`, `#if ... #else ... #end`, and `$rowProperties` to generate instant preview HTML files from mock student personas (`tests/fixtures/students.json`) without running Docker or backend services.

### 3. Define / Render / Export Visual Presentation & Button Renders
- **Wallet Card Display**: Generates the display JSON properties (`display`, `display_order`, background color, text color, and logo) for Inji Web and Inji Mobile card lists.
- **Inji Verify Button & Descriptors**: Exports verification rule blocks for `deploy/base/verify-config.json` (`verifiableClaims` descriptor, proof format checks, and `<CredentialType>RenderOrder`).

---

## 2. In-Memory Velocity Template Engine (`template_engine.py`)

VC Lab includes a pure-Python Velocity template engine for live rendering in the studio dashboard and REST APIs without requiring Java, Inji Certify, or Docker.

### Running Unit Tests:
```bash
python3 src/vc-lab/test_template_engine.py
.venv/bin/python src/vc-lab/test_main.py
```

---

## 3. Docker Service & Compose Integration

VC Lab is containerized with [`docker/Dockerfile.vc-lab`](../../docker/Dockerfile.vc-lab) and runs as a service in [`compose.yaml`](../../compose.yaml).

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
