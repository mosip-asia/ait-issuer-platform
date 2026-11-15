---
title: "How to Develop and Add a Verifiable Credential to Inji Platform"
description: "High-level architectural and step-by-step developer guide for adding a new Verifiable Credential (VC) across the 5 core components: Certify, VCGA, VDR, Wallet, and Verify, including validation commands for each."
tags:
  - guide
  - certify
  - credential
  - template
  - vcga
  - vdr
  - wallet
  - verify
---

# How to Add a Verifiable Credential to Inji Platform

This guide explains the developer workflow for adding a new **Verifiable Credential (VC)** to the platform.

Adding a credential touches **five core components**:

```
                      ┌─────────────────────────────────┐
                      │ 2. VCGA (Issuers Catalog :9099) │
                      │    mimoto-issuers-config.json   │
                      └────────────────┬────────────────┘
                                       │ discovers issuer
                                       ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│ 3. VDR (Context Server :9098)│              │ 4. Wallet (Inji Web :4004)   │
│    contexts/<vc>/v1.json     │              │    views, claims & stores VC │
└──────────────┬───────────────┘              └──────────────┬───────────────┘
               │ resolves schema                             │ OID4VCI request
               ▼                                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│ 1. Inji Certify (Issuer Engine :9091)                                      │
│    credentials/<vc>.json (template, scope, keys) & PostgreSQL sync         │
└──────────────────────────────────────┬─────────────────────────────────────┘
                                       │ issues signed VC
                                       ▼
                      ┌─────────────────────────────────┐
                      │ 5. Inji Verify (Verifier :8000) │
                      │    verify-config.json           │
                      └─────────────────────────────────┘
```

---

## The 5 Core Components Overview

| Component | Responsibility | Configuration Artifact | Validation Command |
|---|---|---|---|
| **1. Certify** | Issuer engine, signing keys, status lists | `deploy/<inst>/credentials/<vc>.json` | `curl :9091/.well-known/openid-credential-issuer` |
| **2. VCGA** | Mimoto issuer catalog for wallet discovery | `deploy/<inst>/mimoto-issuers-config.json` | `curl :9099/mimoto-issuers-config.json` |
| **3. VDR** | JSON-LD schema & context server | `deploy/<inst>/contexts/<vc>/v1.json` | `curl :9098/contexts/<vc>/v1.json` |
| **4. Wallet** | Inji Web / Mobile holder app | `deploy/base/<template>.html` | `curl :4004/v1/mimoto/issuers/.../configuration` |
| **5. Verify** | Signature & schema verification | `deploy/base/verify-config.json` | `curl :8000/v1/verify/v2/vc-verification` |

---

## 1. Configure Inji Certify (Issuer Engine)

**Role**: Certify is the cryptographic signing engine. It loads credential configurations from PostgreSQL (`certify.credential_config`), evaluates Apache Velocity templates, and signs credentials using its configured DID (`CERTIFY_DID`).

### 1.1 What to Configure
Create `deploy/<installation>/credentials/<credential-id>.json`:

```json
{
  "credential_config_key_id": "<credential-id>",
  "status": "active",
  "scope": "<credential_scope>_vc_ldp",
  "credential_type": "<CredentialType>,VerifiableCredential",
  "credential_format": "ldp_vc",
  "context": [
    "https://vdr.example.org/contexts/<vc-name>/v1.json",
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
        "url": "https://example.org/logo.png",
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
      "https://vdr.example.org/contexts/<vc-name>/v1.json",
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

### 1.2 Synchronize to PostgreSQL
Apply the credential JSON to Certify's database:
```bash
docker compose -f compose.certify.yaml run --rm template-sync
```

### 1.3 How to Validate Inji Certify

#### Validation Command 1: OpenID4VCI Issuer Discovery
Query Certify's discovery metadata to ensure the credential is active:
```bash
curl -s http://localhost:9091/.well-known/openid-credential-issuer | jq '.credential_configurations_supported["<credential-id>"]'
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

## 2. Configure VCGA (Issuers Catalog)

**Role**: Verifiable Credentials Global Architecture (VCGA) serves `mimoto-issuers-config.json` on port `9099`. Wallets query this catalog to discover issuers and their OpenID4VCI endpoints.

### 2.1 What to Configure
In `deploy/<installation>/mimoto-issuers-config.json`, ensure your issuer is listed and enabled:
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

### 2.2 How to Validate VCGA
Query the static VCGA catalog server:
```bash
curl -s http://localhost:9099/mimoto-issuers-config.json | jq '.issuers[] | {issuer_id, wellknown_endpoint, enabled}'
```
*Expected: Returns HTTP 200 with `enabled: "true"` and points to Certify's `.well-known` endpoint.*

---

## 3. Configure VDR (Contexts) & CDN (Assets)

In `compose.trust.yaml`, two static services host public trust artifacts:
1. **VDR (Port 9098)**: Serves W3C JSON-LD `@context` schemas from `deploy/<inst>/contexts/`.
2. **CDN (Port 9097)**: Serves branding logos and visual card assets from `deploy/<inst>/assets/`.

### 3.1 What to Configure

1. **Context Schema**: Create `deploy/<installation>/contexts/<vc-name>/v1.json`:
```json
{
  "@context": {
    "@version": 1.1,
    "@protected": true,
    "<prefix>": "https://example.org/credentials#",
    "<CredentialType>": "<prefix>:<CredentialType>",
    "field1": "<prefix>:field1",
    "field2": "<prefix>:field2"
  }
}
```

2. **Brand Assets**: Place your credential logo at `deploy/<installation>/assets/<logo>.png`.

3. **Canonical Domain Architecture (Pattern A)**:
In production, credentials must **never** use dynamic `.env` replacement for `@context` schemas, as altering the context URI breaks W3C JSON-LD cryptographic signatures. Always reference permanent canonical FQDNs (for AIT, under `*.dpi.ait.ac.th`):
- Context: `"https://vdr.dpi.ait.ac.th/contexts/<vc-name>/v1.json"`
- Logo: `"https://cdn.dpi.ait.ac.th/assets/<logo>.png"`

In local development:
- **Docker Compose**: Map domains using `extra_hosts` in `compose.certify.yaml`, `compose.verify.yaml`, and `compose.web-wallet.yaml`, and container network `aliases` in `compose.trust.yaml`.
- **Developer Host**: Add `/etc/hosts` mappings (`127.0.0.1 vdr.dpi.ait.ac.th cdn.dpi.ait.ac.th`) or test via exposed host ports (`:9098` for VDR, `:9097` for CDN).

### 3.2 How to Validate VDR and CDN

#### Validate VDR:
```bash
curl -s http://localhost:9098/contexts/<vc-name>/v1.json | jq .
```
*Expected: Returns HTTP 200 with the valid JSON-LD `@context` document.*

#### Validate CDN:
```bash
curl -s -I http://localhost:9097/assets/<logo>.png
```
*Expected: Returns HTTP 200 with `Content-Type: image/png` and CORS header `Access-Control-Allow-Origin: *`.*

---

## 4. Configure Wallet (Inji Web)

**Role**: Inji Web (port 4004) connects to VCGA, loads the issuer catalog, allows users to request VCs, and displays cards.

### 4.1 What to Configure
- **Branding**: Configured in Certify's `deploy/<inst>/credentials/<vc>.json` under `display` (wallet automatically reads this).
- **Display Order**: Configured under `display_order` and `credential_subject` in the credential JSON.
- **Visual Card (Optional)**: If custom visual printing or styling is required, provide `deploy/base/<Issuer>-<vc-name>-template.html`.

### 4.2 How to Validate Wallet Readiness

#### Validation Command 1: Wallet Issuer Discovery
Verify that Inji Web can read the issuer from VCGA:
```bash
curl -s http://localhost:4004/v1/mimoto/issuers | jq .
```
*Expected: Lists your configured issuer.*

#### Validation Command 2: Wallet Credential Catalog Proxy
Verify that Inji Web proxies Certify's credential configurations:
```bash
curl -s http://localhost:4004/v1/mimoto/issuers/<IssuerId>/configuration | jq '.credential_configurations_supported["<credential-id>"]'
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
curl -s -X POST "http://localhost:8000/v1/verify/v2/vc-verification" \
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

Run through these five commands in order to confirm complete readiness:

```bash
# 1. VDR Context is served:
curl -s -f http://localhost:9098/contexts/<vc-name>/v1.json > /dev/null && echo "✅ 1. VDR OK"

# 2. VCGA Catalog is served:
curl -s -f http://localhost:9099/mimoto-issuers-config.json > /dev/null && echo "✅ 2. VCGA OK"

# 3. Certify recognizes the credential:
curl -s -f http://localhost:9091/.well-known/openid-credential-issuer | jq -e '.credential_configurations_supported["<credential-id>"]' > /dev/null && echo "✅ 3. Certify OK"

# 4. Wallet proxies the credential:
curl -s -f http://localhost:4004/v1/mimoto/issuers/<IssuerId>/configuration | jq -e '.credential_configurations_supported["<credential-id>"]' > /dev/null && echo "✅ 4. Wallet OK"

# 5. Verify service is healthy:
curl -s -f http://localhost:8000/actuator/health > /dev/null && echo "✅ 5. Verify OK"
```
