#!/usr/bin/env bash
# ==============================================================================
# Environment Configuration Validator
# ==============================================================================
# Validates that a deployment .env file exists, is non-empty, and holds every
# configuration key required by .env.example with non-empty critical values.
#
# Usage:
#   ./scripts/check-env.sh [env-file] [example-file]
#
# Examples:
#   ./scripts/check-env.sh
#   ./scripts/check-env.sh .env .env.example
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

log_info() { echo -e "${BLUE}${BOLD}[ENV]${NC} $*"; }
log_ok() { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}${BOLD}[ERROR]${NC} $*" >&2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

ENV_FILE="${1:-.env}"
EXAMPLE_FILE="${2:-.env.example}"

# 1. Ensure .env.example exists as canonical contract
if [ ! -f "$EXAMPLE_FILE" ]; then
  log_err "Canonical example file '$EXAMPLE_FILE' not found in $ROOT_DIR!"
  exit 1
fi

# 2. Check if target .env exists
if [ ! -f "$ENV_FILE" ]; then
  log_err "Environment file '$ENV_FILE' does not exist!"
  log_info "To create it, copy '$EXAMPLE_FILE' and configure environment settings:"
  echo "    cp $EXAMPLE_FILE $ENV_FILE"
  exit 1
fi

# 3. Check if target .env is non-empty
if [ ! -s "$ENV_FILE" ]; then
  log_err "Environment file '$ENV_FILE' exists but is empty (0 bytes)!"
  exit 1
fi

# 4. Compare configuration keys between .env.example and .env
# Extract all key names defined on non-comment lines
mapfile -t EXAMPLE_KEYS < <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "$EXAMPLE_FILE" | cut -d '=' -f1)

missing_keys=()
empty_critical_keys=()

# Critical keys that must have a non-empty value for the platform to function
CRITICAL_KEYS=(
  "INSTALLATION"
  "IMAGE_TAG"
  "CERTIFY_PUBLIC_BASE_URL"
  "AUTH_SERVER_ISSUER"
  "AUTH_SERVER_JWKS_URL"
  "CERTIFY_DID"
  "CERTIFY_RECORD_URL"
  "VDR_BASE_URL"
  "VCGA_BASE_URL"
  "INJI_WEB_URL"
  "INJI_VERIFY_URL"
)

is_critical() {
  local target="$1"
  for ck in "${CRITICAL_KEYS[@]}"; do
    if [ "$ck" = "$target" ]; then
      return 0
    fi
  done
  return 1
}

for key in "${EXAMPLE_KEYS[@]}"; do
  # Check if key is declared in target .env
  if ! grep -E "^[[:space:]]*${key}=" "$ENV_FILE" >/dev/null 2>&1; then
    missing_keys+=("$key")
    continue
  fi

  # Extract value
  val="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | head -n 1 | cut -d '=' -f2- | tr -d ' "\r\n')"
  if is_critical "$key" && [ -z "$val" ]; then
    empty_critical_keys+=("$key")
  fi
done

has_errors=false

if [ "${#missing_keys[@]}" -gt 0 ]; then
  has_errors=true
  log_err "Missing ${#missing_keys[@]} configuration key(s) in '$ENV_FILE' (required by '$EXAMPLE_FILE'):"
  for k in "${missing_keys[@]}"; do
    example_line="$(grep -E "^${k}=" "$EXAMPLE_FILE" | head -n 1)"
    echo -e "    ${RED}✗${NC} ${BOLD}${k}${NC}  (example: ${example_line})"
  done
fi

if [ "${#empty_critical_keys[@]}" -gt 0 ]; then
  has_errors=true
  log_err "The following ${#empty_critical_keys[@]} critical key(s) are empty in '$ENV_FILE':"
  for k in "${empty_critical_keys[@]}"; do
    example_line="$(grep -E "^${k}=" "$EXAMPLE_FILE" | head -n 1)"
    echo -e "    ${RED}✗${NC} ${BOLD}${k}${NC} is empty  (example: ${example_line})"
  done
fi

if [ "$has_errors" = true ]; then
  log_err "Environment configuration validation failed for '$ENV_FILE'."
  exit 1
fi

log_ok "All ${#EXAMPLE_KEYS[@]} configuration keys in '$ENV_FILE' match '$EXAMPLE_FILE' and are valid."
exit 0
