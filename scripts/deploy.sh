#!/usr/bin/env bash
# ==============================================================================
# Deploy or update the AIT Issuer Platform Compose stack on the host.
# ==============================================================================
# Usage:
#   ./scripts/deploy.sh [installation] [--tag <tag>] [--wipe] [--build] [--sparse]
#
# Examples:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh ait
#   ./scripts/deploy.sh ait --tag v0.0.6
#   ./scripts/deploy.sh ait --wipe
#   ./scripts/deploy.sh hackathon
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

log_info() { echo -e "${BLUE}${BOLD}[DEPLOY]${NC} $*"; }
log_ok() { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}${BOLD}[ERROR]${NC} $*" >&2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

update_env_var() {
  local file="$1"
  local key="$2"
  local val="$3"

  if grep -E "^[[:space:]]*${key}=" "$file" >/dev/null 2>&1; then
    local tmp
    tmp="$(mktemp)"
    sed -E "s|^[[:space:]]*${key}=.*|${key}=${val}|" "$file" > "$tmp"
    cat "$tmp" > "$file"
    rm -f "$tmp"
  else
    echo "${key}=${val}" >> "$file"
  fi
}

INSTALLATION="${INSTALLATION:-${TENANT:-ait}}"
TENANT="${TENANT:-$INSTALLATION}"
WIPE_FLAG=false
BUILD_FLAG=false
INIT_ENV_FLAG=false
SPARSE_FLAG=false
DEPLOY_TAG="${IMAGE_TAG:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --wipe|wipe)
      WIPE_FLAG=true
      shift
      ;;
    --build|build)
      BUILD_FLAG=true
      shift
      ;;
    --init-env|init-env)
      INIT_ENV_FLAG=true
      shift
      ;;
    --sparse|sparse)
      SPARSE_FLAG=true
      shift
      ;;
    --tag)
      DEPLOY_TAG="$2"
      shift 2
      ;;
    --tenant)
      INSTALLATION="$2"
      TENANT="$2"
      shift 2
      ;;
    --installation)
      INSTALLATION="$2"
      TENANT="$2"
      shift 2
      ;;
    -*)
      log_err "Unknown option: $1"
      exit 1
      ;;
    *)
      INSTALLATION="$1"
      TENANT="$1"
      shift
      ;;
  esac
done

log_info "Starting deployment of ait-issuer-platform (tenant: ${INSTALLATION})..."
export INSTALLATION
export TENANT

# 0. Sparse checkout (keep server minimal: only deploy/${INSTALLATION}, deploy/base, scripts, docker)
IS_SPARSE="$(git config --get core.sparseCheckout 2>/dev/null || true)"
if [ "$SPARSE_FLAG" = true ] || [ "${SPARSE_CHECKOUT:-false}" = "true" ] || [ "$IS_SPARSE" = "true" ]; then
  if [ -d .git ] && command -v git >/dev/null 2>&1; then
    log_info "Configuring git sparse-checkout (deploy/${INSTALLATION}, deploy/base, scripts, docker)..."
    git config core.sparseCheckout true
    git config core.sparseCheckoutCone true
    git sparse-checkout set --cone "deploy/${INSTALLATION}" deploy/base scripts docker 2>/dev/null || true
    git sparse-checkout reapply 2>/dev/null || true
  fi
fi

# 1. Verify .env is set and up-to-date against .env.example
if [ "$INIT_ENV_FLAG" = true ] && [ ! -f .env ]; then
  if [ -f .env.example ]; then
    log_warn "Creating .env from .env.example (--init-env requested)..."
    cp .env.example .env
  fi
fi

if [ ! -f .env ]; then
  log_err "No .env file found! Deployment requires an environment configuration."
  log_info "Please create .env from .env.example and configure environment settings:"
  echo "    cp .env.example .env"
  exit 1
fi

log_info "Checking environment configuration against .env.example..."
if ! bash scripts/check-env.sh; then
  log_err ".env configuration check failed. Update .env before deploying."
  exit 1
fi
log_ok "Environment configuration is verified and up-to-date."

# 2. Synchronize deployment tag and tenant with .env
if [ -z "$DEPLOY_TAG" ]; then
  if [ -d .git ] && command -v git >/dev/null 2>&1; then
    DEPLOY_TAG="$(git describe --tags --exact-match 2>/dev/null || true)"
  fi
fi

if [ -n "$DEPLOY_TAG" ]; then
  log_info "Updating IMAGE_TAG in .env to match deployment tag '${DEPLOY_TAG}'..."
  update_env_var ".env" "IMAGE_TAG" "$DEPLOY_TAG"
  export IMAGE_TAG="$DEPLOY_TAG"
else
  CURRENT_TAG="$(grep -E '^IMAGE_TAG=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r' || echo "latest")"
  export IMAGE_TAG="${CURRENT_TAG:-latest}"
  log_info "Using existing IMAGE_TAG '${IMAGE_TAG}' from .env."
fi

# Synchronize INSTALLATION and optional TENANT with .env
update_env_var ".env" "INSTALLATION" "$INSTALLATION"
if grep -E "^[[:space:]]*TENANT=" .env >/dev/null 2>&1; then
  update_env_var ".env" "TENANT" "$INSTALLATION"
fi

# Determine Certify Base URL (prefer CERTIFY_PUBLIC_BASE_URL, default to http://issuer.localhost)
CERTIFY_URL="$(grep -E '^CERTIFY_PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r' || echo "")"
CERTIFY_URL="${CERTIFY_URL:-http://issuer.localhost}"

# 3. Pull pre-built images or build locally
if [ "$BUILD_FLAG" = true ]; then
  log_info "Building images locally (--build specified)..."
  bash scripts/build.sh
else
  log_info "Pulling pre-built images from container registry..."
  docker compose pull --quiet --ignore-pull-failures || log_warn "Pull completed with warnings (continuing with cached images if present)..."
  if ! docker image inspect certify-template-sync:local >/dev/null 2>&1; then
    log_info "Building local helper services (template-sync)..."
    docker compose build template-sync --quiet || true
  fi
fi

# 4. Tear down existing stack
log_info "Tearing down existing stack..."
if [ "$WIPE_FLAG" = true ]; then
  log_warn "Wiping database and volumes (--wipe specified)..."
  docker compose down -v --remove-orphans
else
  docker compose down --remove-orphans
fi

# 5. Start fresh stack
log_info "Starting compose services..."
docker compose up -d --remove-orphans

# 6. Wait for Inji Certify to initialize
log_info "Waiting for Inji Certify issuer engine to initialize at ${CERTIFY_URL}..."
TIMEOUT=90
ELAPSED=0

while [ "$ELAPSED" -lt "$TIMEOUT" ]; do
  if curl -sf "${CERTIFY_URL}/.well-known/openid-credential-issuer" >/dev/null 2>&1 || \
     curl -sf "${CERTIFY_URL}/v1/certify/.well-known/openid-credential-issuer" >/dev/null 2>&1; then
    log_ok "Inji Certify is ready!"
    break
  fi
  sleep 3
  ELAPSED=$((ELAPSED + 3))
done

if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
  log_err "Inji Certify failed to become ready within ${TIMEOUT}s. Recent logs:"
  docker compose logs --tail 50 certify
  exit 1
fi

# 7. Run post-deployment issuance smoke test
log_info "Running post-deployment issuance smoke test..."
if [ "$INSTALLATION" = "hackathon" ]; then
  SMOKE_CMD="bash scripts/smoke-test.sh ${CERTIFY_URL} hack-2026-0001 developer-passport"
else
  SMOKE_CMD="bash scripts/smoke-test.sh ${CERTIFY_URL}"
fi
if ! eval "$SMOKE_CMD"; then
  log_err "Post-deployment smoke test failed. Recent logs:"
  docker compose logs --tail 50 certify
  exit 1
fi
log_ok "Post-deployment smoke test passed."

# 8. Stack status summary
echo ""
echo -e "${GREEN}${BOLD}Stack status:${NC}"
docker compose ps
echo ""
echo -e "${GREEN}${BOLD}✅ Deployment of ait-issuer-platform completed successfully!${NC}"
