#!/usr/bin/env bash
# ==============================================================================
# Build and package AIT Issuer Platform artifacts (JAR & Docker images)
# ==============================================================================
# Usage:
#   ./scripts/build.sh [options]
#
# Options:
#   --tag <tag>           Image tag (default: git tag/commit or 'latest')
#   --registry <registry> Container registry (default: ghcr.io/mosip-asia)
#   --push                Push built images to the container registry
#   --jar-only            Only build the Inji Certify SPI plugin JAR
#   --images-only         Only build Docker images (assumes JAR is built)
#   --no-cache            Pass --no-cache to docker build
#   -h, --help            Show this help message
#
# Examples:
#   ./scripts/build.sh
#   ./scripts/build.sh --tag v0.2.0 --push
#   ./scripts/build.sh --jar-only
# ==============================================================================
set -euo pipefail

# ANSI color codes
BOLD="\033[1m"
GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
YELLOW="\033[1;33m"
NC="\033[0m"

log_info() { echo -e "${BLUE}${BOLD}[BUILD]${NC} $*"; }
log_ok() { echo -e "${GREEN}${BOLD}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}${BOLD}[WARN]${NC} $*"; }
log_err() { echo -e "${RED}${BOLD}[ERROR]${NC} $*" >&2; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

# Defaults
REGISTRY="${CONTAINER_REGISTRY:-ghcr.io/mosip-asia}"
TAG="${IMAGE_TAG:-}"
PUSH=false
JAR_ONLY=false
IMAGES_ONLY=false
NO_CACHE=""

# Determine default tag if not specified
if [ -z "$TAG" ]; then
  if git describe --tags --exact-match >/dev/null 2>&1; then
    TAG="$(git describe --tags --exact-match)"
  elif [ -n "${GITHUB_REF_NAME:-}" ]; then
    TAG="${GITHUB_REF_NAME}"
  else
    TAG="latest"
  fi
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)
      TAG="$2"
      shift 2
      ;;
    --registry)
      REGISTRY="$2"
      shift 2
      ;;
    --push)
      PUSH=true
      shift
      ;;
    --jar-only)
      JAR_ONLY=true
      shift
      ;;
    --images-only)
      IMAGES_ONLY=true
      shift
      ;;
    --no-cache)
      NO_CACHE="--no-cache"
      shift
      ;;
    -h|--help)
      sed -ne '/^#/!q;s/^#//;p' "$0"
      exit 0
      ;;
    *)
      log_err "Unknown argument: $1"
      exit 1
      ;;
  esac
done

log_info "Build configuration:"
echo "  Registry:    $REGISTRY"
echo "  Image Tag:   $TAG"
echo "  Push:        $PUSH"
echo "  Target dir:  $ROOT_DIR"

# ==============================================================================
# 1. Build Inji Certify Plugin JAR
# ==============================================================================
build_jar() {
  log_info "Building Inji Certify DataProviderPlugin JAR (src/issuer)..."
  if command -v mvn >/dev/null 2>&1; then
    log_info "Using host Maven ($(mvn -version | head -n 1))..."
    mvn -B -f src/issuer/pom.xml package -DskipTests
  else
    log_info "Host Maven not found. Using compiler container via Docker Compose..."
    docker compose -f compose.certify-build.yaml run --rm plugin-builder
  fi

  local jar="src/issuer/target/issuer-data-provider-plugin.jar"
  if [ -f "$jar" ]; then
    log_ok "Plugin JAR built successfully: $jar ($(du -h "$jar" | cut -f1))"
  else
    log_err "Plugin JAR not found at $jar after build!"
    exit 1
  fi
}

if [ "$IMAGES_ONLY" = false ]; then
  build_jar
fi

if [ "$JAR_ONLY" = true ]; then
  log_ok "JAR build finished (--jar-only requested). Exiting."
  exit 0
fi

# ==============================================================================
# 2. Build Docker Images
# ==============================================================================
build_image() {
  local image_name="$1"
  local dockerfile="$2"
  local context="${3:-.}"

  local full_tag="${REGISTRY}/${image_name}:${TAG}"
  local latest_tag="${REGISTRY}/${image_name}:latest"

  log_info "Building image: ${full_tag} (${dockerfile})..."

  local tag_args=("-t" "$full_tag")
  if [ "$TAG" != "latest" ]; then
    tag_args+=("-t" "$latest_tag")
  fi

  # shellcheck disable=SC2086
  docker build $NO_CACHE "${tag_args[@]}" -f "$dockerfile" "$context"
  log_ok "Built ${full_tag}"

  if [ "$PUSH" = true ]; then
    log_info "Pushing ${full_tag}..."
    docker push "$full_tag"
    if [ "$TAG" != "latest" ]; then
      log_info "Pushing ${latest_tag}..."
      docker push "$latest_tag"
    fi
    log_ok "Pushed ${image_name} successfully."
  fi
}

log_info "Starting Docker image builds..."

# 1. Inji Certify with pre-baked plugin
build_image "ait-certify" "docker/Dockerfile.certify" "."

# 2. Certify Template-sync
build_image "ait-certify-template-sync" "docker/Dockerfile.template-sync" "."

# 3. Verifier UI
build_image "ait-verify-ui" "src/verifier/Dockerfile" "."

# 4. VC Lab
build_image "ait-vc-lab" "docker/Dockerfile.vc-lab" "."

log_ok "All Docker images built successfully!"
if [ "$PUSH" = true ]; then
  log_ok "All Docker images pushed to ${REGISTRY}!"
fi
