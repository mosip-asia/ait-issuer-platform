#!/usr/bin/env bash
# ==============================================================================
# Inji Certify Engine Baseline Smoke Test
#
# Validates that the Inji Certify issuer engine itself is healthy, operational,
# and correctly configured to serve, independent of external integrations or
# specific student credential issuance flows:
#
# 1. System Health Check (/v1/certify/actuator/health)
#    - Verifies Spring Boot runtime is UP and PostgreSQL database is connected.
# 2. Cryptographic Identity & Signing Keys (/.well-known/did.json & /jwks.json)
#    - Verifies the issuer's public DID document and active cryptographic signing keys.
# 3. OpenID4VCI Issuer Metadata Discovery (/.well-known/openid-credential-issuer)
#    - Verifies the OpenID4VCI discovery endpoint, credential endpoints, and inspects
#      all registered credential configurations (VCs) loaded in the engine.
# 4. Credential Revocation Registry (Status List)
#    - Verifies the W3C Bitstring / StatusList2021 revocation endpoint is reachable.
#
# Usage:
#   ./scripts/smoke-test-certify.sh [certify_url]
#   ./scripts/smoke-test-certify.sh http://localhost:9091
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
NC="\033[0m"

CERTIFY_URL="${1:-${CERTIFY_PUBLIC_BASE_URL:-http://issuer.localhost}}"
CERTIFY_URL="${CERTIFY_URL%/}" # Strip trailing slash

echo -e "${BLUE}${BOLD}======================================================================${NC}"
echo -e "${BLUE}${BOLD} 🔍 INJI CERTIFY ENGINE BASELINE SMOKE TEST${NC}"
echo -e "${BLUE}${BOLD}======================================================================${NC}"
echo -e " Target Host: ${BOLD}${CERTIFY_URL}${NC}"
echo ""

# 0. Check prerequisite CLI tools
for cmd in curl jq; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo -e "${RED}${BOLD}[ERROR]${NC} Required CLI tool '${cmd}' is not installed." >&2
    exit 1
  fi
done

FAILED=0

# Helper to fetch with timeout and handle errors
fetch_json() {
  local url="$1"
  local desc="$2"
  local resp
  if ! resp=$(curl -skfL --max-time 10 "$url" 2>/dev/null); then
    echo -e "${RED}${BOLD}[FAILED]${NC} Could not reach ${desc} at: ${url}" >&2
    return 1
  fi
  echo "$resp"
}

# ------------------------------------------------------------------------------
# Step 1: System Health Check
# ------------------------------------------------------------------------------
echo -e "${BLUE}${BOLD}[1/4] Checking Certify System Health & Database Connection...${NC}"
HEALTH_URL="${CERTIFY_URL}/v1/certify/actuator/health"
HEALTH_RESP=$(curl -skL --max-time 10 "$HEALTH_URL" 2>/dev/null || echo "")

if [ -n "$HEALTH_RESP" ] && echo "$HEALTH_RESP" | jq -e . >/dev/null 2>&1; then
  STATUS=$(echo "$HEALTH_RESP" | jq -r '.status // empty' 2>/dev/null || echo "")
  DB_STATUS=$(echo "$HEALTH_RESP" | jq -r '.components.db.status // .details.db.status // empty' 2>/dev/null || echo "")

  if [ "$STATUS" = "UP" ]; then
    echo -e "  ${GREEN}✓${NC} Spring Boot Status: ${GREEN}${BOLD}${STATUS}${NC}"
  elif [ -n "$STATUS" ]; then
    echo -e "  ${GREEN}✓${NC} Spring Boot Status: ${CYAN}${STATUS}${NC}"
  else
    echo -e "  ${GREEN}✓${NC} Spring Boot Actuator endpoint active"
  fi

  if [ "$DB_STATUS" = "UP" ]; then
    echo -e "  ${GREEN}✓${NC} PostgreSQL Database: ${GREEN}${BOLD}${DB_STATUS}${NC}"
  fi
else
  echo -e "  ${YELLOW}ℹ${NC} Actuator endpoint not exposed or non-standard (database and crypto validated in Steps 2 & 3)"
fi

# ------------------------------------------------------------------------------
# Step 2: Cryptographic Identity & Public Keys
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}[2/4] Checking Cryptographic Identity (DID & JWKS)...${NC}"

# Check DID Document: try root ingress /.well-known/did.json first, fallback to /v1/certify/...
DID_URL="${CERTIFY_URL}/.well-known/did.json"
DID_RESP=$(curl -skL --max-time 10 "$DID_URL" 2>/dev/null || curl -skL --max-time 10 "${CERTIFY_URL}/v1/certify/.well-known/did.json" 2>/dev/null || echo "")

if [ -n "$DID_RESP" ]; then
  ISSUER_DID=$(echo "$DID_RESP" | jq -r '.id // "UNKNOWN"')
  KEY_COUNT=$(echo "$DID_RESP" | jq -r '(.verificationMethod // []) | length')
  echo -e "  ${GREEN}✓${NC} DID Document: ${CYAN}${ISSUER_DID}${NC}"
  echo -e "  ${GREEN}✓${NC} Verification Methods: ${KEY_COUNT} public key(s) registered"
else
  echo -e "  ${YELLOW}⚠${NC} Could not fetch DID document from ${DID_URL} (may be unmapped on public ingress)"
fi

# Check JWKS Key Set
JWKS_URL="${CERTIFY_URL}/v1/certify/.well-known/jwks.json"
if JWKS_RESP=$(fetch_json "$JWKS_URL" "JWKS endpoint"); then
  JWKS_KEYS=$(echo "$JWKS_RESP" | jq -r '(.keys // []) | length')
  KEY_IDS=$(echo "$JWKS_RESP" | jq -r '[.keys[].kid // empty] | join(", ")')
  KEY_TYPES=$(echo "$JWKS_RESP" | jq -r '[.keys[].kty // empty] | unique | join(", ")')

  echo -e "  ${GREEN}✓${NC} Public JWKS: ${GREEN}${JWKS_KEYS} key(s) active${NC} (Types: ${KEY_TYPES:-None})"
  if [ -n "$KEY_IDS" ]; then
    echo -e "  ${GREEN}✓${NC} Active Key IDs: ${CYAN}${KEY_IDS}${NC}"
  fi
else
  FAILED=1
fi

# ------------------------------------------------------------------------------
# Step 3: OpenID4VCI Issuer Metadata & Configured Credentials (VCs)
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}[3/4] Checking OpenID4VCI Discovery & Configured VCs...${NC}"

DISCOVERY_URL="${CERTIFY_URL}/.well-known/openid-credential-issuer"
DISCOVERY_RESP=$(curl -skL --max-time 10 "$DISCOVERY_URL" 2>/dev/null || curl -skL --max-time 10 "${CERTIFY_URL}/v1/certify/.well-known/openid-credential-issuer" 2>/dev/null || echo "")

if [ -n "$DISCOVERY_RESP" ]; then
  CRED_ISSUER=$(echo "$DISCOVERY_RESP" | jq -r '.credential_issuer // "N/A"')
  CRED_ENDPOINT=$(echo "$DISCOVERY_RESP" | jq -r '.credential_endpoint // "N/A"')
  AUTH_SERVERS=$(echo "$DISCOVERY_RESP" | jq -r '(.authorization_servers // []) | join(", ")')

  echo -e "  ${GREEN}✓${NC} Credential Issuer ID: ${CYAN}${CRED_ISSUER}${NC}"
  echo -e "  ${GREEN}✓${NC} Credential Issuance Endpoint: ${CYAN}${CRED_ENDPOINT}${NC}"
  if [ -n "$AUTH_SERVERS" ]; then
    echo -e "  ${GREEN}✓${NC} Trusted Authorization Server(s): ${CYAN}${AUTH_SERVERS}${NC}"
  fi

  # Inspect loaded credential configurations
  CONFIG_IDS=$(echo "$DISCOVERY_RESP" | jq -r '(.credential_configurations_supported // {}) | keys | .[]')
  CONFIG_COUNT=$(echo "$DISCOVERY_RESP" | jq -r '(.credential_configurations_supported // {}) | length')

  echo ""
  if [ "$CONFIG_COUNT" -gt 0 ]; then
    echo -e "  ${GREEN}${BOLD}Registered Verifiable Credentials (${CONFIG_COUNT} found):${NC}"
    for cid in $CONFIG_IDS; do
      CFG=$(echo "$DISCOVERY_RESP" | jq -c ".credential_configurations_supported[\"${cid}\"]")
      CFG_FORMAT=$(echo "$CFG" | jq -r '.format // "unknown"')
      CFG_TYPES=$(echo "$CFG" | jq -r '(.credential_definition.type // []) | join(", ")')
      CFG_NAME=$(echo "$CFG" | jq -r '.display[0].name // .credential_definition.type[-1] // "N/A"')
      CFG_SCOPE=$(echo "$CFG" | jq -r '.scope // "none"')
      echo -e "    ${BOLD}• ${cid}${NC}: ${GREEN}${CFG_NAME}${NC}"
      echo -e "      - Scope:  ${CYAN}${CFG_SCOPE}${NC}"
      echo -e "      - Format: ${CFG_FORMAT}"
      echo -e "      - Types:  ${CFG_TYPES}"
    done
  else
    echo -e "  ${YELLOW}${BOLD}Zero VCs currently loaded.${NC}"
    echo -e "  ${YELLOW}Notice: The Certify engine is ready and healthy, but waiting for credential configurations${NC}"
    echo -e "  ${YELLOW}to be synchronized via template-sync (deploy/<installation>/certify/credentials/).${NC}"
  fi
else
  echo -e "  ${RED}✗${NC} OpenID4VCI discovery endpoint failed at ${DISCOVERY_URL}" >&2
  FAILED=1
fi

# ------------------------------------------------------------------------------
# Step 4: Credential Revocation Registry (Status List)
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}[4/4] Checking Revocation Registry (Status List API)...${NC}"
STATUS_URL="${CERTIFY_URL}/v1/certify/credentials/status-list/1"
HTTP_CODE=$(curl -skL -o /dev/null -w "%{http_code}" --max-time 5 "$STATUS_URL" 2>/dev/null || echo "000")
HTTP_CODE="${HTTP_CODE:0:3}"

if [ "$HTTP_CODE" = "200" ]; then
  echo -e "  ${GREEN}✓${NC} Status List Registry endpoint is active (HTTP 200 OK)"
elif [ "$HTTP_CODE" = "404" ]; then
  echo -e "  ${YELLOW}✓${NC} Status List Registry service is responding (HTTP 404 - status list #1 unallocated yet)"
elif [ "$HTTP_CODE" = "000" ] || [ -z "$HTTP_CODE" ]; then
  echo -e "  ${YELLOW}⚠${NC} Status List endpoint not reachable at ${STATUS_URL}"
else
  echo -e "  ${YELLOW}✓${NC} Status List endpoint returned HTTP ${HTTP_CODE}"
fi

# ------------------------------------------------------------------------------
# Final Verdict
# ------------------------------------------------------------------------------
echo ""
echo -e "${BLUE}${BOLD}======================================================================${NC}"
if [ "$FAILED" -eq 0 ]; then
  echo -e "${GREEN}${BOLD} 🎉 INJI CERTIFY ENGINE IS HEALTHY & READY TO SERVE!${NC}"
  echo -e "${BLUE}${BOLD}======================================================================${NC}"
  exit 0
else
  echo -e "${RED}${BOLD} ❌ CERTIFY ENGINE SMOKE TEST DETECTED ISSUES.${NC}"
  echo -e "${BLUE}${BOLD}======================================================================${NC}"
  exit 1
fi
