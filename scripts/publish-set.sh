#!/usr/bin/env bash
# ==============================================================================
# Publish a VC Lab set (the zip its Download gives) to the local stack. Local only.
# ==============================================================================
# Run from anywhere, after scripts/deploy.sh and, to print, scripts/mimoto-up.sh: run mimoto-up.sh BEFORE publishing.
# Running it, or deploy.sh, afterwards runs compose up, which re-syncs the committed credential files and undoes the
# publish (the template and the Background stay). It
#   1. refuses unless this is the local stack (compose.mock.yaml in COMPOSE_FILE, Certify on the local Keycloak),
#      so it can never act on a deployment: there, publishing is infra's step (ask T3 in
#      docs/guides/print-from-the-wallet.md);
#   2. puts the template on the VDR as <issuer id>-<credential configuration id>-template.html and warns that git
#      tracks that file; puts the Background at <credential configuration id>/background.png under the VDR's
#      templates folder (git-ignored), whatever its type, or removes the one there when the set has none, so the VDR
#      mirrors the set (src/tools/publish_set.py);
#   3. writes Certify's live DID into .env when .env holds another one;
#   4. loads the credential file into Certify through template-sync, from a temporary folder holding the
#      Installation's credential files with the set's in place of the committed one, then recreates Certify. The
#      set's file is loaded under the live DID, and, with a Background, with its address in
#      display[0].background_image.uri (VC Lab's download holds neither).
# Publishing the same set again gives the same state. The next Wallet print uses the set: print it with
# ./scripts/print-check.sh --published. The plain print check publishes its own test copy and, on exit, puts the
# committed credential files back into Certify.
#
# Usage:
#   ./scripts/publish-set.sh <set.zip> <issuer id>      <issuer id>: the Mimoto issuer id, AITUniversity for AIT
# ==============================================================================
set -euo pipefail

usage() { echo "Usage: scripts/publish-set.sh <set.zip> <issuer id>" >&2; exit 1; }
[[ $# -eq 2 ]] || usage
[[ -f $1 ]] || { echo "publish-set: no such file: $1" >&2; usage; }
SET=$(readlink -f "$1")
ISSUER_ID=$2
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROG=publish-set
source scripts/local-stack.sh
load_stack_env
require_local_certify

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
python3 src/tools/publish_set.py --set "$SET" "--issuer-id=$ISSUER_ID" --installation "$INSTALLATION" \
  --credentials-out "$TMP/credentials"
chmod -R a+rX "$TMP"

write_live_did
compose run --rm -T -e CREDENTIALS_DIR=/test-credentials -v "$TMP/credentials:/test-credentials:ro" template-sync
compose up -d --no-deps --force-recreate certify
wait_for "$CERTIFY/.well-known/openid-credential-issuer" "Certify" || die "Certify didn't come back"
echo "published the set: print it with ./scripts/print-check.sh --published (run mimoto-up.sh before publishing; running it or deploy.sh now puts the committed credential files back)"
