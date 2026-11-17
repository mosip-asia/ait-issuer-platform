#!/usr/bin/env bash
# ==============================================================================
# Deploy or update the AIT Issuer Platform Compose stack on the host.
# ==============================================================================
# Usage:
#   ./scripts/deploy.sh [installation] [--wipe]
#
# Examples:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh ait
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

INSTALLATION="${1:-${INSTALLATION:-ait}}"
# If first argument is a flag, keep default installation 'ait'
if [ "$INSTALLATION" = "--wipe" ] || [ "$INSTALLATION" = "wipe" ] || [ "$INSTALLATION" = "--build" ] || [ "$INSTALLATION" = "build" ] || [ "$INSTALLATION" = "--init-env" ] || [ "$INSTALLATION" = "--sparse" ]; then
  INSTALLATION="ait"
fi

WIPE_FLAG=false
BUILD_FLAG=false
INIT_ENV_FLAG=false
SPARSE_FLAG=false
for arg in "$@"; do
  if [ "$arg" = "--wipe" ] || [ "$arg" = "wipe" ]; then
    WIPE_FLAG=true
  elif [ "$arg" = "--build" ] || [ "$arg" = "build" ]; then
    BUILD_FLAG=true
  elif [ "$arg" = "--init-env" ] || [ "$arg" = "init-env" ]; then
    INIT_ENV_FLAG=true
  elif [ "$arg" = "--sparse" ] || [ "$arg" = "sparse" ]; then
    SPARSE_FLAG=true
  fi
done

log_info "Starting deployment of ait-issuer-platform (installation: ${INSTALLATION})..."
export INSTALLATION

# 0. Sparse checkout (keep server minimal: only deploy, scripts, docker)
if [ "$SPARSE_FLAG" = true ] || [ "${SPARSE_CHECKOUT:-false}" = "true" ]; then
  if [ -d .git ] && command -v git >/dev/null 2>&1; then
    log_info "Configuring git sparse-checkout (deploy, scripts, docker)..."
    git config core.sparseCheckout true
    git sparse-checkout set --cone deploy scripts docker 2>/dev/null || true
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

# Determine Certify Base URL (prefer CERTIFY_PUBLIC_BASE_URL, default to http://issuer.localhost)
CERTIFY_URL="$(grep -E '^CERTIFY_PUBLIC_BASE_URL=' .env 2>/dev/null | cut -d '=' -f2 | tr -d ' "\r' || echo "")"
CERTIFY_URL="${CERTIFY_URL:-http://issuer.localhost}"

# 2. Pull pre-built images or build locally
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

# 3. Tear down existing stack
log_info "Tearing down existing stack..."
if [ "$WIPE_FLAG" = true ]; then
  log_warn "Wiping database and volumes (--wipe specified)..."
  docker compose down -v --remove-orphans
else
  docker compose down --remove-orphans
fi

# 4. Start fresh stack
log_info "Starting compose services..."
docker compose up -d --remove-orphans

# 5. Wait for Inji Certify to initialize
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
  docker compose logs --tail 50 service
  exit 1
fi

# 7. Run post-deployment issuance smoke test
log_info "Running post-deployment issuance smoke test..."
if ! bash scripts/smoke-test.sh "${CERTIFY_URL}"; then
  log_err "Post-deployment smoke test failed. Recent logs:"
  docker compose logs --tail 50 service
  exit 1
fi
log_ok "Post-deployment smoke test passed."

# 8. Stack status summary
echo ""
echo -e "${GREEN}${BOLD}Stack status:${NC}"
docker compose ps
echo ""
echo -e "${GREEN}${BOLD}✅ Deployment of ait-issuer-platform completed successfully!${NC}"
