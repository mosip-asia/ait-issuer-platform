---
title: "Stage 2: Inji Web Wallet Day-0 Deployment Guide"
description: "Operational runbook for deploying the Inji Web Wallet, configuring Keycloak OAuth clients (with PKCE, redirect URIs, and protocol mappers), and registering issuers in the VCGA catalog."
tags:
  - guide
  - deployment
  - wallet
  - keycloak
  - oauth
  - vcga
---

# Stage 2: Inji Web Wallet Day-0 Deployment Guide

This guide covers the **initial (Day-0) deployment of the Inji Web Wallet** and the configuration of the **OAuth Client on campus Keycloak (`oauth-dev`)**.

```mermaid
flowchart LR
    subgraph Browser["Student Browser"]
        WalletUI["Inji Web Wallet<br>(wallet.dpi.ait.ac.th)"]
    end

    subgraph TrustStack["Catalog & Discovery"]
        VCGA["VCGA Catalog<br>(vcga.dpi.ait.ac.th/vcga/issuers.json)"]
    end

    subgraph CampusIAM["Campus Keycloak (oauth-dev)"]
        Keycloak["Keycloak IAM<br>(Client: wallet-demo)"]
    end

    subgraph CertifyStack["Issuer Engine"]
        Certify["Inji Certify<br>(issuer.dpi.ait.ac.th)"]
    end

    WalletUI -->|"1. Fetch Issuers"| VCGA
    WalletUI -->|"2. Redirect to Login (PKCE)"| Keycloak
    Keycloak -->>|"3. Access Token (sub=st120001)"| WalletUI
    WalletUI -->|"4. Claim Credential (Bearer Token)"| Certify
```

---

## 1. Keycloak Client Configuration (on `oauth-dev` Server)

Unlike Inji Certify (which is a Resource Server), the **Wallet is an OAuth Client**. It must be registered in your campus Keycloak realm (`ait-dev`).

### A. Client Basic Settings
Navigate to **Clients > Create client** in the Keycloak Admin Console:
- **Client ID**: `wallet-demo` (or `inji-web-wallet`).
- **Client Protocol**: `openid-connect`.
- **Client Authentication**: `OFF` (Public Client with PKCE).
- **Standard Flow Enabled**: `ON` (Authorization Code Grant).
- **Direct Access Grants Enabled**: `OFF` (or `ON` for automated CLI smoke tests).
- **Valid Redirect URIs**:
  - `https://wallet.dpi.ait.ac.th/redirect`
  - `http://wallet.localhost/redirect` (for developer laptop testing)
  - `io.mosip.residentapp.inji://oauthredirect` (for mobile wallets)
- **Web Origins**:
  - `+` or `https://wallet.dpi.ait.ac.th` (allows browser CORS during token exchange).

---

### B. Required Protocol Mappers (Critical for Issuance)

By default, Keycloak assigns an internal UUID to the token `sub` claim. However, Inji Certify queries the SIS Adapter using `sub` (e.g. `GET /student/{sub}/transcript`).

Configure these three protocol mappers on the `wallet-demo` client:

1. **`sub-from-username`** (User Model Property Mapper):
   - **Mapper Type**: `User Property`
   - **Property**: `username`
   - **Token Claim Name**: `sub`
   - **Claim JSON Type**: `String`
   - **Add to Access Token**: `true`
   - **Add to ID Token**: `true`
   - **Add to UserInfo**: `true`

2. **`audience-self`** (Audience Mapper):
   - **Mapper Type**: `Audience`
   - **Included Client Audience**: `wallet-demo`
   - **Add to Access Token**: `true`
   - *(Ensures the token's `aud` matches Certify's allowed audiences)*.

3. **`client_id-hardcoded`** (Hardcoded Claim Mapper):
   - **Mapper Type**: `Hardcoded claim`
   - **Token Claim Name**: `client_id`
   - **Claim Value**: `wallet-demo`
   - **Add to Access Token**: `true`

---

### C. Client Scopes
1. Go to **Client Scopes > Create client scope**:
   - **Name**: `ait_transcript_vc_ldp`
   - **Protocol**: `openid-connect`
   - **Include in token scope**: `true`
2. Go to your client (`wallet-demo`) > **Client Scopes** > **Add Client Scope** > Select `ait_transcript_vc_ldp` as **Optional**.

---

## 2. VCGA Catalog Synchronization (`deploy/<tenant>/vcga/issuers.json`)

The wallet queries VCGA's [`deploy/ait/vcga/issuers.json`](../../deploy/ait/vcga/issuers.json) to locate the token endpoint and issuer host:

1. Ensure `.env` contains your Keycloak token endpoint and wallet URLs:
   ```ini
   INJI_WEB_URL=https://wallet.dpi.ait.ac.th
   CERTIFY_PUBLIC_BASE_URL=https://issuer.dpi.ait.ac.th
   AUTH_SERVER_TOKEN_ENDPOINT=https://oauth-dev.ait-itserv.dpi.ait.ac.th/realms/ait-dev/protocol/openid-connect/token
   AUTH_SERVER_WALLET_CLIENT_ID=wallet-demo
   ```
2. Run the parameterization script to sync the file:
   ```bash
   python3 src/tools/render_mimoto_issuers_config.py
   ```
3. This sets `authorization_audience` and `proxy_token_endpoint` in `issuers.json` directly to your campus Keycloak server.

---

## 3. Deploy the Web Wallet Stack

Start the Web Wallet service and VCGA registry:
```bash
docker compose -f compose.web-wallet.yaml -f compose.trust.yaml -f compose.traefik.yaml up -d
```

---

## 4. End-to-End Verification (Claiming a VC)

1. Open `https://wallet.dpi.ait.ac.th` in a browser.
2. Select **AIT University** from the issuer catalog.
3. Click **Add Credential** $\rightarrow$ browser redirects to Keycloak login.
4. Log in with a valid student username (e.g. `st120001`).
5. After login, Keycloak redirects back to `https://wallet.dpi.ait.ac.th/redirect`.
6. The wallet exchanges the authorization code for a Bearer token and requests the credential from Inji Certify.
7. Verify that the **AIT Transcript** credential is saved and viewable in the wallet UI.

---

## 5. Troubleshooting Matrix

| Symptom | Root Cause | Fix |
|---|---|---|
| **CORS error in browser console** | Keycloak `Web Origins` missing wallet domain | Add `https://wallet.dpi.ait.ac.th` (or `+`) to Keycloak client `Web Origins`. |
| **Redirect URI mismatch (400)** | Redirect URI in browser does not match Keycloak whitelist | Add `https://wallet.dpi.ait.ac.th/redirect` to Keycloak client `Valid Redirect URIs`. |
| **`no_record` error after login** | Keycloak token `sub` is UUID instead of student ID | Ensure `sub-from-username` protocol mapper is configured and added to access tokens. |
| **Issuer not showing in wallet** | VCGA catalog not reachable or invalid JSON | Verify `curl -sf https://vcga.dpi.ait.ac.th/vcga/issuers.json | jq .`. |
