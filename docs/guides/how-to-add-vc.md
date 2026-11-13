---
title: How to Develop and Add a Verifiable Credential to Inji Certify
description: Step-by-step developer guide for adding a new Verifiable Credential (VC) type to Inji Certify, from vocabulary and Velocity templates to GitOps sync and data mapping.
tags:
  - guide
  - certify
  - credential
  - template
---

# How to Develop and Add a Verifiable Credential to Inji Certify

This guide explains the developer workflow for adding a new **Verifiable Credential (VC)** to the Inji Certify platform.

---

## 1. Core Mental Model: Engine vs Credentials

Before defining a specific credential, it helps to distinguish between the **Certify Engine** and **Credential Blueprints**:

```
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ INJI CERTIFY ENGINE (Generic Baseline)                                      │
 │ - Spring Boot runtime, PostgreSQL connection (inji_certify)                 │
 │ - Cryptographic keystore (local.p12) & Issuer DID (CERTIFY_DID)             │
 │ - OpenID4VCI protocol implementation & verification engine                  │
 └──────────────────────────────────────┬──────────────────────────────────────┘
                                        │ Loads at startup / sync
                                        ▼
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ CREDENTIAL BLUEPRINTS (Per-VC Definitions)                                  │
 │ • ait-transcript         (Academic Transcript)                              │
 │ • student-id             (Student Identification Card)                      │
 │ • achievement-certificate (Hackathon Award)                                 │
 └─────────────────────────────────────────────────────────────────────────────┘
```

- **The Engine alone** has zero hardcoded credentials. It knows how to sign documents with Ed25519, verify holder proofs of possession, maintain the revocation Bitstring list, and serve OpenID4VCI endpoints.
  - To verify the engine is healthy before configuring VCs, run:
    ```bash
    ./scripts/smoke-test-certify.sh http://localhost:9091
    ```
- **A Credential** is a declarative blueprint that tells Certify:
  1. What is the semantic vocabulary? (JSON-LD `@context`)
  2. What is the JSON structure and signing policy? (Credential Configuration & Velocity Template)
  3. Where do the subject claim values come from? (Data Provider Plugin & Adapter)
  4. How should wallets brand and render it? (Display metadata & HTML visual card)

---

## 2. The 4 Building Blocks of a Verifiable Credential

Adding a new VC to Certify involves four coordinated pieces:

```
┌────────────────────────────────┐       ┌────────────────────────────────┐
│ 1. Semantic Vocabulary         │       │ 2. Credential Blueprint        │
│ deploy/<inst>/contexts/        │       │ deploy/<inst>/credentials/     │
│ <vc-name>/v1.json              │       │ <vc-name>.json                 │
│ (W3C JSON-LD Context)          │       │ (Config, Display, Template)    │
└───────────────┬────────────────┘       └───────────────┬────────────────┘
                │                                        │
                │ Served by VDR :9098                    │ Synced via template-sync
                ▼                                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Inji Certify PostgreSQL (certify.credential_config)                     │
└───────────────────────────────────┬─────────────────────────────────────┘
                                    │ Evaluated at issuance
                                    ▼
┌────────────────────────────────┐       ┌────────────────────────────────┐
│ 3. Data Source (Adapter)       │       │ 4. Wallet Presentation         │
│ GET /student/{sub}/...         │       │ deploy/base/                   │
│ JSON fields matching ${...}    │       │ <Issuer>-<vc>-template.html    │
└────────────────────────────────┘       └────────────────────────────────┘
```

---

## 3. Step-by-Step Tutorial: Adding a New Credential

In this tutorial, we will add a new credential called **`student-id`** (`StudentIdCredential`) to the `ait` installation.

### Step 1: Create the Semantic Vocabulary (JSON-LD Context)

W3C JSON-LD requires an `@context` document defining each claim term so digital signatures bind to standardized semantic URIs.

1. Create directory `deploy/ait/contexts/student-id/`
2. Create `deploy/ait/contexts/student-id/v1.json`:

```json
{
  "@context": {
    "@version": 1.1,
    "@protected": true,
    "StudentIdCredential": "https://ait.example/credentials#StudentIdCredential",
    "studentId": "https://ait.example/claims#studentId",
    "fullName": "https://schema.org/name",
    "faculty": "https://schema.org/department",
    "dateOfBirth": "https://schema.org/birthDate",
    "validUntil": "https://schema.org/validUntil"
  }
}
```

*Note: During local development, this file is served by the `vdr` Nginx container at `http://host.docker.internal:9098/contexts/student-id/v1.json`.*

---

### Step 2: Create the Credential Configuration & Velocity Template

Create the configuration file at `deploy/ait/credentials/student-id.json`. This single file configures discovery, cryptographic algorithms, wallet display, and the Apache Velocity template.

```json
{
  "credential_config_key_id": "student-id",
  "status": "active",
  "scope": "student_id_vc_ldp",
  "credential_type": "StudentIdCredential,VerifiableCredential",
  "credential_format": "ldp_vc",
  "context": [
    "http://host.docker.internal:9098/contexts/student-id/v1.json",
    "https://www.w3.org/ns/credentials/v2"
  ],
  "did_url": "did:key:z6MkpPLACEHOLDERreplaceMeViaBootstrapDidRefreshScript1",
  "key_manager_app_id": "CERTIFY_VC_SIGN_ED25519",
  "key_manager_ref_id": "ED25519_SIGN",
  "signature_algo": "EdDSA",
  "signature_crypto_suite": "Ed25519Signature2020",
  "display": [
    {
      "name": "AIT Student ID",
      "locale": "en",
      "logo": {
        "url": "https://ait.ac.th/wp-content/uploads/2024/09/AIT_globe.png",
        "alt_text": "AIT Logo"
      },
      "background_color": "#005696",
      "text_color": "#FFFFFF"
    }
  ],
  "display_order": [
    "fullName",
    "studentId",
    "faculty"
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
    "fullName": {
      "display": [{ "name": "Full Name", "locale": "en" }]
    },
    "studentId": {
      "display": [{ "name": "Student ID", "locale": "en" }]
    },
    "faculty": {
      "display": [{ "name": "Faculty / School", "locale": "en" }]
    }
  },
  "vc_template": {
    "@context": [
      "https://www.w3.org/ns/credentials/v2",
      "http://host.docker.internal:9098/contexts/student-id/v1.json",
      "https://w3id.org/security/suites/ed25519-2020/v1"
    ],
    "issuer": "${_issuer}",
    "type": [
      "VerifiableCredential",
      "StudentIdCredential"
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
      "faculty": "${faculty}"
    }
  }
}
```

#### Understanding the Velocity Variables
In the `vc_template` object:
- **System Built-ins** (populated automatically by Certify's signing engine):
  - `${_issuer}`: The Issuer DID.
  - `${_holderId}`: The Holder DID extracted from the proof-of-possession JWT.
  - `${validFrom}`, `${validUntil}`: Timestamps managed by Certify.
  - `${credentialStatus.*}`: The allocated index in Certify's W3C Bitstring / StatusList2021 revocation registry.
- **Subject Claims** (populated by your Data Provider / Adapter):
  - `${studentId}`, `${fullName}`, `${faculty}`.

---

### Step 3: Synchronize with PostgreSQL (`template-sync`)

Certify reads credentials from its internal `certify.credential_config` database table.

Instead of writing manual SQL, this repository uses GitOps synchronization:
```bash
# In-process synchronization using Python / uv:
uv run certify-template-sync --apply

# Or if running Docker Compose:
docker compose run --rm template-sync
```

When Certify starts up (or restarts), it will automatically load the new configuration from PostgreSQL.

---

### Step 4: Configure Data Provider & Adapter Mapping

When an issuance request arrives, `IssuerDataProviderPlugin` calls your Adapter endpoint (`CERTIFY_RECORD_URL`).

1. **Adapter Output**:
   Your SIS API or Adapter must return a JSON response containing the keys referenced in `${...}`:
   ```json
   {
     "studentId": "st125001",
     "fullName": "Nara Wattanakul",
     "faculty": "School of Engineering and Technology"
   }
   ```
2. **Ledger Indexing (Optional)**:
   If you want this credential's claims indexed in Certify's ledger for searching and revocation audits, add them to `deploy/ait/certify-installation.properties`:
   ```properties
   mosip.certify.indexed-mappings.studentId=$.studentId
   ```

---

### Step 5: (Optional) Wallet Visual Presentation Template

For Inji Web or Inji Mobile wallets to visually render the card in the wallet UI, provide an HTML/SVG card template under `deploy/base/` (e.g. `deploy/base/AITUniversity-student-id-template.html`). Wallets substitute fields using `#claimValue("studentId")`.

---

## 4. Testing & Verification

Once you have added the credential, verify it using the smoke scripts:

### 1. Verify Certify Recognized the New VC
Run the engine baseline smoke test:
```bash
./scripts/smoke-test-certify.sh http://localhost:9091
```
*Expected Output:*
```text
Registered Verifiable Credentials (2 found):
  • ait-transcript: AIT Transcript (Scope: ait_transcript_vc_ldp)
  • student-id: AIT Student ID (Scope: student_id_vc_ldp)
```

### 2. Verify Issuance via Pre-Authorized Code
Run the end-to-end issuance test for a specific student and credential:
```bash
./scripts/smoke-test.sh http://localhost:9091 st125001 student-id
```
*Expected Output:*
- Stages offer for `student-id`.
- Exchanges pre-authorized code for Certify access token.
- Generates ephemeral holder key (`did:jwk`) and proof JWT.
- Certify signs and returns `StudentIdCredential` with valid Ed25519 proof.

---

## 5. Critical Gotchas & Best Practices

1. **Quoted vs Unquoted Velocity Variables**:
   - All standard string claims must be quoted in `vc_template`:
     `"fullName": "${fullName}"`
   - **The Course Array Exception**: If a claim is a raw JSON array or object (like the transcript's semester courses), it **must be unquoted** in `vc_template`:
     `"courses": ${courses}`
     If quoted, Certify will serialize the JSON array into an escaped string.
2. **Strict String Types for Numbers and Dates**:
   - Inji Certify and W3C JSON-LD expect numbers and dates as formatted strings (e.g. `"3.67"`, `"2026-08-31"`). Do not pass raw numeric floats or unparsed dates.
3. **No Forbidden Keys**:
   - The Adapter must **never** return keys managed by Certify: `id`, `_holderId`, `_issuer`, `validFrom`, `validUntil`, `credentialStatus`, `tokenSub`, or `tokenClientId`. If any of these keys appear in the data source payload, `IssuerDataProviderPlugin` rejects issuance with `adapter_error`.
4. **No Null Values**:
   - Every claim in the record must have a value or an empty string (`""`). Certify strictly fails on JSON `null`.
