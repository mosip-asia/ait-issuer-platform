#!/usr/bin/env bash
# ==============================================================================
# Start the real Mimoto 0.21, the Wallet's printer, beside the regular local stack. Local only.
# ==============================================================================
# Run from the repository root after scripts/deploy.sh has brought up the regular stack with the mock services
# (COMPOSE_FILE=compose.yaml:compose.mock.yaml). Each step converges, so a half-finished start can be run again:
#   1. refuses unless Certify trusts the local Keycloak (the code Mimoto exchanges must never reach another server);
#   2. generates Mimoto's client keystore once (deploy/<installation>/mimoto/, git-ignored);
#   3. writes Certify's live DID into .env when .env holds another one (the placeholder, or a key deploy.sh read
#      from the keystore before Certify replaced it);
#   4. starts compose.mimoto.yaml beside the stack: Compose recreates what step 3 or .env changed (template-sync,
#      Certify) and the VDR, which gains Mimoto's files under /templates/;
#   5. sets the local Keycloak's wallet client to trust the keystore's key (the committed realm is untouched);
#   6. waits until Mimoto serves its issuers list.
# Then print with scripts/print-check.sh. Stop everything with the same COMPOSE_FILE plus compose.mimoto.yaml.
#
# Usage:
#   ./scripts/mimoto-up.sh
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROG=mimoto-up
source scripts/local-stack.sh
MIMOTO=http://mimoto.localhost/v1/mimoto
# compose.mimoto.yaml's oidc_p12_password.
KEYSTORE_PASS=local-mimoto

load_stack_env
[[ -d deploy/$INSTALLATION/vdr/templates ]] \
  || die "the Installation $INSTALLATION has no VDR templates folder (deploy/$INSTALLATION/vdr/templates), so there's nothing for Mimoto to print"
compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES:compose.mimoto.yaml" docker compose "$@"; }

# 1. Certify must trust the local Keycloak (scripts/local-stack.sh).
require_local_certify

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
write_live_did

# 4. The overlay beside the stack. Docker can't create a mount point inside the VDR's read-only templates mount, so
#    the files Mimoto's VDR mounts land on are created first (empty, git-ignored).
for f in mimoto-issuers-config.json mimoto-trusted-verifiers.json mosip-cbeff.xsd; do
  [[ -e deploy/$INSTALLATION/vdr/templates/$f ]] || : > "deploy/$INSTALLATION/vdr/templates/$f"
done
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
