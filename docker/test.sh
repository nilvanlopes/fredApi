#!/usr/bin/env bash
# Isolated backend suite: no production services, networks, ports or volumes.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
test_token="$(id -u)-$$-$(date +%s)"
test_image="fred-tests:${test_token}"
test_network="fred-test-network-${test_token}"
test_database="fred-test-postgres-${test_token}"
test_migration="fred-test-migration-${test_token}"
test_runner="fred-test-runner-${test_token}"
test_url="postgresql+asyncpg://fred:test-only@${test_database}:5432/fred_test"

cleanup() {
  local result=$?
  trap - EXIT INT TERM
  docker rm -fv "$test_runner" "$test_migration" "$test_database" >/dev/null 2>&1 || true
  docker network rm "$test_network" >/dev/null 2>&1 || true
  docker image rm "$test_image" >/dev/null 2>&1 || true
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker build -t "$test_image" "$project_dir"
docker network create "$test_network" >/dev/null
docker run -d --name "$test_database" --network "$test_network" \
  --tmpfs /var/lib/postgresql/data:rw,size=512m \
  -e POSTGRES_DB=fred_test -e POSTGRES_USER=fred -e POSTGRES_PASSWORD=test-only \
  postgres:16-alpine@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685 >/dev/null

ready=0
for attempt in {1..40}; do
  if docker exec "$test_database" pg_isready -h 127.0.0.1 -U fred -d fred_test >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  docker logs "$test_database" >&2
  echo "PostgreSQL de testes não iniciou a tempo." >&2
  exit 1
fi

docker run --rm --name "$test_migration" --network "$test_network" -e "DATABASE_URL=$test_url" \
  --entrypoint /app/.venv/bin/alembic "$test_image" upgrade head
if [[ $# == 0 ]]; then
  set -- -q
fi
docker run --rm --name "$test_runner" --network "$test_network" \
  -e "DATABASE_URL=$test_url" -e "FRED_TEST_DATABASE_URL=$test_url" \
  --mount "type=bind,source=$project_dir/docs/n8n,target=/app/docs/n8n,readonly" \
  --entrypoint /app/.venv/bin/pytest "$test_image" "$@"
