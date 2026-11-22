#!/usr/bin/env bash
# ==============================================================================
# Parity: VC Lab shows what the Wallet prints. One made-up set through VC Lab's preview and through the local Mimoto,
# compared. Local only, not in CI.
# ==============================================================================
# Run from anywhere, after scripts/deploy.sh and scripts/mimoto-up.sh (docs/guides/print-from-the-wallet.md). It
#   1. puts the Thai font the set's template loads through @font-face on the VDR (scripts/thai-font.sh), in a
#      git-ignored folder it removes afterwards;
#   2. runs the made-up set through VC Lab's HTTP API (src/tools/parity_check.py preview): uploads its four files one
#      at a time, and keeps /preview.pdf and the zip /download gives;
#   3. publishes that zip with scripts/publish-set.sh, and prints it from the Wallet with
#      scripts/print-check.sh --published;
#   4. compares the two PDFs (parity_check.py compare): the page text with whitespace collapsed, the pixel sizes of the
#      images each page draws, and the font names. Each difference is named, and the exit status is 1.
# On exit it puts back what publishing changed: the template and the Background the VDR held, and the committed
# credential files in Certify. The set and both PDFs are kept in a temporary folder the output names.
#
# Usage:
#   ./scripts/parity-check.sh [student]     a made-up student of the stand-in realm; default: smoke.json's eligible
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PROG=parity-check
source scripts/local-stack.sh
load_stack_env
STUDENT=${1:-}
INST=deploy/$INSTALLATION
TAG=$(env_value IMAGE_TAG || true)
IMAGE=ghcr.io/mosip-asia/ait-vc:${TAG:-latest}
OUT=$(mktemp -d)
FONT_DIR=$INST/vdr/templates/parity-check
ENTRY="next(e for e in d if e.get('mimotoTemplate'))"
CREDENTIAL=$(json "$INST/smoke.json" "$ENTRY['credentialConfig']")
TEMPLATE=$INST/vdr/templates/$(json "$INST/smoke.json" "$ENTRY['mimotoTemplate']")
BACKGROUND=$INST/vdr/templates/$CREDENTIAL/background.png
ISSUER_ID=$(json "$INST/vcga/issuers.json" "d['issuers'][0]['issuer_id']")

# What publishing changes, kept so the exit can put it back.
cp "$TEMPLATE" "$OUT/template.kept"
[[ ! -f $BACKGROUND ]] || cp "$BACKGROUND" "$OUT/background.kept"
PUBLISHED=0
put_back() {
  local rc=$?
  rm -rf "$FONT_DIR"
  cat "$OUT/template.kept" > "$TEMPLATE"  # in place: the VDR's bind mount keeps the same file
  if [[ -f $OUT/background.kept ]]; then
    cat "$OUT/background.kept" > "$BACKGROUND"
  else
    rm -f "$BACKGROUND"
  fi
  if [[ $PUBLISHED == 1 ]]; then
    if COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES:compose.mimoto.yaml" \
         docker compose up -d --force-recreate template-sync certify >/dev/null 2>&1 \
       && wait_for "$CERTIFY/.well-known/openid-credential-issuer" "Certify" >/dev/null; then
      echo "put back the template and the Background the VDR held, and the committed credential files in Certify"
    else
      echo "$PROG: Certify may still hold the set's credential file. From the repository root, run:" >&2
      echo "  COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=$STACK_FILES:compose.mimoto.yaml docker compose up -d --force-recreate template-sync certify" >&2
      [[ $rc -ne 0 ]] || rc=1
    fi
  fi
  exit "$rc"
}
trap put_back EXIT
trap 'exit 130' INT TERM

check() {  # parity_check.py in the ait-vc image, which has httpx and pypdf; it reaches VC Lab and the Adapter by name
  docker run --rm --user "$(id -u):$(id -g)" \
    --add-host lab.localhost:host-gateway --add-host adapter.localhost:host-gateway \
    -v "$PWD/src/tools/parity_check.py:/check/parity_check.py:ro" \
    -v "$PWD/src/tools/print_check.py:/check/print_check.py:ro" \
    -v "$PWD/src/tools/map_course_rows.py:/check/map_course_rows.py:ro" \
    -v "$PWD/mock/adapter/ait_courses.py:/check/ait_courses.py:ro" \
    -v "$PWD/tests/fixtures/parity-template.html:/check/parity-template.html:ro" \
    -v "$PWD/$INST:/installation:ro" \
    -v "$OUT:/out" \
    "$IMAGE" python /check/parity_check.py "$@"
}

bash scripts/thai-font.sh "$FONT_DIR" "$IMAGE"
check preview --installation /installation --template /check/parity-template.html --out /out ${STUDENT:+--student "$STUDENT"}
PUBLISHED=1
./scripts/publish-set.sh "$OUT/set.zip" "$ISSUER_ID"
printed=$(./scripts/print-check.sh --published $STUDENT) || { echo "$printed"; exit 1; }
echo "$printed"
cp "$(sed -n 's/^PDFs: //p' <<<"$printed")/published.pdf" "$OUT/wallet.pdf"
echo "the set and both PDFs (preview.pdf from VC Lab, wallet.pdf from Mimoto): $OUT"
check compare /out/preview.pdf /out/wallet.pdf
