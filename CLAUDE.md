# CLAUDE.md

Operational guidelines, architectural invariants, and command cheat sheet for developers and AI agents working in `mosip-asia/ait-issuer-platform`.

## 1. What This Repository Is

The **Institutional Verifiable Credential Platform** is built on pinned upstream MOSIP Inji components to issue W3C VCDM 2.0 Verifiable Credentials (JSON-LD with Ed25519Signature2020) via OpenID4VCI.

- **Issuer (Inji Certify)**: Signs credentials populated from university SIS data via an SPI Data-provider plugin (`src/issuer/`).
- **Approval Gate (Gateway)**: Sits *beside* the data path (`docs/adr/0001-approval-gate-beside-the-data-path.md`) to evaluate eligibility checklists (no holds, conferral status, zero balance) for academic transcripts (Phase 2).
- **Wallets**: Compliant holder wallets (Inji Web Wallet `:4004` and AI4DPI Mobile Wallet) claim VCs using OpenID4VCI.
- **Trust Registry & Verifier**: Static VDR schema context server (`deploy/<tenant>/vdr/contexts/`), VCGA issuer catalog (`deploy/<tenant>/vcga/`), and decentralized Inji Verify service & custom UI (`src/verifier/`).
- **Installations (`deploy/<tenant>/`)**: Multi-tenant isolation for `ait` (University Credentials) and `hackathon` (Developer Passport & Achievement Certificate).

---

## 2. Core Invariants & Architecture Rules

1. **OpenID4VCI Resource Server Decoupling:**
   - Inji Certify is an **OAuth 2.0 Resource Server**, NOT a client. It must NEVER configure, expect, or check `AUTH_SERVER_WALLET_CLIENT_ID`.
   - Certify validates bearer access tokens against Keycloak public JWKS (`AUTH_SERVER_JWKS_URL`) using resource indicator audience validation (`https://<issuer-domain>/v1/certify/issuance/credential`).
   - Wallets are OAuth clients registered in Keycloak with standard PKCE and redirect URIs.

2. **Day-0 Phased Rollout (Student ID First):**
   - Day-0 deployment in dev environments is scoped strictly to the **Student ID Card** (`StudentIdCredential`, `AitIdCredential`) querying `GET /student/{sub}/student-id` with Gateway checklist gate disabled (`MOSIP_CERTIFY_GATEWAY_ENABLED=false`).
   - Academic Transcript (`AitTranscriptCredential`) with Gateway checklist gates is deferred to Phase 2.

3. **Multi-Role Campus Identity & W3C Multi-Typing:**
   - All campus roles (Students, Faculty, Staff) share a single LDAP directory and Keycloak realm (`ait-dev`).
   - Role scoping is enforced by the SIS Adapter (returns 404 for non-students, causing Certify to fail closed with `no_record`).
   - Credentials use W3C VCDM 2.0 dual typing: `["VerifiableCredential", "StudentIdCredential", "AitIdCredential"]` with `"affiliation": "Student"`.

4. **Cryptographic Binding Standards:**
   - All credential definitions and database seeds must include `"did:key"` alongside `"did:jwk"` in `cryptographic_binding_methods_supported` for Thailand ETDA and mobile wallet compliance.

5. **Approval Gate Beside the Data Path (ADR 0001):**
   - When enabled (Phase 2), the Gateway evaluates the Checklist (`no_holds`, `conferred`, `zero_balance`) via `GET /student/{sub}/eligibility`.
   - The Gateway **never** proxies or intercepts credential record data. Refusal fails closed (`checklist_failed`, `no_record`, `gateway_error`).

6. **Canonical API Contracts:**
   - [`docs/contracts/adapter-openapi.yaml`](docs/contracts/adapter-openapi.yaml) is the master contract defining `/student/{sub}/student-id`, `/student/{sub}/transcript`, and `/student/{sub}/eligibility`.
   - `tests/test_adapter.py` holds Certify templates, database seeds, and adapter responses equal against this OpenAPI specification.

7. **Multi-Tenant Directory Layout (`deploy/<tenant>/`):**
   - Certify configuration is isolated under `deploy/<tenant>/certify/` (`certify-installation.properties`, `certify_seed.sql`, `credentials/*.json`).
   - Trust registry assets reside under `deploy/<tenant>/vdr/` and `deploy/<tenant>/vcga/`.

8. **Plugin Build & Packaging:**
   - Source code is at `src/issuer/` (Java 21).
   - Built and packaged via `scripts/build.sh` (or `docker compose -f compose.certify-build.yaml run --rm plugin-builder` to `src/issuer/target/issuer-data-provider-plugin.jar`).
   - Baked into the pre-built `ghcr.io/mosip-asia/ait-certify` container image into `/home/inji/additional_jars/issuer-data-provider-plugin.jar` (or mounted as a single file via `compose.override.yaml` for rapid local iteration). Never mount a directory over `additional_jars/`.

---

## 3. Standard Verification & Test Commands

Run the host test suite without Docker containers:
```bash
python3 src/tools/test_generate_csv.py
python3 src/tools/test_render_mimoto_issuers_config.py
python3 src/certify_template_sync/test_sync.py
python3 src/verifier/test_verifier.py
python3 tests/test_installations.py
python3 tests/test_backgrounds_ignored.py
python3 tests/test_authorization_server.py
python3 tests/test_inji_web_vc_readiness.py
.venv/bin/python tests/test_issue_and_verify.py
.venv/bin/python tests/test_adapter.py
.venv/bin/python tests/test_courses.py
python3 tests/test_print_check.py
.venv/bin/python src/gateway/tests/test_evaluations.py
bash scripts/check-data-guard.sh
```

---

## 4. Compose Manifests & Deployment Guides

### Compose Files:
- `compose.yaml`: Master compose orchestrator.
- `compose.certify.yaml`: Core Inji Certify engine, PostgreSQL, template-sync.
- `compose.certify-build.yaml`: Containerized Maven build for `IssuerDataProviderPlugin.java`.
- `compose.web-wallet.yaml`: Inji Web Wallet UI.
- `compose.verify.yaml`: Inji Verify UI and verification backend.
- `compose.trust.yaml`: VDR schema context registry and VCGA issuer catalog.
- `compose.traefik.yaml`: Ingress router for local/dev domain routing.
- `compose.mimoto.yaml`: Local only, never CD: `ait-mimoto` (the Wallet's printer: Mimoto 0.21 with one change, `src/mimoto/README.md`) beside the local stack. Start it with `scripts/mimoto-up.sh`; check a print with `scripts/print-check.sh`.

### Day-0 Deployment Guides:
- **Roadmap**: [`docs/guides/day-0-deployment.md`](docs/guides/day-0-deployment.md)
- **Stage 1 (Issuer Engine)**: [`docs/guides/day-0-certify.md`](docs/guides/day-0-certify.md)
- **Stage 2 (Holder Wallet)**: [`docs/guides/day-0-wallet.md`](docs/guides/day-0-wallet.md)
- **Stage 3 (Credential Verifier)**: [`docs/guides/day-0-verify.md`](docs/guides/day-0-verify.md)

---

## 5. Repository Hygiene & Conventions

- **Line Endings:** All `.sh` files must use LF line endings (`.gitattributes`).
- **Git Hygiene:** Never commit `.env`, CSV files, generated templates, or JARs.
- **Local Files:** `AGENTS.md`, `PLAN.md`, and `docs/log.md` at the repository root are local-only and git-ignored.
- **In-place Edits in WSL/Linux:** Never use `sed -i` on bind-mounted files (preserves Docker Desktop inode bindings).
- **Issue Tracking:** Do not create or comment on GitHub Issues; track issues locally or via PRs.
