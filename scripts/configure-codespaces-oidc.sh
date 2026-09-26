#!/usr/bin/env bash
set -euo pipefail

: "${CODESPACE_NAME:?This command must run inside GitHub Codespaces}"
: "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:?Missing Codespaces forwarding domain}"

container=local-keycloak
config=/tmp/codespaces-kcadm.config
web_origin="https://${CODESPACE_NAME}-5173.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
kcadm=/opt/keycloak/bin/kcadm.sh

docker exec "$container" sh -c "$kcadm config credentials --config $config --server http://localhost:8080 --realm master --user \${KC_BOOTSTRAP_ADMIN_USERNAME:-admin} --password \$KC_BOOTSTRAP_ADMIN_PASSWORD"
client_id=$(docker exec "$container" "$kcadm" get clients -r enterprise -q clientId=enterprise-web --fields id --config "$config" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["id"])')
redirect_uris="[\"http://localhost:5173/*\",\"${web_origin}/*\"]"

docker exec "$container" "$kcadm" update "clients/${client_id}" -r enterprise --config "$config" -s "redirectUris=${redirect_uris}" -s 'webOrigins=["http://localhost:5173","+"]'
printf 'Keycloak callback configured for %s\n' "$web_origin"