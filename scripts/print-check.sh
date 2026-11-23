#!/usr/bin/env bash
# ==============================================================================
# Print a made-up credential from the Wallet through the local Mimoto, and check the PDF. Local only.
# ==============================================================================
# Run from the repository root after scripts/mimoto-up.sh. It runs src/tools/print_check.py in the ait-vc image,
# which reaches Keycloak, Certify, the VDR, the mock Adapter and Mimoto through Traefik by their *.localhost names.
# For the second print it swaps tests/fixtures/print-check-template.html onto the VDR under the credential's
# template name, and puts the original back. The PDFs are kept in a temporary folder the output names.
# First the check publishes a test copy of the credential files to the local stack only (template-sync, then Certify
# restarts), and on exit puts the committed files back (below). A credential issued in between carries the copy's
# edits; the committed files are never changed.
#
# Usage:
#   ./scripts/print-check.sh [student]     a made-up student of the stand-in realm; default: smoke.json's eligible
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

env_value() { { grep -E "^$1=" .env || true; } | tail -1 | cut -d= -f2- | tr -d '\r"'; }  # a missing key is empty, not an exit
[ -f .env ] || { echo "No .env: bring the regular stack up first (scripts/deploy.sh)." >&2; exit 1; }
for key in INSTALLATION COMPOSE_FILE; do
  [ -n "$(env_value "$key")" ] || { echo "FAIL setup: $key is not set in .env: see .env.example." >&2; exit 1; }
done
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
# A made-up Thai text for the transcript's notes claim. It goes into the published copy of the credential file only
# (below), so Certify signs it and Mimoto prints it, and no shared demo data carries Thai.
THAI_NOTE='ทดสอบภาษาไทย (made-up)'
# The made-up student's last course, which the published copy leaves without a grade, so the print check proves an
# empty grade cell doesn't shift its row. st120001's CS606 is the last course of the second term.
UNGRADED=CS606

# The stack's own Compose files, as mimoto-up.sh names them, plus the overlay so Compose knows Mimoto too.
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$(env_value COMPOSE_FILE):compose.mimoto.yaml" docker compose "$@"; }
quiet() {  # run a command, showing its output only when it fails
  local output
  output=$("$@" 2>&1) || { echo "$output" >&2; return 1; }
}
wait_certify() {
  local i
  for i in $(seq 1 60); do
    curl -sf -o /dev/null --max-time 5 "$CERTIFY/.well-known/openid-credential-issuer" && return 0
    sleep 5
  done
  echo "print-check: Certify didn't answer within 300s" >&2; return 1
}
# The command that puts the committed credential files back into Certify, as printed when restore() fails.
RESTORE_COMMAND="COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE=$(env_value COMPOSE_FILE):compose.mimoto.yaml docker compose up -d --force-recreate template-sync certify"
restore() {  # the committed credential files back into Certify; fails when it can't
  [[ $PUBLISHED == 1 ]] || return 0
  PUBLISHED=0
  if quiet compose up -d --force-recreate template-sync certify && wait_certify; then
    echo "restored the committed credential file in Certify"
  else
    echo "print-check: Certify may still hold the test copy of the credential file. From the repository root, run:" >&2
    echo "  $RESTORE_COMMAND" >&2
    return 1
  fi
}
TEST_CREDENTIALS=""
finish() {  # the exit status stays the check's own, or becomes 1 when the restore failed
  local rc=$?
  rm -rf "$FONT_DIR"
  restore || [ "$rc" -ne 0 ] || rc=1
  [[ -z $TEST_CREDENTIALS ]] || rm -rf "$TEST_CREDENTIALS"
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT TERM

# The check publishes a copy of the credential files for the run, and finish puts them back as git has them:
#  - the transcript's notes claim becomes a made-up Thai text (vc_template.credentialSubject.notes);
#  - the transcript's courses claim becomes the student's courses from the mock Adapter, with $UNGRADED's grade emptied
#    (the committed data has no ungraded course);
#  - the file git tracks may have no Background address (a deployment's VDR may hold no Background), or one that isn't
#    on the local VDR (null, empty, another host), so unless it has an address on the local VDR,
#    display[0].background_image points at the VDR's templates folder, where the print check places its
#    made-up Background: <VDR>/templates/<credential configuration id>/background.png.
# The copy is made once (test_credentials) and every edit changes it in place; publish_test_credentials then syncs it
# and restarts Certify.
CREDENTIAL=$(python3 -c "import json,sys; print(next(e['credentialConfig'] for e in json.load(open(sys.argv[1])) if e.get('mimotoTemplate')))" "$INST/smoke.json")   || { echo "FAIL setup: $INST/smoke.json names no mimotoTemplate" >&2; exit 1; }
certify_reports_display() {  # succeeds when Certify's metadata gives the credential's display (it is up and knows the id)
  curl -sf "$CERTIFY/.well-known/openid-credential-issuer" | python3 -c "
import json,sys
json.load(sys.stdin)['credential_configurations_supported'][sys.argv[1]]['display'][0]" "$CREDENTIAL"
}
test_credentials() {
  [[ -z $TEST_CREDENTIALS ]] || return 0
  TEST_CREDENTIALS=$(mktemp -d)
  cp "$INST"/certify/credentials/*.json "$TEST_CREDENTIALS"/
  chmod -R a+rX "$TEST_CREDENTIALS"
}
add_background_address() {  # the copy's display[0].background_image, unless the file git holds has an address on the local VDR
  python3 -c "
import json,sys
p=sys.argv[1]+'/'+sys.argv[2]+'.json'
c=json.load(open(p,encoding='utf-8'))
vdr='http://vdr.localhost/templates/'
uri=(c['display'][0].get('background_image') or {}).get('uri')
if not (isinstance(uri,str) and uri.startswith(vdr)):
    c['display'][0]['background_image']={'uri':vdr+sys.argv[2]+'/background.png'}
json.dump(c,open(p,'w',encoding='utf-8'),indent=2)" "$TEST_CREDENTIALS" "$CREDENTIAL"
}
set_thai_note() {  # the copy's notes claim: a literal in place of ${notes}, so the Adapter's data is untouched
  python3 -c "
import json,sys
p=sys.argv[1]+'/'+sys.argv[2]+'.json'
c=json.load(open(p,encoding='utf-8'))
c['vc_template']['credentialSubject']['notes']=sys.argv[3]
json.dump(c,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)" "$TEST_CREDENTIALS" "$CREDENTIAL" "$THAI_NOTE"
}
set_ungraded_course() {  # the copy's courses claim: the student's courses from the Adapter as a literal, UNGRADED with no grade
  curl -sf "http://adapter.localhost/student/$STUDENT/transcript" | python3 -c "
import json,sys
p=sys.argv[1]+'/'+sys.argv[2]+'.json'
c=json.load(open(p,encoding='utf-8'))
courses=json.load(sys.stdin)['courses']
for term in courses:
    for course in term['courses']:
        if course['no']==sys.argv[3]: course['grade']=''
c['vc_template']['credentialSubject']['courses']=courses
json.dump(c,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)" "$TEST_CREDENTIALS" "$CREDENTIAL" "$UNGRADED"
}
publish_test_credentials() {
  PUBLISHED=1
  quiet compose run --rm -T -e CREDENTIALS_DIR=/test-credentials -v "$TEST_CREDENTIALS:/test-credentials:ro" template-sync
  quiet compose restart certify
  wait_certify
}
# Stop before anything is published when Certify is down or doesn't know the credential id.
STUDENT=${1:-$(python3 -c "import json,sys; e=next(e for e in json.load(open(sys.argv[1])) if e.get('mimotoTemplate'))['eligible']; print(e if isinstance(e,str) else e[0])" "$INST/smoke.json")}
certify_reports_display   || { echo "FAIL setup: couldn't read $CREDENTIAL's display from Certify's metadata at $CERTIFY: is the stack up?" >&2; exit 1; }
test_credentials
add_background_address
set_thai_note
set_ungraded_course
publish_test_credentials
echo "published a test copy of $CREDENTIAL with a Background address, a Thai notes claim and a course without a grade (restored afterwards)"

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
    --test-template /check/template.html --out /out --templates-shown "$INST/vdr/templates" --thai-note "$THAI_NOTE" --ungraded "$UNGRADED" ${1:+--student "$1"} \
  && status=0 || status=$?
echo "PDFs: $OUT"
exit "$status"
