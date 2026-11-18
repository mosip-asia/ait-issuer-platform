# AGENTS.md

Operational guidelines, architectural invariants, and User Acceptance Testing (UAT) runbook for AI agents and human reviewers working in `mosip-asia/ait-issuer-platform`.

This file adheres strictly to repository conventions defined in [`CLAUDE.md`](./CLAUDE.md) and [`docs/guides/day-0-deployment.md`](./docs/guides/day-0-deployment.md). It is local-only and git-ignored.

---

## 1. System Overview & Core Invariants

The **Issuer platform** is built on pinned upstream Inji components to issue W3C VCDM 2.0 Verifiable Credentials (JSON-LD with Ed25519Signature2020) via OpenID4VCI.

### Architecture Topology

#### Day-0 Deployment: Student ID Card Issuance (Direct Adapter Path)
```
[ Holder Wallet (Inji Web / Mobile) ]
           │
           │ 1. OpenID4VCI: Bearer <access_token>
           ▼ (Audience: https://issuer.dpi.ait.ac.th/v1/certify/issuance/credential)
 [ Inji Certify :9090 / :9091 ] ── 2. Validate JWT ──► [ Keycloak JWKS (oauth-dev) ]
   (OAuth 2.0 Resource Server)
           │
           ▼
 [ IssuerDataProviderPlugin ] (one generic SPI jar in Certify)
           │
           └── 3. GET /student/{sub}/student-id ───► [ SIS Adapter :8000 ]
                  (Gate OFF: MOSIP_CERTIFY_GATEWAY_ENABLED=false)
```

#### Phase 2 Architecture: Academic Transcript (Approval Gate beside Data Path)
```
[ Holder Wallet (Inji Web / Mobile) ]
           │
           ▼ (OpenID4VCI: Bearer <access_token>)
 [ Inji Certify :9090 / :9091 ] ◄── auth via ── [ Keycloak JWKS ]
           │
           ▼
 [ IssuerDataProviderPlugin ]
      ├── 1. Gate ON? ──► POST /evaluations ──► [ Gateway :8000 ]
      │                                                │
      │                                                ▼ GET /student/{sub}/eligibility
      │                                         [ SIS Adapter :8000 ]
      └── 2. GET /student/{sub}/transcript ───► [ SIS Adapter :8000 ]
```

### Critical Invariants

1. **OpenID4VCI Resource Server Decoupling (Zero Wallet Client IDs in Certify):**
   - Certify is an OAuth 2.0 Resource Server, not a client. It must NEVER configure, expect, or check `AUTH_SERVER_WALLET_CLIENT_ID`.
   - Certify accepts tokens from any compliant wallet (Web, Mobile, third-party) based on Keycloak public JWKS (`AUTH_SERVER_JWKS_URL`) and resource indicator audience validation (`https://<issuer-domain>/v1/certify/issuance/credential`).
   - Wallets are OAuth clients registered in Keycloak with standard PKCE and redirect URIs.

2. **Day-0 Phased Rollout (Student ID First):**
   - Day-0 deployment in dev environments is scoped strictly to the **Student ID Card** (`StudentIdCredential`, `AitIdCredential`) querying `GET /student/{sub}/student-id` with Gateway checklist gate disabled (`MOSIP_CERTIFY_GATEWAY_ENABLED=false`).
   - Academic Transcript (`AitTranscriptCredential`) with Gateway checklist gates (`no_holds`, `conferred`, `zero_balance`) is deferred to Phase 2.

3. **Multi-Role Campus Identity & Dual-Type W3C Hierarchy:**
   - All campus roles (Students, Faculty, Staff) share a single LDAP directory and Keycloak realm (`ait-dev`). Role validation is enforced at the SIS Adapter endpoint (non-students return 404, causing Certify to fail closed with `no_record`).
   - Student ID credentials use W3C VCDM 2.0 multi-typing: `["VerifiableCredential", "StudentIdCredential", "AitIdCredential"]` with `"affiliation": "Student"`, establishing an extensible foundation for future `FacultyIdCredential` and `StaffIdCredential`.

4. **Cryptographic Binding Standards (Thailand ETDA & W3C):**
   - All credential definitions and database seeds must include `"did:key"` alongside `"did:jwk"` in `cryptographic_binding_methods_supported` for Thailand ETDA and mobile wallet compliance.

5. **Approval Gate Beside the Data Path ([ADR 0001](docs/adr/0001-approval-gate-beside-the-data-path.md)):**
   - When enabled (Phase 2), the Gateway is stateless and evaluates the Checklist (`no_holds`, `conferred`, `zero_balance`). It reads only the `/eligibility` path.
   - The Gateway **never** proxies or intercepts the credential record data.
   - Refusal fails closed: Any response other than HTTP 200 with all checks `passed: true` stops issuance (`checklist_failed`, `no_record`, `gateway_error`).

6. **Canonical API Contracts & Drift Prevention:**
   - [`docs/contracts/adapter-openapi.yaml`](docs/contracts/adapter-openapi.yaml) is the master contract defining `/student/{sub}/student-id`, `/student/{sub}/transcript`, and `/student/{sub}/eligibility`.
   - `python3 tests/test_adapter.py` holds Certify templates, database seeds, and adapter responses equal against this OpenAPI specification.

7. **Multi-Installation Model & Directory Layout:**
   - Configuration is isolated under `deploy/<name>/certify/` (`ait` for university credentials, `hackathon` for Developer Passport and Achievement Certificate).
   - Never hardcode installation names or credential types in generic tools or plugins.

8. **Plugin Location & Packaging:**
   - The plugin source code resides at `src/issuer/`.
   - Built and packaged via `scripts/build.sh` (or `docker compose -f compose.certify-build.yaml run --rm plugin-builder` to `src/issuer/target/issuer-data-provider-plugin.jar`).
   - Baked into the pre-built `ghcr.io/mosip-asia/ait-certify` container image into `/home/inji/additional_jars/issuer-data-provider-plugin.jar` (or mounted as a single file via `compose.override.yaml` for rapid local iteration). Never mount a directory over `additional_jars/`, or bundled Certify dependencies will be hidden.

9. **No Shortcuts or Heuristic Parsing:**
   - Never introduce regex token parsing or subject heuristics (e.g. `extractSub`). Token subjects must resolve via standard claim resolution.
   - Structured payload fields (arrays/objects) must be configured generically via `mosip.certify.adapter.structured-keys` rather than hardcoding field names.

10. **In-place Edits in WSL/Linux:**
    - Never use `sed -i` on bind-mounted files. Docker Desktop bind mounts track inode numbers; replacing an inode causes restarts to mount stale files.

---

## 2. Agent Workflow Rules

- **Issue Tracking:** Do not create or comment on GitHub Issues. Work is tracked locally in Markdown files outside the repository (see `docs/agents/issue-tracker.md`).
- **Registrar Approval Flow:** The demo Portal requires registrar approval before rendering claim links in the student portal. This is a deliberate demonstration boundary; do not alter this logic.
- **Git Hygiene:** Never commit `.env`, CSV files, generated templates, or JARs.
- **Line Endings:** All `.sh` files must use LF line endings (`.gitattributes`).

---

## 3. Host Verification & Acceptance Runbook

### Stage 0: Host Pre-flight Verification (In-Process)
Run the host test suite without Docker containers:
```bash
python3 src/tools/test_generate_csv.py
python3 src/tools/test_render_mimoto_issuers_config.py
python3 src/verifier/test_verifier.py
python3 tests/test_installations.py
python3 tests/test_authorization_server.py
python3 tests/test_inji_web_vc_readiness.py
.venv/bin/python tests/test_issue_and_verify.py
.venv/bin/python tests/test_adapter.py
.venv/bin/python tests/test_courses.py
.venv/bin/python src/gateway/tests/test_evaluations.py
bash scripts/check-data-guard.sh
```

---

### Stage 1: Day-0 Deployment Runbook (Dev Environment)

Reference guides:
- [docs/guides/day-0-deployment.md](docs/guides/day-0-deployment.md) (Roadmap)
- [docs/guides/day-0-certify.md](docs/guides/day-0-certify.md) (Stage 1: Certify Issuer)
- [docs/guides/day-0-wallet.md](docs/guides/day-0-wallet.md) (Stage 2: Web Wallet)
- [docs/guides/day-0-verify.md](docs/guides/day-0-verify.md) (Stage 3: Verifier)

#### Test Case D0-01: Issuer Pre-flight & Live DID Binding
1. Pre-flight reachability checks:
   ```bash
   curl -sf https://oauth-dev.ait-itserv.dpi.ait.ac.th/realms/ait-dev/protocol/openid-connect/certs | jq .
   curl -sf http://ait-itserv-dev-vm.netbird.selfhosted:8000/student/st120001/student-id | jq .
   ```
2. Launch services (using `./scripts/deploy.sh` to auto-provision keystore and sync `CERTIFY_DID`):
   ```bash
   ./scripts/deploy.sh ait
   ```
3. Verify live `did:key` binding:
   ```bash
   LIVE_DID=$(curl -sf https://issuer.dpi.ait.ac.th/.well-known/did.json | jq -r '"did:key:" + .verificationMethod[0].publicKeyMultibase')
   echo "Live Keystore-derived Issuer DID: $LIVE_DID"
   # Confirm that .id and CERTIFY_DID in .env match LIVE_DID
   ```
4. Verify discovery endpoint reports `StudentIdCredential` and `AitIdCredential`:
   ```bash
   curl -sf https://issuer.dpi.ait.ac.th/.well-known/openid-credential-issuer | jq .
   ```

#### Test Case D0-02: Student ID Card Issuance via Web Wallet
1. Bring up Web Wallet stack:
   ```bash
   docker compose -f compose.web-wallet.yaml -f compose.trust.yaml -f compose.traefik.yaml up -d
   ```
2. In browser at `https://wallet.dpi.ait.ac.th`:
   - Select **AIT University** $\rightarrow$ log in via campus Keycloak as student (`st120001`).
   - Claim credential via scope `ait_student_id_vc_ldp`.
3. **Expected Result**:
   - Web wallet displays **AIT Student ID Card**.
   - Credential attributes: `studentId: "st120001"`, `affiliation: "Student"`, `fullName: "Nara Wattanakul"`.

#### Test Case D0-03: Student ID Verification via Inji Verify
1. Bring up Inji Verify stack:
   ```bash
   docker compose -f compose.verify.yaml -f compose.trust.yaml -f compose.traefik.yaml up -d
   ```
2. Navigate to `https://verifier.dpi.ait.ac.th`:
   - Drop the downloaded Student ID JSON file (or scan QR code via AI4DPI Mobile Wallet).
3. **Expected Result**:
   - Verification status: **`Valid`** (`allChecksSuccessful: true`).
   - Signature verified against live `did:key`.
   - VDR schema resolved from `https://vdr.dpi.ait.ac.th/contexts/student-id/v1.json`.

---

### Stage 2: Phase 2 Acceptance (Academic Transcript & Checklist Gates)

When Academic Transcript issuance is activated in Phase 2 (`CERTIFY_RECORD_URL=.../transcript`, `MOSIP_CERTIFY_GATEWAY_ENABLED=true`):

#### Test Case P2-01: Eligible Student Transcript Claim
- Student `st120001` (Nara Wattanakul): Holds clean, degree conferred, zero balance.
- Issuance succeeds with full course grades, GPA, and graduation date.

#### Test Case P2-02: Checklist Gate Refusals (Gateway Fail-Closed)
- `st120002` (Hold on record): Refused with `checklist_failed` (`no_holds` failed).
- `st120003` (Pending conferral): Refused with `checklist_failed` (`conferred` failed).
- `st120004` (Debt): Refused with `checklist_failed` (`zero_balance` failed).
- `st120099` (Unknown student): Refused with `no_record` (Adapter 404).

---

### Stage 3: Acceptance Sign-Off Checklist
| Item | Verification Step | Status |
|---|---|---|
| 1 | All unit & host tests pass (`test_adapter.py`, `test_issue_and_verify.py`, etc.) | [ ] |
| 2 | Stage 1 Certify boots with live `did:key` and serves discovery metadata | [ ] |
| 3 | Stage 2 Inji Web Wallet issues Student ID card (`StudentIdCredential`, `AitIdCredential`) | [ ] |
| 4 | Stage 3 Inji Verify validates Student ID against live DID and VDR context | [ ] |
| 5 | Phase 2 Transcript tests pass with Gateway checklist gates enabled | [ ] |
| 6 | Sensitive data guard passes (`scripts/check-data-guard.sh`) | [ ] |
