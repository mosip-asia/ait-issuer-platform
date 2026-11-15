---
title: "How to Add a Verifiable Credential: 5-Component Architectural Guide"
description: "Step-by-step architectural guide explaining how to configure and validate each of the 5 core components (VDR/CDN, Certify, VCGA, Wallet, Verify) in natural dependency order to add a new Verifiable Credential like the Student ID Card."
tags:
  - guide
  - certify
  - vcga
  - vdr
  - wallet
  - verify
  - student-card
---

# How to Add a Verifiable Credential: 5-Component Architectural Guide

To add a new Verifiable Credential (such as the **AIT Student ID Card**, `AitStudentIdCredential`), you configure **five core components** in natural dependency order:

```
┌─────────────────────────────────┐
│ 1. VDR & CDN (Trust :9098/97)   │  ◄── 1. Define schema & visual assets first
│    contexts/<vc> & assets/<logo>│
└──────────────┬──────────────────┘
               │ resolves schema
               ▼
┌─────────────────────────────────┐
│ 2. Inji Certify (Issuer :9091)  │  ◄── 2. Configure credential blueprint & keys
│    credentials/<vc>.json        │
└──────────────┬──────────────────┘
               │ published to
               ▼
┌─────────────────────────────────┐
│ 3. VCGA (Catalog :9099)         │  ◄── 3. Register issuer in wallet catalog
│    mimoto-issuers-config.json   │
└──────────────┬──────────────────┘
               │ discovers issuer
               ▼
┌─────────────────────────────────┐              ┌──────────────────────────────┐
│ 4. Wallet (Inji Web :4004)      │   presents   │ 5. Inji Verify (Verify :8000)│
│    claims & stores credential   ├─────────────►│    validates signature/schema│
└─────────────────────────────────┘              └──────────────────────────────┘
```

| Component | Responsibility | Configuration Artifact | Validation Command |
|---|---|---|---|
| **1. VDR & CDN** | JSON-LD schema & static brand assets | `deploy/<inst>/contexts/<vc>/v1.json` | `curl :9098/contexts/<vc>/v1.json` |
| **2. Certify** | Issuer engine, signing keys, status lists | `deploy/<inst>/credentials/<vc>.json` | `curl :9091/.well-known/openid-credential-issuer` |
| **3. VCGA** | Issuer catalog for wallet discovery | `deploy/<inst>/mimoto-issuers-config.json` | `curl :9099/mimoto-issuers-config.json` |
| **4. Wallet** | Digital wallet (Inji Web / Mobile) | Card display properties & template | `curl :4004/v1/mimoto/issuers/.../configuration` |
| **5. Verify** | Verification engine & presentation | `deploy/base/verify-config.json` | `curl :8000/v1/verify/v2/vc-verification` |

Each component has a clear purpose, a specific configuration file, and an **explicit validation command** to confirm it is working before moving to the next.

---

## Component 1: Configure VDR (Schemas) & CDN (Assets)

**Role**: Before an issuer can sign a credential or a verifier can inspect it, the cryptographic schema and visual branding must exist at permanent, resolvable URIs.
- **VDR (Port 9098)**: Static Nginx serving W3C JSON-LD `@context` schemas from `deploy/${INSTALLATION}/contexts/`.
- **CDN (Port 9097)**: Static Nginx serving brand logos and card artwork from `deploy/${INSTALLATION}/assets/`.

### 1.1 What to Configure

1. **Context Schema**: Create the JSON-LD `@context` file at [`deploy/ait/contexts/student-id/v1.json`](../../deploy/ait/contexts/student-id/v1.json):

```json
{
  "@context": {
    "@version": 1.1,
    "@protected": true,
    "ait": "https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json#",
    "AitStudentIdCredential": "ait:AitStudentIdCredential",
    "studentId": "ait:studentId",
    "fullName": "ait:fullName",
    "faculty": "ait:faculty",
    "academicProgram": "ait:academicProgram",
    "studentStatus": "ait:studentStatus",
    "issueDate": "ait:issueDate",
    "expiryDate": "ait:expiryDate"
  }
}
```

2. **Brand Assets**: Place the credential logo at [`deploy/ait/assets/AIT_globe.png`](../../deploy/ait/assets/AIT_globe.png).

3. **Canonical Domain Architecture (`*.dpi.ait.ac.th`)**:
To prevent cryptographic signature invalidation and environment drift, production blueprints **never** use dynamic `.env` string substitution for `@context` and assets. They use permanent canonical domain names:
- **VDR Schema URI**: `https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json`
- **CDN Asset URI**: `https://cdn.dpi.ait.ac.th/assets/AIT_globe.png`

| Role | Institutional Production Domain | Local Clean URL (*.localhost) | Direct Compose Port |
|---|---|---|---|
| **VDR (Schemas)** | `https://vdr.dpi.ait.ac.th` | `http://vdr.localhost` | `http://localhost:9098` |
| **CDN (Assets)** | `https://cdn.dpi.ait.ac.th` | `http://cdn.localhost` | `http://localhost:9097` |
| **VCGA (Catalog)** | `https://vcga.dpi.ait.ac.th` | `http://vcga.localhost` | `http://localhost:9099` |
| **Issuer Engine** | `https://issuer.dpi.ait.ac.th` | `http://issuer.localhost` | `http://localhost:9091` |
| **Verifier UI** | `https://verifier.dpi.ait.ac.th` | `http://verifier.localhost` | `http://localhost:8000` |
| **Web Wallet** | `https://wallet.dpi.ait.ac.th` | `http://wallet.localhost` | `http://localhost:4004` |
| **VC Lab Studio** | `https://lab.dpi.ait.ac.th` | `http://lab.localhost` | `http://localhost:4200` |

In local development:
- **Zero-Config Ingress (Traefik v3.7)**: All `*.localhost` domains (RFC 6761) resolve natively to `127.0.0.1` on port 80 without modifying `/etc/hosts`.
- **Inside Docker**: `compose.trust.yaml`, `compose.certify.yaml`, `compose.verify.yaml`, and `compose.web-wallet.yaml` define network aliases and `extra_hosts` mapping `*.dpi.ait.ac.th` to `host-gateway`.
- **On Developer Host (Optional)**: If you want to use the full `*.dpi.ait.ac.th` production domain names locally on your host machine, add them to `/etc/hosts`:
  ```bash
  127.0.0.1 vdr.dpi.ait.ac.th cdn.dpi.ait.ac.th vcga.dpi.ait.ac.th issuer.dpi.ait.ac.th verifier.dpi.ait.ac.th wallet.dpi.ait.ac.th
  ```
  Or access directly via exposed host ports (`http://localhost:9098` for VDR, `http://localhost:9097` for CDN).

### 1.2 How to Validate VDR and CDN

#### Validate VDR:
```bash
curl -s http://localhost:9098/contexts/student-id/v1.json | jq .
```
*Expected: HTTP 200 OK returning the JSON-LD context.*

#### Validate CDN:
```bash
curl -s -I http://localhost:9097/assets/AIT_globe.png
```
*Expected: HTTP 200 OK with `Content-Type: image/png` and `Access-Control-Allow-Origin: *`.*

---

## Component 2: Configure Inji Certify (Issuer Engine)

**Role**: Certify is the cryptographic signing engine. It maintains signing keys (`did:key` / X.509), evaluates templates, maps data from upstream sources, signs credentials, and tracks revocation lists.

### 2.1 Format A: W3C JSON-LD (`ldp_vc`) Student Card

Create the credential definition and Apache Velocity template at [`deploy/ait/credentials/ait-student-id.json`](../../deploy/ait/credentials/ait-student-id.json):

```json
{
  "credential_config_key_id": "ait-student-id",
  "status": "active",
  "scope": "ait_student_id_vc_ldp",
  "credential_type": "AitStudentIdCredential,VerifiableCredential",
  "credential_format": "ldp_vc",
  "context": [
    "https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json",
    "https://www.w3.org/ns/credentials/v2"
  ],
  "did_url": "did:key:z6MkpPLACEHOLDERreplaceMeViaBootstrapDidRefreshScript1",
  "key_manager_app_id": "CERTIFY_VC_SIGN_ED25519",
  "key_manager_ref_id": "ED25519_SIGN",
  "signature_algo": "EdDSA",
  "signature_crypto_suite": "Ed25519Signature2020",
  "display": [
    {
      "name": "AIT Student ID Card",
      "locale": "en",
      "logo": {
        "url": "https://cdn.dpi.ait.ac.th/assets/AIT_globe.png",
        "alt_text": "AIT Logo"
      },
      "background_color": "#005696",
      "text_color": "#FFFFFF"
    }
  ],
  "display_order": [
    "studentId",
    "fullName",
    "faculty",
    "academicProgram",
    "studentStatus",
    "expiryDate"
  ],
  "cryptographic_binding_methods_supported": [
    "did:jwk"
  ],
  "credential_signing_alg_values_supported": [
    "Ed25519Signature2020"
  ],
  "proof_types_supported": {
    "jwt": {
      "proof_signing_alg_values_supported": [
        "RS256",
        "ES256"
      ]
    }
  },
  "credential_status_purpose": [
    "revocation"
  ],
  "credential_subject": {
    "studentId": { "display": [{ "name": "Student ID", "locale": "en" }] },
    "fullName": { "display": [{ "name": "Full Name", "locale": "en" }] },
    "faculty": { "display": [{ "name": "Faculty / School", "locale": "en" }] },
    "academicProgram": { "display": [{ "name": "Academic Program", "locale": "en" }] },
    "studentStatus": { "display": [{ "name": "Status", "locale": "en" }] },
    "issueDate": { "display": [{ "name": "Issue Date", "locale": "en" }] },
    "expiryDate": { "display": [{ "name": "Expiry Date", "locale": "en" }] }
  },
  "vc_template": {
    "@context": [
      "https://www.w3.org/ns/credentials/v2",
      "https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json",
      "https://w3id.org/security/suites/ed25519-2020/v1"
    ],
    "issuer": "${_issuer}",
    "type": [
      "VerifiableCredential",
      "AitStudentIdCredential"
    ],
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
      "studentId": "${studentId}",
      "fullName": "${fullName}",
      "faculty": "${faculty}",
      "academicProgram": "${academicProgram}",
      "studentStatus": "${studentStatus}",
      "issueDate": "${issueDate}",
      "expiryDate": "${expiryDate}"
    }
  }
}
```

---

### 2.2 Format B: ISO/IEC 18013-5 Mobile Document (`mso_mdoc`) Student Card

In addition to W3C JSON-LD, Inji Certify supports issuing the Student ID as an **ISO/IEC 18013-5 mDoc** (the binary CBOR/COSE standard used by Apple Wallet, Google Wallet, and offline BLE/NFC turnstiles).

Create [`deploy/ait/credentials/ait-student-id-mdoc.json`](../../deploy/ait/credentials/ait-student-id-mdoc.json):

```json
{
  "credential_config_key_id": "ait-student-id-mdoc",
  "status": "active",
  "scope": "ait_student_id_mdoc",
  "credential_format": "mso_mdoc",
  "doctype": "th.ac.ait.student_id",
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
      "name": "AIT Student ID (mDoc)",
      "locale": "en",
      "logo": {
        "url": "https://cdn.dpi.ait.ac.th/assets/AIT_globe.png",
        "alt_text": "AIT Logo"
      },
      "background_color": "#005696",
      "text_color": "#FFFFFF"
    }
  ],
  "display_order": [
    "student_id",
    "full_name",
    "faculty",
    "academic_program",
    "student_status",
    "expiry_date"
  ],
  "mso_mdoc_claims": {
    "th.ac.ait.student_id": {
      "student_id": {
        "mandatory": true,
        "display": [{ "name": "Student ID", "locale": "en" }]
      },
      "full_name": {
        "mandatory": true,
        "display": [{ "name": "Full Name", "locale": "en" }]
      },
      "faculty": {
        "mandatory": false,
        "display": [{ "name": "Faculty", "locale": "en" }]
      },
      "academic_program": {
        "mandatory": false,
        "display": [{ "name": "Academic Program", "locale": "en" }]
      },
      "student_status": {
        "mandatory": true,
        "display": [{ "name": "Student Status", "locale": "en" }]
      },
      "issue_date": {
        "mandatory": true,
        "display": [{ "name": "Issue Date", "locale": "en" }]
      },
      "expiry_date": {
        "mandatory": true,
        "display": [{ "name": "Expiry Date", "locale": "en" }]
      }
    }
  }
}
```

---

### 2.3 Sync to Certify Database
Inji Certify reads configurations from PostgreSQL. Apply your files using `template-sync`:
```bash
docker compose -f compose.certify.yaml run --rm template-sync
```

### 2.4 How to Validate Inji Certify

#### Validation Check 1: Query the OpenID4VCI Issuer Discovery Endpoint
Certify publishes all active credentials at its `.well-known` discovery URL:
```bash
curl -s http://localhost:9091/.well-known/openid-credential-issuer | jq '.credential_configurations_supported["ait-student-id"]'
```
*Expected Result:*
```json
{
  "format": "ldp_vc",
  "scope": "ait_student_id_vc_ldp",
  "credential_definition": {
    "type": [
      "VerifiableCredential",
      "AitStudentIdCredential"
    ],
    "@context": [
      "https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json",
      "https://www.w3.org/ns/credentials/v2"
    ]
  }
}
```

#### Validation Check 2: Direct Database Verification
Check that the database row was inserted into PostgreSQL:
```bash
docker compose -f compose.certify.yaml exec -T database \
  psql -U postgres -d inji_certify -c \
  "SELECT credential_config_key_id, status, scope FROM certify.credential_config WHERE credential_config_key_id = 'ait-student-id';"
```
*Expected Result: `1 row returned` with `status: active`.*

---

## Component 3: Configure VCGA (Issuers Catalog)

**Role**: The Verifiable Credentials Global Architecture (VCGA) catalog tells wallets which issuers exist, what credentials they issue, and how to reach their OAuth and OpenID4VCI endpoints. In this stack, it is statically served by Nginx on port `9099`.

### 3.1 What to Configure
In [`deploy/ait/mimoto-issuers-config.json`](../../deploy/ait/mimoto-issuers-config.json), ensure your issuer points to Certify's discovery endpoint:

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
Query the static VCGA catalog endpoint directly:
```bash
curl -s http://localhost:9099/mimoto-issuers-config.json | jq '.issuers[] | {issuer_id, wellknown_endpoint, enabled}'
```

*Expected Result:*
```json
{
  "issuer_id": "AITUniversity",
  "wellknown_endpoint": "http://host.docker.internal:9091/.well-known/openid-credential-issuer",
  "enabled": "true"
}
```
*If this returns HTTP 200 and points to Certify's discovery endpoint, VCGA is correctly configured.*

---

## Component 4: Configure Wallet (Inji Web)

**Role**: Inji Web (port 4004) connects to VCGA to discover issuers, lets users authenticate, requests credentials, and visually renders them in the digital wallet.

### 4.1 What to Configure
Inji Web dynamically reads the issuer's credentials from Certify (via VCGA). However, you configure:
1. **Wallet Display Schema**: Defined inside [`deploy/ait/credentials/ait-student-id.json`](../../deploy/ait/credentials/ait-student-id.json) under `display` and `credential_subject` (title, logo, background color, localized field labels).
2. **(Optional) Visual Card Template**: If you need custom HTML/print layout, provide `deploy/base/<Issuer>-ait-student-id-template.html` using `#claimValue("studentId")`.

### 4.2 How to Validate Wallet Readiness

#### Validation Check 1: Inji Web Issuer Discovery API
Query Inji Web's backend proxy to verify it sees the issuer:
```bash
curl -s http://localhost:4004/v1/mimoto/issuers | jq .
```
*Expected Result: Lists `AITUniversity` as an available issuer.*

#### Validation Check 2: Inji Web Credential Configuration Proxy
Verify that Inji Web successfully proxies and parses the new credential from Certify:
```bash
curl -s http://localhost:4004/v1/mimoto/issuers/AITUniversity/configuration | jq '.credential_configurations_supported["ait-student-id"]'
```
*Expected Result: Returns the full configuration object for `ait-student-id`. If this succeeds, the wallet UI will display the Student ID Card in its catalog.*

---

## Component 5: Configure Inji Verify (Verification Engine)

**Role**: Inji Verify cryptographically verifies credential signatures, validates JSON-LD schemas against the VDR, and renders the claims for relying parties.

### 5.1 What to Configure
Edit [`deploy/base/verify-config.json`](../../deploy/base/verify-config.json):

1. **Add the Input Descriptor** to `verifiableClaims`:
```json
{
  "logo": "/assets/cert.png",
  "name": "AIT Student ID",
  "type": "AitStudentIdCredential",
  "clientIdScheme": "did",
  "definition": {
    "purpose": "Verify the holder's AIT student ID card credential.",
    "format": {
      "ldp_vc": {
        "proof_type": ["Ed25519Signature2020"]
      }
    },
    "input_descriptors": [
      {
        "id": "student id credential",
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
                "pattern": "AitStudentIdCredential"
              }
            }
          }
        }
      }
    ]
  }
}
```

2. **Add Render Order** to `VCRenderOrders`:
```json
"AitStudentIdCredentialRenderOrder": [
  "studentId",
  "fullName",
  "faculty",
  "academicProgram",
  "studentStatus",
  "expiryDate"
]
```

### 5.2 How to Validate Inji Verify
Send a test credential verification request to Inji Verify (`http://localhost:8000`):

```bash
curl -s -X POST "http://localhost:8000/v1/verify/v2/vc-verification" \
  -H "Content-Type: application/json" \
  -d '{
    "verifiableCredential": "<ISSUED_CREDENTIAL_JSON>",
    "skipStatusChecks": true
  }' | jq .
```

*Expected Result:*
```json
{
  "allChecksSuccessful": true,
  "schemaAndSignatureCheck": {
    "status": "SUCCESS"
  }
}
```
*If `allChecksSuccessful: true`, Inji Verify has resolved the VDR context, verified the Ed25519 digital signature, and confirmed that the schema matches.*

---

## 6. End-to-End Validation Checklist

Before releasing or testing with real users, verify each component in order:

| Step | Component | Target Endpoint | Success Criteria |
|---|---|---|---|
| **1** | **VDR** | `GET http://localhost:9098/contexts/student-id/v1.json` | HTTP 200, returns JSON-LD `@context` |
| **2** | **Certify Discovery** | `GET http://localhost:9091/.well-known/openid-credential-issuer` | Returns `ait-student-id` configuration |
| **3** | **VCGA Catalog** | `GET http://localhost:9099/mimoto-issuers-config.json` | Returns `AITUniversity` issuer |
| **4** | **Wallet Proxy** | `GET http://localhost:4004/v1/mimoto/issuers/AITUniversity/configuration` | Inji Web sees `ait-student-id` |
| **5** | **Verify Service** | `POST http://localhost:8000/v1/verify/v2/vc-verification` | `allChecksSuccessful: true` |
