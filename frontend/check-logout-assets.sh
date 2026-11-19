#!/usr/bin/env bash
set -euo pipefail

# Run from any directory with the local Fred web image available.
NGINX_IMAGE="${NGINX_IMAGE:-fred-web:latest}"
CONTAINER_NAME="fred-logout-assets-check-$$"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
TEMP_DIR="$(mktemp -d)"

cleanup() {
  docker rm --force "$CONTAINER_NAME" >/dev/null 2>&1 || true
  rm -rf -- "$TEMP_DIR"
}
trap cleanup EXIT

docker run --detach --rm --pull=never \
  --name "$CONTAINER_NAME" \
  --network none \
  --add-host api:127.0.0.1 \
  --add-host login-fred.nilvanlopes.com:127.0.0.1 \
  --volume "$SCRIPT_DIR/nginx.conf:/etc/nginx/nginx.conf:ro" \
  --volume "$SCRIPT_DIR/public:/usr/share/nginx/html:ro" \
  --entrypoint nginx "$NGINX_IMAGE" -g 'daemon off;' >/dev/null

for attempt in {1..30}; do
  if docker exec "$CONTAINER_NAME" wget -T 2 -q -O /dev/null http://127.0.0.1:8080/healthz; then
    break
  fi
  if [[ "$attempt" == 30 ]]; then
    echo "O nginx temporário não iniciou." >&2
    exit 1
  fi
  sleep 1
done

check_asset() {
  local route="$1" asset="$2" content_type="$3"
  if ! docker exec "$CONTAINER_NAME" wget -Y off -T 2 -S -O - \
    "http://login-fred.nilvanlopes.com:8080$route" \
    >"$TEMP_DIR/body" 2>"$TEMP_DIR/headers"; then
    cat "$TEMP_DIR/headers" >&2
    return 1
  fi
  grep -i "^[[:blank:]]*Content-Type: $content_type" "$TEMP_DIR/headers"
  cmp "$SCRIPT_DIR/public/$asset" "$TEMP_DIR/body"
}

check_asset '/if/flow/fred-invalidation-flow/?fixture=1' authentik-invalidation.html text/html
check_asset '/authentik-invalidation.js' authentik-invalidation.js application/javascript

echo "Logout HTML e JavaScript servidos com sucesso pelo nginx temporário."
