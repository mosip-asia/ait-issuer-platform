#!/usr/bin/env bash
# ==============================================================================
# Derive or Generate did:key Identifiers for Inji Certify
#
# Runs through `uv run tools did` or falls back to direct python execution.
#
# Usage:
#   ./scripts/derive-did.py --generate deploy/ait/private_key/CERTIFY_PKCS12/local.p12
#   ./scripts/derive-did.py https://issuer-dev.ait-vc.dpi.ait.ac.th
# ==============================================================================
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

if command -v uv >/dev/null 2>&1; then
  exec uv run tools did "$@"
else
  export PYTHONPATH="${ROOT_DIR}/src:${PYTHONPATH:-}"
  exec python3 -m tools.did "$@"
fi
