#!/usr/bin/env bash
# ==============================================================================
# What the local-only scripts (mimoto-up.sh, publish-set.sh) share. Source it; it runs nothing.
# ==============================================================================
# The caller sets PROG (its name, for messages) and has changed to the repository root. The functions:
#   load_stack_env          reads .env: INSTALLATION, STACK_FILES; refuses a stack without compose.mock.yaml; defines compose()
#   require_local_certify   refuses unless Certify trusts the local Keycloak; sets REALM, ISSUER, JWKS
#   write_live_did          writes Certify's live DID into .env when .env holds another one
# plus die, env_value, set_env, json and wait_for. A deployment's .env fails the first refusal or the second, so these
# scripts never act on a deployment.

KEYCLOAK=http://auth.localhost
CERTIFY=http://issuer.localhost
TIMEOUT=${MIMOTO_TIMEOUT:-300}

die() { echo "$PROG: $*" >&2; exit 1; }
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

load_stack_env() {
  [ -f .env ] || die "no .env: bring the regular stack up first (scripts/deploy.sh)"
  INSTALLATION=$(env_value INSTALLATION)
  STACK_FILES=$(env_value COMPOSE_FILE)
  [[ :$STACK_FILES: == *:compose.mock.yaml:* ]] \
    || die "the local Keycloak runs from compose.mock.yaml: add it to COMPOSE_FILE in .env and run scripts/deploy.sh"
  compose() { COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES" docker compose "$@"; }
}

# Certify must trust the local Keycloak, whose issuer is its public base plus the stand-in realm. The values checked
# are the ones Compose will hand Certify, so a variable exported in the shell, which wins over .env, counts too.
require_local_certify() {
  REALM=$(json "deploy/$INSTALLATION/mock/keycloak-realm.json" "d['realm']")
  ISSUER="$KEYCLOAK/realms/$REALM"
  JWKS="$ISSUER/protocol/openid-connect/certs"
  local certify_env
  certify_env=$(COMPOSE_PATH_SEPARATOR=: COMPOSE_FILE="$STACK_FILES" docker compose config --format json certify 2>/dev/null \
    | python3 -c "import json,sys; e=json.load(sys.stdin)['services']['certify']['environment']; print(e.get('AUTH_SERVER_ISSUER') or '', e.get('AUTH_SERVER_JWKS_URL') or '')") \
    || die "Compose can't resolve the certify service with COMPOSE_FILE=$STACK_FILES"
  if [[ $certify_env != "$ISSUER $JWKS" ]]; then
    echo "$PROG: refused: Certify must trust the local Keycloak, so a login code is never sent elsewhere." >&2
    echo "Certify would get: ${certify_env:-nothing}" >&2
    echo "Set these two lines in .env, and unset them in the shell if exported there, then run this again:" >&2
    echo "AUTH_SERVER_ISSUER=$ISSUER" >&2
    echo "AUTH_SERVER_JWKS_URL=$JWKS" >&2
    exit 1
  fi
  echo "Certify trusts the local Keycloak ($ISSUER)"
}

# The live DID replaces whatever other DID .env holds; the next template-sync then writes it into every credential
# configuration. did.json's "id" only repeats .env, so the live DID comes from the key Certify signs with.
write_live_did() {
  local live
  wait_for "$CERTIFY/.well-known/did.json" "Certify" \
    || die "Certify isn't answering at $CERTIFY: bring the regular stack up first (scripts/deploy.sh)"
  live=$(curl -sf "$CERTIFY/.well-known/did.json" \
    | python3 -c "import json,sys; print('did:key:' + json.load(sys.stdin)['verificationMethod'][0]['publicKeyMultibase'])")
  if [[ $(env_value CERTIFY_DID) != "$live" ]]; then
    set_env CERTIFY_DID "$live"
    echo "wrote Certify's live DID into .env (${live:0:24}...)"
  else
    echo ".env already holds Certify's live DID"
  fi
}
