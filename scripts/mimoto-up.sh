#!/usr/bin/env bash
# ==============================================================================
# Start ait-mimoto, the Wallet's printer, beside the regular local stack. Local only.
# ==============================================================================
# Run from the repository root after scripts/deploy.sh has brought up the regular stack with the mock services
# (COMPOSE_FILE=compose.yaml:compose.mock.yaml). Each step converges, so a half-finished start can be run again:
#   1. refuses unless Certify trusts the local Keycloak (the code Mimoto exchanges must never reach another server);
#   2. generates Mimoto's client keystore once (deploy/<installation>/mimoto/, git-ignored);
#   3. writes Certify's live DID into .env when .env holds another one (the placeholder, or a key deploy.sh read
#      from the keystore before Certify replaced it);
#   4. builds the ait-mimoto image when it's missing, then starts compose.mimoto.yaml beside the stack: Compose
#      recreates what step 3 or .env changed (template-sync, Certify) and the VDR, which gains Mimoto's files under
#      /templates/;
#   5. sets the local Keycloak's wallet client to trust the keystore's key (the committed realm is untouched);
#   6. waits until Mimoto serves its issuers list.
# Then print with scripts/print-check.sh. Stop everything with the same COMPOSE_FILE plus compose.mimoto.yaml.
#
# Usage:
#   ./scripts/mimoto-up.sh
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

KEYCLOAK=http://auth.localhost
CERTIFY=http://issuer.localhost
MIMOTO=http://mimoto.localhost/v1/mimoto
# compose.mimoto.yaml's oidc_p12_password.
KEYSTORE_PASS=local-mimoto
TIMEOUT=${MIMOTO_TIMEOUT:-300}

die() { echo "mimoto-up: $*" >&2; exit 1; }
env_value() { grep -E "^$1=" "${2:-.env}" | tail -1 | cut -d= -f2- | tr -d '\r"'; }
set_env() {  # set_env KEY VALUE: rewrite .env in place, never sed -i (bind-mounted files keep their inode)
  local tmp; tmp=$(mktemp)
  awk -v k="$1" -v v="$2" -F= '$1==k{print k "=" v; next} {print}' .env > "$tmp" && cat "$tmp" > .env && rm -f "$tmp"
}
json() { python3 -c "import json,sys; d=json.load(open(sys.argv[1], encoding='utf-8')); print($2)" "$1"; }
wait_for() {  # wait_for URL WHAT: until the URL answers 200
  local start=$SECONDS
  until curl -sf -o /dev/null --max-time 5 "$1"; do
    (( SECONDS - start < TIMEOUT )) || return 1
    sleep 5
  done
  echo "$2 answers after $((SECONDS - start))s"
}

[ -f .env ] || die "no .env: bring the regular stack up first (scripts/deploy.sh)"
INSTALLATION=$(env_value INSTALLATION)
[[ -d deploy/$INSTALLATION/vdr/templates ]] \
  || die "the Installation $INSTALLATION has no VDR templates folder (deploy/$INSTALLATION/vdr/templates), so there's nothing for Mimoto to print"
STACK_FILES=$(env_value COMPOSE_FILE)
[[ :$STACK_FILES: == *:compose.mock.yaml:* ]] \
  || die "the local Keycloak runs from compose.mock.yaml: add it to COMPOSE_FILE in .env and run scripts/deploy.sh"
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES:compose.mimoto.yaml" docker compose "$@"; }

# 1. Certify must trust the local Keycloak, whose issuer is its public base plus the stand-in realm. The values
#    checked are the ones Compose will hand Certify, so a variable exported in the shell, which wins over .env,
#    counts too.
REALM=$(json "deploy/$INSTALLATION/mock/keycloak-realm.json" "d['realm']")
ISSUER="$KEYCLOAK/realms/$REALM"
JWKS="$ISSUER/protocol/openid-connect/certs"
CERTIFY_ENV=$(COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES" docker compose config --format json certify 2>/dev/null \
  | python3 -c "import json,sys; e=json.load(sys.stdin)['services']['certify']['environment']; print(e.get('AUTH_SERVER_ISSUER') or '', e.get('AUTH_SERVER_JWKS_URL') or '')") \
  || die "Compose can't resolve the certify service with COMPOSE_FILE=$STACK_FILES"
if [[ $CERTIFY_ENV != "$ISSUER $JWKS" ]]; then
  echo "mimoto-up: refused: Certify must trust the local Keycloak, so Mimoto never sends a login elsewhere." >&2
  echo "Certify would get: ${CERTIFY_ENV:-nothing}" >&2
  echo "Set these two lines in .env, and unset them in the shell if exported there, then run this again:" >&2
  echo "AUTH_SERVER_ISSUER=$ISSUER" >&2
  echo "AUTH_SERVER_JWKS_URL=$JWKS" >&2
  exit 1
fi
echo "Certify trusts the local Keycloak ($ISSUER)"

# 2. Mimoto's client keystore, under the alias the issuers list names. Its certificate goes to Keycloak in step 5.
ISSUERS=deploy/$INSTALLATION/vcga/issuers.json
ALIAS=$(json "$ISSUERS" "d['issuers'][0]['client_alias']")
CLIENT=$(json "$ISSUERS" "d['issuers'][0]['client_id']")
KEYS=deploy/$INSTALLATION/mimoto
if [[ ! -f $KEYS/oidckeystore.p12 || ! -f $KEYS/client.pem ]]; then
  mkdir -p "$KEYS"
  tmp=$(mktemp -d)
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=$ALIAS/OU=local test key" \
    -keyout "$tmp/client.key" -out "$tmp/client.pem" 2>/dev/null
  openssl pkcs12 -export -name "$ALIAS" -inkey "$tmp/client.key" -in "$tmp/client.pem" \
    -passout "pass:$KEYSTORE_PASS" -out "$KEYS/oidckeystore.p12"
  mv "$tmp/client.pem" "$KEYS/client.pem"
  rm -rf "$tmp"
  echo "generated Mimoto's client keystore in $KEYS (alias $ALIAS)"
else
  echo "Mimoto's client keystore is in $KEYS"
fi

# 3. The live DID replaces whatever other DID .env holds; Compose then re-syncs and recreates Certify (step 4).
#    did.json's "id" only repeats .env, so the live DID comes from the key Certify signs with.
wait_for "$CERTIFY/.well-known/did.json" "Certify" \
  || die "Certify isn't answering at $CERTIFY: bring the regular stack up first (scripts/deploy.sh)"
LIVE=$(curl -sf "$CERTIFY/.well-known/did.json" \
  | python3 -c "import json,sys; print('did:key:' + json.load(sys.stdin)['verificationMethod'][0]['publicKeyMultibase'])")
if [[ $(env_value CERTIFY_DID) != "$LIVE" ]]; then
  set_env CERTIFY_DID "$LIVE"
  echo "wrote Certify's live DID into .env (${LIVE:0:24}...)"
else
  echo ".env already holds Certify's live DID"
fi

# 4. The overlay beside the stack. Docker can't create a mount point inside the VDR's read-only templates mount, so
#    the files Mimoto's VDR mounts land on are created first (empty, git-ignored).
for f in mimoto-issuers-config.json mimoto-trusted-verifiers.json mosip-cbeff.xsd; do
  [[ -e deploy/$INSTALLATION/vdr/templates/$f ]] || : > "deploy/$INSTALLATION/vdr/templates/$f"
done
# Built from this checkout when missing, not pulled: with a build: entry, Compose would try the registry first.
# After changing src/mimoto, rebuild it with: docker compose build mimoto (with this script's COMPOSE_FILE).
MIMOTO_IMAGE=$(compose config --format json mimoto | python3 -c "import json,sys; print(json.load(sys.stdin)['services']['mimoto']['image'])")
if ! docker image inspect "$MIMOTO_IMAGE" >/dev/null 2>&1; then
  echo "building $MIMOTO_IMAGE"
  compose build mimoto
fi
compose up -d
wait_for "$CERTIFY/.well-known/openid-credential-issuer" "Certify" || die "Certify didn't come back"

# 5. The local Keycloak's wallet client trusts the keystore's certificate.
CERT=$(openssl x509 -in "$KEYS/client.pem" -outform DER | base64 | tr -d '\n')
KC=(compose exec -T keycloak /opt/keycloak/bin/kcadm.sh)
"${KC[@]}" config credentials --server http://localhost:8080 --realm master --user admin --password admin >/dev/null
CID=$("${KC[@]}" get clients -r "$REALM" -q "clientId=$CLIENT" --fields id --format csv --noquotes)
[[ -n $CID ]] || die "the local Keycloak has no client $CLIENT"
"${KC[@]}" update "clients/$CID" -r "$REALM" -s "attributes.\"jwt.credential.certificate\"=$CERT"
echo "Keycloak's $CLIENT client trusts Mimoto's key"

# 6. Mimoto is up once it serves the issuers list it reads from the VDR.
if ! wait_for "$MIMOTO/issuers" "Mimoto"; then
  compose logs --tail 30 mimoto >&2
  die "Mimoto didn't serve its issuers list within ${TIMEOUT}s"
fi
curl -sf "$MIMOTO/issuers" | python3 -c "import json,sys; print('Mimoto lists', [i['issuer_id'] for i in json.load(sys.stdin)['response']['issuers']])"
echo "Mimoto is up at $MIMOTO. Print with: ./scripts/print-check.sh"
