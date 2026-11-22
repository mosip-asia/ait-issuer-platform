---
title: "How to Develop and Add a Verifiable Credential to Inji Platform"
description: "High-level architectural and step-by-step developer guide for designing and adding a new Verifiable Credential (VC) from Phase 0 (Design & Modeling) through Phase 1 (5 Core Runtime Components: VDR/CDN, Certify, VCGA, Wallet, and Verify)."
tags:
  - guide
  - design
  - vdr
  - cdn
  - certify
  - vcga
  - wallet
  - verify
---

# How to Add a Verifiable Credential to Inji Platform

This guide explains the developer and designer workflow for authoring, modeling, and deploying a new **Verifiable Credential (VC)** to the platform.

The credential lifecycle is structured into two phases:
1. **Phase 0: Credential Design & Modeling (Upstream Authoring)**: Define the claims dictionary, select the cryptographic format, craft the visual card and printable HTML template, and preview the PDF the Wallet would print (VC Lab and its renderer run from Compose; no issuer stack is needed).
2. **Phase 1: Deployment & Runtime Configuration (The 5 Core Components)**: Deploy schema, templates, and assets to VDR, configure signing engine in Certify, register in VCGA catalog, expose in Wallet, and enforce verification rules in Verify.

---

## Phase 0: Credential Design & Modeling (Upstream Authoring)

Before deploying files into Docker containers or databases, the data contract and visual presentation must be designed and verified.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       PHASE 0: CREDENTIAL DESIGN                            │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         ▼                            ▼                            ▼
┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
│ 1. Claims        │         │ 2. Visual Layout │         │ 3. Format &      │
│    Dictionary    │         │ & HTML Template  │         │ Cryptography     │
│ - Fields & Types │         │ - Wallet Card    │         │ - W3C JSON-LD vs │
│ - Mandatory vs   │         │ - Printable PDF  │         │   mso_mdoc       │
│   Optional       │         │ - Logo & Colors  │         │ - Ed25519 vs     │
└────────┬─────────┘         └────────┬─────────┘         │   ES256 P-256    │
         │                            │                   └────────┬─────────┘
         └────────────────────────────┼────────────────────────────┘
                                      │
                                      ▼ Generates 5 Artifacts
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. Schema (@context)         ──► deploy/<inst>/vdr/contexts/<vc>/v1.json    │
│ 2. Brand Artwork             ──► deploy/<inst>/vdr/assets/<logo>.png        │
│ 3. Certify Blueprint         ──► deploy/<inst>/credentials/<vc>.json        │
│ 4. Printable HTML Template   ──► deploy/base/vdr/templates/<vc>-template.html│
│ 5. Verification Rules        ──► deploy/base/verify-config.json             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 0.1 Define the Claims Dictionary
Identify the core attributes that this credential asserts:
- What attributes are required vs optional? (e.g. `studentId`, `fullName`, `faculty`, `academicProgram`).
- What data formats apply (dates, strings, arrays)?
- Which claims are public vs sensitive?

### 0.2 Select Format & Cryptographic Suite
Inji Certify natively supports three primary credential formats defined in OpenID4VCI:

| Credential Format | Standard | Data Representation | Signature Scheme | Best Used For |
|---|---|---|---|---|
| **`ldp_vc`** | W3C VCDM 2.0 | JSON-LD text with `@context` | Linked Data Proofs (`Ed25519Signature2020` / EdDSA) | Academic transcripts, web wallets (Inji Web), cloud PDF verification |
| **`mso_mdoc`** | ISO/IEC 18013-5 | Binary CBOR (Mobile Security Object) | COSE (`COSE_Sign1` with `ES256` ECDSA P-256) | Student ID cards, Apple Wallet, Google Wallet, offline NFC/BLE gate turnstiles |
| **`vc+sd-jwt`** | IETF SD-JWT VC | Base64url JSON Web Tokens | JWS (`ES256` / `RS256`) with SHA-256 disclosure digests | Fine-grained field-by-field selective disclosure in browser wallets |

### 0.3 Design Visual Assets & HTML Template
Credentials typically require two visual presentations:
1. **Wallet Card Display**: Thumbnail styling in the wallet catalog (`background_color`, `text_color`, logo URI).
2. **Printable Document / Certificate Layout**: The printable document is an **Apache Velocity HTML template** (e.g. [`deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html`](../../deploy/ait/vdr/templates/AITUniversity-ait-transcript-template.html) or [`deploy/base/vdr/templates/credential-template.html`](../../deploy/base/vdr/templates/credential-template.html)):
   - Defines page geometry (`@page { size: A4 portrait; margin: 10mm; }`).
   - Uses a macro such as `#macro(claimText $claimName)` and `#claimText("fieldName")` to bind claims: the template defines the macro itself, under a name new to the Wallet (the macro and the naming rule are in [VC Lab templates](./vc-lab-templates.md); the committed AIT template already defines `claimValue`, so do not reuse that name).
   - Embeds `$qrCodeImage` for instant scan-to-verify functionality.

### 0.4 Visual Credential Studio & Wallet Preview (VC Lab)

Use **VC Lab Studio** (`src/vc-lab/`) to design, render, and inspect your credential before deployment:

Open the live VC Lab studio:
- **Dashboard URL:** [http://lab.localhost](http://lab.localhost)
- Upload the template, the credential file and a sample Adapter response; VC Lab shows the PDF the Wallet would print, drawn by the renderer from the same template. It reads nothing from the repo; see [`src/vc-lab/README.md`](../../src/vc-lab/README.md).

---

## Phase 1: Deploy to the 5 Core Components (Runtime Configuration)

Once the schema, template, and visual assets are designed, deploy them across the **five core components** in natural dependency order:

```
┌──────────────────────────────────────────────┐
│ 1. VDR (vdr.localhost)                       │  ◄── 1. Define schema & visual assets first
│    contexts/<vc> & assets/<logo>             │
└──────────────────────┬───────────────────────┘
                       │ resolves schema
                       ▼
┌──────────────────────────────────────────────┐
│ 2. Inji Certify (issuer.localhost)           │  ◄── 2. Configure credential blueprint & keys
│    credentials/<vc>.json                     │
└──────────────────────┬───────────────────────┘
                       │ published to
                       ▼
┌──────────────────────────────────────────────┐
│ 3. VCGA (vcga.localhost)                     │  ◄── 3. Register issuer in wallet catalog
│    mimoto-issuers-config.json                │
└──────────────────────┬───────────────────────┘
                       │ discovers issuer
                       ▼
┌──────────────────────────────────────────────┐              ┌──────────────────────────────┐
│ 4. Wallet (wallet.localhost)                 │   presents   │ 5. Inji Verify               │
│    claims & stores credential                ├─────────────►│    (verifier.localhost)      │
│                                              │              │    validates signature/schema│
└──────────────────────────────────────────────┘              └──────────────────────────────┘
```

| Component | Responsibility | Configuration Artifact | Validation Command |
|---|---|---|---|
| **1. VDR** | JSON-LD schema, templates & brand assets | `deploy/<inst>/vdr/contexts/<vc>/v1.json` | `curl -s http://vdr.localhost/contexts/<vc>/v1.json` |
| **2. Certify** | Issuer engine, signing keys, status lists | `deploy/<inst>/credentials/<vc>.json` | `curl -s http://issuer.localhost/.well-known/openid-credential-issuer` |
| **3. VCGA** | Trusted issuer catalog for wallet discovery | `deploy/<inst>/vcga/issuers.json` | `curl -s http://vcga.localhost/issuers` |
| **4. Wallet** | Digital wallet (Inji Web / Mobile) | Card display properties & template | `curl -s http://wallet.localhost/v1/mimoto/issuers/.../configuration` |
| **5. Verify** | Signature & schema verification | `deploy/base/verify-config.json` | `curl -s -X POST http://verifier.localhost/v1/verify/v2/vc-verification` |

---

## 1. Configure VDR (Schemas, Templates & Assets)

**Role**: Before an issuer can sign a credential or a verifier can inspect it, the cryptographic schema, rendering templates, and visual branding must exist at permanent, resolvable URIs.
- **VDR (`http://vdr.localhost`)**: Serves W3C JSON-LD `@context` schemas, templates, and brand artwork from `deploy/${INSTALLATION}/vdr/`.

### 1.1 What to Configure

1. **Context Schema**: Create the JSON-LD `@context` file at `deploy/<installation>/vdr/contexts/<vc-name>/v1.json`:
```json
{
  "@context": {
    "@version": 1.1,
    "@protected": true,
    "<prefix>": "https://vdr.example.org/contexts/<vc-name>/v1.json#",
    "<CredentialType>": "<prefix>:<CredentialType>",
    "field1": "<prefix>:field1",
    "field2": "<prefix>:field2"
  }
}
```

2. **Brand Assets**: Place your credential logo at `deploy/<installation>/vdr/assets/<logo>.png`.

3. **Single Source of Truth with Configurable Origin**:
Credential JSON blueprints in `deploy/<inst>/credentials/*.json` use clean local domain URLs (`http://vdr.localhost`) so local development works 100% offline without external dependencies or `/etc/hosts` modifications:
- **Local VDR Schema URI**: `"http://vdr.localhost/contexts/<vc-name>/v1.json"`
- **Local VDR Asset URI**: `"http://vdr.localhost/assets/<logo>.png"`

When deploying to production or staging, `certify-template-sync` automatically substitutes `VDR_BASE_URL=https://vdr.dpi.ait.ac.th` when synchronizing into PostgreSQL.

| Role | Local Clean URL (*.localhost) | Institutional Production Domain | Internal Container Port |
|---|---|---|---|
| **VDR (Trust Registry)** | `http://vdr.localhost` | `https://vdr.dpi.ait.ac.th` | `80` |
| **VCGA (Catalog)** | `http://vcga.localhost` | `https://vcga.dpi.ait.ac.th` | `80` |
| **Issuer Engine** | `http://issuer.localhost` | `https://issuer.dpi.ait.ac.th` | `80` |
| **Verifier UI** | `http://verifier.localhost` | `https://verifier.dpi.ait.ac.th` | `8000` |
| **Web Wallet** | `http://wallet.localhost` | `https://wallet.dpi.ait.ac.th` | `3004` |
| **VC Lab Studio** | `http://lab.localhost` | `https://lab.dpi.ait.ac.th` | `4200` |

In local development:
- **Zero-Config Domain Ingress (Traefik v3.7)**: All `*.localhost` domains (RFC 6761) resolve natively to `127.0.0.1` on port 80 without modifying `/etc/hosts` or exposing individual host ports.
- **Inside Docker**: `compose.certify.yaml`, `compose.verify.yaml`, and `compose.web-wallet.yaml` map `*.localhost` to `host-gateway` via `extra_hosts` so containers and browsers resolve the exact same URLs.

### 1.2 How to Validate VDR

#### Validate Schema:
```bash
curl -s http://vdr.localhost/contexts/<vc-name>/v1.json | jq .
```
*Expected: Returns HTTP 200 with the valid JSON-LD `@context` document.*

#### Validate Asset:
```bash
curl -s -I http://vdr.localhost/assets/<logo>.png
```
*Expected: Returns HTTP 200 with `Content-Type: image/png` and CORS header `Access-Control-Allow-Origin: *`.*

---

## 2. Configure Inji Certify (Issuer Engine)

**Role**: Certify is the cryptographic signing engine. It loads credential configurations from PostgreSQL (`certify.credential_config`), evaluates templates or claims mappings, and signs credentials using its configured keys.

### 2.1 Format A: W3C JSON-LD (`ldp_vc`)

Create `deploy/<installation>/credentials/<credential-id>.json`:

```json
{
  "credential_config_key_id": "<credential-id>",
  "status": "active",
  "scope": "<credential_scope>_vc_ldp",
  "credential_type": "<CredentialType>,VerifiableCredential",
  "credential_format": "ldp_vc",
  "context": [
    "http://vdr.localhost/contexts/<vc-name>/v1.json",
    "https://www.w3.org/ns/credentials/v2"
  ],
  "did_url": "did:key:z6MkpPLACEHOLDERreplaceMeViaBootstrapDidRefreshScript1",
  "key_manager_app_id": "CERTIFY_VC_SIGN_ED25519",
  "key_manager_ref_id": "ED25519_SIGN",
  "signature_algo": "EdDSA",
  "signature_crypto_suite": "Ed25519Signature2020",
  "display": [
    {
      "name": "Human Friendly Credential Name",
      "locale": "en",
      "logo": {
        "url": "http://vdr.localhost/assets/<logo>.png",
        "alt_text": "Logo"
      },
      "background_color": "#005696",
      "text_color": "#FFFFFF"
    }
  ],
  "display_order": ["field1", "field2"],
  "cryptographic_binding_methods_supported": ["did:jwk"],
  "credential_signing_alg_values_supported": ["Ed25519Signature2020"],
  "proof_types_supported": {
    "jwt": {
      "proof_signing_alg_values_supported": ["RS256", "ES256"]
    }
  },
  "credential_status_purpose": ["revocation"],
  "credential_subject": {
    "field1": { "display": [{ "name": "Field 1", "locale": "en" }] },
    "field2": { "display": [{ "name": "Field 2", "locale": "en" }] }
  },
  "vc_template": {
    "@context": [
      "https://www.w3.org/ns/credentials/v2",
      "http://vdr.localhost/contexts/<vc-name>/v1.json",
      "https://w3id.org/security/suites/ed25519-2020/v1"
    ],
    "issuer": "${_issuer}",
    "type": ["VerifiableCredential", "<CredentialType>"],
    "validFrom": "${validFrom}",
    "validUntil": "${validUntil}",
    "credentialStatus": {
      "id": "${credentialStatus.id}",
      "type": "${credentialStatus.type}",
      "statusPurpose": "${credentialStatus.statusPurpose}",
      "statusListIndex": "${credentialStatus.statusListIndex}",
      "statusListCredential": "${credentialStatus.statusListCredential}"
    },
    "credentialSubject": {
      "id": "${_holderId}",
      "field1": "${field1}",
      "field2": "${field2}"
    }
  }
}
```

---

### 2.2 Format B: ISO/IEC 18013-5 Mobile Document (`mso_mdoc`)

Create `deploy/<installation>/credentials/<credential-id>-mdoc.json`:

```json
{
  "credential_config_key_id": "<credential-id>-mdoc",
  "status": "active",
  "scope": "<credential_scope>_mdoc",
  "credential_format": "mso_mdoc",
  "doctype": "org.iso.18013.5.1.<doctype>",
  "key_manager_app_id": "CERTIFY_VC_SIGN_EC_R1",
  "key_manager_ref_id": "EC_SECP256R1_SIGN",
  "signature_algo": "ES256",
  "signature_crypto_suite": "ES256",
  "cryptographic_binding_methods_supported": [
    "cose_key"
  ],
  "credential_signing_alg_values_supported": [
    "ES256"
  ],
  "proof_types_supported": {
    "jwt": {
      "proof_signing_alg_values_supported": ["ES256"]
    }
  },
  "display": [
    {
      "name": "Mobile Document Name",
      "locale": "en",
      "logo": {
        "url": "http://vdr.localhost/assets/<logo>.png",
        "alt_text": "Logo"
      },
      "background_color": "#005696",
      "text_color": "#FFFFFF"
    }
  ],
  "display_order": ["field1", "field2"],
  "mso_mdoc_claims": {
    "org.iso.18013.5.1.<namespace>": {
      "field1": {
        "mandatory": true,
        "display": [{ "name": "Field 1", "locale": "en" }]
      },
      "field2": {
        "mandatory": false,
        "display": [{ "name": "Field 2", "locale": "en" }]
      }
    }
  }
}
```

---

### 2.3 Synchronize to PostgreSQL
Apply the credential JSON to Certify's database without wiping keys or ledger records:
```bash
# Using modern Python CLI:
uv run certify-template-sync --apply

# Or via Docker Compose:
docker compose -f compose.certify.yaml run --rm template-sync
```

### 2.4 How to Validate Inji Certify

#### Validation Command 1: OpenID4VCI Issuer Discovery
Query Certify's discovery metadata to ensure the credential is active:
```bash
curl -s http://issuer.localhost/.well-known/openid-credential-issuer | jq '.credential_configurations_supported["<credential-id>"]'
```
*Expected: Returns the JSON configuration object with matching format and scope.*

#### Validation Command 2: Database Table Verification
Confirm the row exists in PostgreSQL:
```bash
docker compose -f compose.certify.yaml exec -T database \
  psql -U postgres -d inji_certify -c \
  "SELECT credential_config_key_id, status, scope FROM certify.credential_config WHERE credential_config_key_id = '<credential-id>';"
```
*Expected: `1 row` with `status: active`.*

---

## 3. Configure VCGA (Issuers Catalog)

**Role**: Verifiable Credentials Global Architecture (VCGA) serves `issuers.json` at `http://vcga.localhost/issuers`. Wallets query this catalog to discover issuers and their OpenID4VCI endpoints.

### 3.1 What to Configure
In `deploy/<installation>/vcga/issuers.json`, ensure your issuer is listed and enabled:
```json
{
  "issuers": [
    {
      "credential_issuer": "AITUniversity",
      "issuer_id": "AITUniversity",
      "protocol": "OpenId4VCI",
      "display": [
        {
          "name": "AIT University Registrar",
          "title": "AIT University",
          "description": "Download your AIT credentials",
          "language": "en"
        }
      ],
      "enabled": "true",
      "wellknown_endpoint": "http://host.docker.internal:9091/.well-known/openid-credential-issuer"
    }
  ]
}
```

### 3.2 How to Validate VCGA
Query the static VCGA catalog server:
```bash
curl -s http://vcga.localhost/mimoto-issuers-config.json | jq '.issuers[] | {issuer_id, wellknown_endpoint, enabled}'
```
*Expected: Returns HTTP 200 with `enabled: "true"` and points to Certify's `.well-known` endpoint.*

---

## 4. Configure Wallet (Inji Web)

**Role**: Inji Web connects to VCGA, loads the issuer catalog, allows users to request VCs, and displays cards.

### 4.1 What to Configure
- **Branding**: Configured in Certify's `deploy/<inst>/credentials/<vc>.json` under `display` (wallet automatically reads this).
- **Display Order**: Configured under `display_order` and `credential_subject` in the credential JSON.
- **Visual Card (Optional)**: If custom visual printing or styling is required, provide `deploy/base/<Issuer>-<vc-name>-template.html`.

### 4.2 How to Validate Wallet Readiness

#### Validation Command 1: Wallet Issuer Discovery
Verify that Inji Web can read the issuer from VCGA:
```bash
curl -s http://wallet.localhost/v1/mimoto/issuers | jq .
```
*Expected: Lists your configured issuer.*

#### Validation Command 2: Wallet Credential Catalog Proxy
Verify that Inji Web proxies Certify's credential configurations:
```bash
curl -s http://wallet.localhost/v1/mimoto/issuers/<IssuerId>/configuration | jq '.credential_configurations_supported["<credential-id>"]'
```
*Expected: Returns the credential configuration. If this succeeds, the credential will render in the Inji Web UI catalog.*

---

## 5. Configure Inji Verify

**Role**: Inji Verify validates digital signatures against the issuer's public key (`did:key`), checks schema compliance against VDR, and renders verified claims.

### 5.1 What to Configure
Edit `deploy/base/verify-config.json`:

1. **Add to `verifiableClaims`**:
```json
{
  "logo": "/assets/cert.png",
  "name": "Human Readable Name",
  "type": "<CredentialType>",
  "clientIdScheme": "did",
  "definition": {
    "purpose": "Verification of credential",
    "format": {
      "ldp_vc": {
        "proof_type": ["Ed25519Signature2020"]
      }
    },
    "input_descriptors": [
      {
        "id": "<credential-id>",
        "format": {
          "ldp_vc": {
            "proof_type": ["Ed25519Signature2020"]
          }
        },
        "constraints": {
          "fields": [
            {
              "path": ["$.type"],
              "filter": {
                "type": "object",
                "pattern": "<CredentialType>"
              }
            }
          ]
        }
      }
    ]
  }
}
```

2. **Add to `VCRenderOrders`**:
```json
"<CredentialType>RenderOrder": [
  "field1",
  "field2"
]
```

### 5.2 How to Validate Inji Verify
Send a verification request with an issued credential JSON:
```bash
curl -s -X POST "http://verifier.localhost/v1/verify/v2/vc-verification" \
  -H "Content-Type: application/json" \
  -d '{
    "verifiableCredential": "<PASTE_CREDENTIAL_JSON>",
    "skipStatusChecks": true
  }' | jq .
```
*Expected Output:*
```json
{
  "allChecksSuccessful": true,
  "schemaAndSignatureCheck": {
    "status": "SUCCESS"
  }
}
```

---

## 6. End-to-End Validation Checklist

Run through these six commands in order to confirm complete readiness:

```bash
# 1. VDR Context is served:
curl -s -f http://vdr.localhost/contexts/<vc-name>/v1.json > /dev/null && echo "✅ 1. VDR OK"

# 2. VDR Asset is served:
curl -s -f http://vdr.localhost/assets/<logo>.png > /dev/null && echo "✅ 2. VDR Asset OK"

# 3. VCGA Catalog is served:
curl -s -f http://vcga.localhost/mimoto-issuers-config.json > /dev/null && echo "✅ 3. VCGA OK"

# 4. Certify recognizes the credential:
curl -s -f http://issuer.localhost/.well-known/openid-credential-issuer | jq -e '.credential_configurations_supported["<credential-id>"]' > /dev/null && echo "✅ 4. Certify OK"

# 5. Wallet proxies the credential:
curl -s -f http://wallet.localhost/v1/mimoto/issuers/<IssuerId>/configuration | jq -e '.credential_configurations_supported["<credential-id>"]' > /dev/null && echo "✅ 5. Wallet OK"

# 6. Verify service is healthy:
curl -s -f http://verifier.localhost/actuator/health > /dev/null && echo "✅ 6. Verify OK"
```
