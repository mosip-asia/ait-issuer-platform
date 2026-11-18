#!/usr/bin/env bash
# scripts/sync-sparse.sh: Tracked sparse-checkout synchronization for deployment hosts
set -euo pipefail

TENANT="${1:-${TENANT:-${INSTALLATION:-ait}}}"

if [ ! -d .git ]; then
  exit 0
fi

if ! command -v git >/dev/null 2>&1; then
  exit 0
fi

# 1. Enable tracked git hooks in repository
git config core.hooksPath .githooks 2>/dev/null || true

# 2. Configure sparse-checkout cone mode
git config core.sparseCheckout true
git config core.sparseCheckoutCone true

# 3. Set sparse cone: root files (compose*.yaml, .env.example) are included automatically;
# plus specific tenant directory, base assets, scripts, and docker configs.
git sparse-checkout set --cone "deploy/${TENANT}" deploy/base scripts docker 2>/dev/null || true

# 4. Reapply to materialize all files on disk
git sparse-checkout reapply 2>/dev/null || true
