# Verifiable Credential Platform Deployment

This directory contains deployment overlays and runtime configurations for staging and production environments.

---

## 1. Directory Structure

```
deploy/
├── base/                      # Common Inji platform defaults
│   ├── certify_init.sql       # Postgres schema initialization
│   ├── certify-default.properties # Base Inji Certify Spring properties
│   └── certify-nginx.conf     # Nginx reverse proxy routing
├── ait/                       # AIT Tenant profile (academic transcript)
│   ├── certify-installation.properties
│   ├── authorization-server.env
│   ├── vdr/                   # Tenant schemas, templates, and brand assets
│   ├── vcga/                  # Tenant Mimoto issuer registry configuration
│   ├── gateway.env
│   ├── smoke.json
│   ├── adapter/
│   ├── mock/                  # Stand-in dependencies for local offline testing
│   │   └── keycloak-realm.json
│   ├── vp_request_config.json # OpenID4VP request specifications
│   └── private_key/           # Isolated signing keystore (git-ignored)
├── hackathon/                 # Hackathon Tenant profile (developer passport & achievements)
│   ├── certify-installation.properties
│   ├── authorization-server.env
│   ├── vdr/                   # Tenant schemas, templates, and brand assets
│   ├── vcga/                  # Tenant Mimoto issuer registry configuration
│   ├── gateway.env
│   ├── smoke.json
│   ├── adapter/
│   ├── mock/                  # Stand-in dependencies for local offline testing
│   │   └── keycloak-realm.json
│   ├── vp_request_config.json # OpenID4VP request specifications
│   └── private_key/           # Isolated signing keystore (git-ignored)
└── base/                      # Common Inji platform defaults and shared templates
```

---

## 2. Quickstart: Deploying the Platform

From the repository root:

```bash
# 1. Configure environment
cp .env.example .env

# 2. Select target tenant (ait or hackathon) in .env:
# INSTALLATION=ait

# 3. Deploy services
docker compose up -d

# 4. Verify deployment
./scripts/smoke-test-certify.sh
```
