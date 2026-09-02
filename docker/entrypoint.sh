#!/bin/sh
set -eu

max_attempts="${DB_STARTUP_MAX_ATTEMPTS:-30}"
attempt=1

while ! alembic upgrade head; do
  if [ "$attempt" -ge "$max_attempts" ]; then
    echo "ERRO: PostgreSQL não ficou disponível após ${max_attempts} tentativas." >&2
    exit 1
  fi

  echo "PostgreSQL ainda não está disponível; nova tentativa em 5s (${attempt}/${max_attempts})." >&2
  attempt=$((attempt + 1))
  sleep 5
done

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
