#!/usr/bin/env bash
# ==============================================================================
# Print a made-up credential from the Wallet through the local Mimoto, and check the PDF. Local only.
# ==============================================================================
# Run from the repository root after scripts/mimoto-up.sh. It runs src/tools/print_check.py in the ait-vc image,
# which reaches Keycloak, Certify, the VDR, the mock Adapter and Mimoto through Traefik by their *.localhost names.
# For the second print it swaps tests/fixtures/print-check-template.html onto the VDR under the credential's
# template name, and puts the original back. The PDFs are kept in a temporary folder the output names.
# The credential file `dev` uses does not map courseRows yet (ask T4), so first the check publishes a mapped copy of
# it to the local stack only (template-sync, then Certify is recreated), and on exit puts the committed file back the
# same way. A credential issued in between carries courseRows; the committed files are never changed.
#
# Usage:
#   ./scripts/print-check.sh [student]     a made-up student of the stand-in realm; default: smoke.json's eligible
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '\r"'; }
[ -f .env ] || { echo "No .env: bring the regular stack up first (scripts/deploy.sh)." >&2; exit 1; }
INSTALLATION=$(env_value INSTALLATION)
IMAGE_TAG=$(env_value IMAGE_TAG)
INST=deploy/$INSTALLATION
OUT=$(mktemp -d)
IMAGE="ghcr.io/mosip-asia/ait-vc:${IMAGE_TAG:-latest}"
CREDENTIAL=$(python3 -c "import json,sys; print(next(e['credentialConfig'] for e in json.load(open(sys.argv[1])) if e.get('mimotoTemplate')))" "$INST/smoke.json")
# The stack's own Compose files, as mimoto-up.sh names them, plus the overlay so Compose knows Mimoto too.
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(env_value COMPOSE_FILE):compose.mimoto.yaml" docker compose "$@"; }
wait_certify() {
  local i
  for i in $(seq 1 60); do
    curl -sf -o /dev/null --max-time 5 http://issuer.localhost/.well-known/openid-credential-issuer && return 0
    sleep 5
  done
  echo "print-check: Certify didn't answer within 300s" >&2; return 1
}
PUBLISHED=
# The command that puts the committed credential files back into Certify, as printed when restore() fails.
RESTORE_COMMAND="COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=$(env_value COMPOSE_FILE):compose.mimoto.yaml docker compose up -d --force-recreate template-sync certify"
restore() {  # the committed credential files back into Certify; fails when it can't
  [ -n "$PUBLISHED" ] || return 0
  PUBLISHED=
  if compose up -d --force-recreate template-sync certify >/dev/null 2>&1 && wait_certify; then
    echo "restored the committed credential file in Certify"
  else
    echo "print-check: Certify may still hold the mapped copy of the credential file. From the repository root, run:" >&2
    echo "  $RESTORE_COMMAND" >&2
    return 1
  fi
}
MAPPED=
finish() {  # the exit status stays the check's own, or becomes 1 when the restore failed
  local rc=$?
  restore || [ "$rc" -ne 0 ] || rc=1
  rm -rf "$MAPPED"
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT TERM

MAPPED=$(mktemp -d)
docker run --rm --user "$(id -u):$(id -g)" \
  -v "$PWD/src/tools/map_course_rows.py:/check/map_course_rows.py:ro" \
  -v "$PWD/$INST/certify/credentials:/credentials:ro" -v "$MAPPED:/out" "$IMAGE" \
  python /check/map_course_rows.py --credentials /credentials --credential "$CREDENTIAL" --out /out
PUBLISHED=1
compose run --rm --no-deps -v "$MAPPED:/app/config/credentials:ro" template-sync >/dev/null
compose up -d --no-deps --force-recreate certify >/dev/null 2>&1
wait_certify
echo "published a copy of $CREDENTIAL that maps courseRows to the local Certify (until this check ends)"

docker run --rm --user "$(id -u):$(id -g)" \
  --add-host auth.localhost:host-gateway --add-host issuer.localhost:host-gateway \
  --add-host vdr.localhost:host-gateway --add-host adapter.localhost:host-gateway \
  --add-host mimoto.localhost:host-gateway \
  -v "$PWD/src/tools/print_check.py:/check/print_check.py:ro" \
  -v "$PWD/tests/fixtures/print-check-template.html:/check/template.html:ro" \
  -v "$PWD/$INST/smoke.json:/installation/smoke.json:ro" \
  -v "$PWD/$INST/mock/keycloak-realm.json:/installation/mock/keycloak-realm.json:ro" \
  -v "$PWD/$INST/vcga/issuers.json:/installation/vcga/issuers.json:ro" \
  -v "$PWD/$INST/vdr/templates:/templates" \
  -v "$OUT:/out" \
  "ghcr.io/mosip-asia/ait-vc:${IMAGE_TAG:-latest}" \
  python /check/print_check.py --installation /installation --templates /templates \
    --test-template /check/template.html --out /out --templates-shown "$INST/vdr/templates" ${1:+--student "$1"} \
  && status=0 || status=$?
echo "PDFs: $OUT"
exit "$status"
