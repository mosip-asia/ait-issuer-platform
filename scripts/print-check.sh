#!/usr/bin/env bash
# ==============================================================================
# Print a made-up credential from the Wallet through the local Mimoto, and check the PDF. Local only.
# ==============================================================================
# Run from the repository root after scripts/mimoto-up.sh. It runs src/tools/print_check.py in the ait-vc image,
# which reaches Keycloak, Certify, the VDR, the mock Adapter and Mimoto through Traefik by their *.localhost names.
# For the second print it swaps tests/fixtures/print-check-template.html onto the VDR under the credential's
# template name, and puts the original back. The PDFs are kept in a temporary folder the output names.
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
CERTIFY=http://issuer.localhost
IMAGE=ghcr.io/mosip-asia/ait-vc:${IMAGE_TAG:-latest}
# The Thai font the test template loads through @font-face. It is TLWG's Loma, freely licensed (GPL-2+ with a font
# exception; the package's copyright file is kept next to the font for the run), taken from Debian's
# fonts-tlwg-loma-ttf at run time, so no font is committed. It lives in a git-ignored folder of the VDR's templates
# and is removed afterwards. src/tools/print_check.py's FONT_NAME and the test template name this font.
FONT_DIR=$INST/vdr/templates/print-check
PUBLISHED=0

compose() { docker compose "$@"; }
quiet() {  # run a command, showing its output only when it fails
  local output
  output=$("$@" 2>&1) || { echo "$output" >&2; return 1; }
}
wait_certify() {
  for _ in $(seq 1 60); do
    curl -sf -o /dev/null "$CERTIFY/.well-known/openid-credential-issuer" && return 0
    sleep 3
  done
  echo "FAIL setup: Certify didn't come back within 180s" >&2
  return 1
}
cleanup() {
  rm -rf "$FONT_DIR"
  [[ -z ${TEST_CREDENTIALS:-} ]] || { [[ $PUBLISHED == 1 ]] || rm -rf "$TEST_CREDENTIALS"; }
  if [[ $PUBLISHED == 1 ]]; then  # put the credential file back as git has it
    quiet compose run --rm -T template-sync && quiet compose restart certify && wait_certify \
      && echo "restored the published credential file" \
      || echo "could not restore the published credential file: run scripts/deploy.sh $INSTALLATION" >&2
    rm -rf "$TEST_CREDENTIALS"
  fi
}
trap cleanup EXIT

# The credential file git tracks has no Background address (a deployment's VDR may hold no Background), so when the
# published one has none, publish a copy that points display[0].background_image at the VDR's templates folder,
# where the print check places its made-up Background: <VDR>/templates/<credential configuration id>/background.png.
# The copy is made once (test_credentials) and every edit changes it in place; publish_test_credentials then syncs it
# and restarts Certify, and cleanup puts the credential files back as git has them.
CREDENTIAL=$(python3 -c "import json,sys; print(next(e['credentialConfig'] for e in json.load(open(sys.argv[1])) if e.get('mimotoTemplate')))" "$INST/smoke.json")   || { echo "FAIL setup: $INST/smoke.json names no mimotoTemplate" >&2; exit 1; }
published_uri() {
  curl -sf "$CERTIFY/.well-known/openid-credential-issuer" | python3 -c "
import json,sys
d=json.load(sys.stdin)['credential_configurations_supported'][sys.argv[1]]['display'][0]
print((d.get('background_image') or {}).get('uri',''))" "$CREDENTIAL"
}
TEST_CREDENTIALS=""
test_credentials() {
  [[ -z $TEST_CREDENTIALS ]] || return 0
  TEST_CREDENTIALS=$(mktemp -d)
  cp "$INST"/certify/credentials/*.json "$TEST_CREDENTIALS"/
  chmod -R a+rX "$TEST_CREDENTIALS"
}
add_background_address() {  # the copy's display[0].background_image, pointing at the VDR's templates folder
  python3 -c "
import json,sys
p=sys.argv[1]+'/'+sys.argv[2]+'.json'
c=json.load(open(p,encoding='utf-8'))
c['display'][0]['background_image']={'uri':'http://vdr.localhost/templates/'+sys.argv[2]+'/background.png'}
json.dump(c,open(p,'w',encoding='utf-8'),indent=2)" "$TEST_CREDENTIALS" "$CREDENTIAL"
}
publish_test_credentials() {
  PUBLISHED=1
  quiet compose run --rm -T -e CREDENTIALS_DIR=/test-credentials -v "$TEST_CREDENTIALS:/test-credentials:ro" template-sync
  quiet compose restart certify
  wait_certify
}
# A failing curl or an unknown credential id must stop the check, not read as "no Background address".
BACKGROUND_URI=$(published_uri)   || { echo "FAIL setup: couldn't read $CREDENTIAL's display from Certify's metadata at $CERTIFY: is the stack up?" >&2; exit 1; }
if [[ -z $BACKGROUND_URI ]]; then
  test_credentials
  add_background_address
  publish_test_credentials
  echo "published a test Background address for $CREDENTIAL (restored afterwards)"
fi

# The font, from the Debian package inside the ait-vc image's own base.
mkdir -p "$FONT_DIR"
docker run --rm --user root -v "$PWD/$FONT_DIR:/font" -e "OWNER=$(id -u):$(id -g)" "$IMAGE" sh -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends fonts-tlwg-loma-ttf >/dev/null &&
  cp /usr/share/fonts/truetype/tlwg/Loma.ttf /font/thai-font.ttf &&
  cp /usr/share/doc/fonts-tlwg-loma-ttf/copyright /font/thai-font.copyright &&
  chown -R "$OWNER" /font' >/dev/null \
  || { echo "FAIL setup: couldn't take the Thai font from Debian's fonts-tlwg-loma-ttf (is the network up?)" >&2; exit 1; }
echo "Thai font: $(wc -c < "$FONT_DIR/thai-font.ttf") bytes from Debian's fonts-tlwg-loma-ttf"

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
