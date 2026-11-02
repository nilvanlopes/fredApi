FROM ghcr.io/astral-sh/uv:0.12.7@sha256:95f2aa1fe59274951cfe9b0cbc7972e879ff1004bc8945d130a32eb0dbd85945 AS uv

FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

COPY --from=uv /uv /uvx /bin/

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV UV_CACHE_DIR=/tmp/uv-cache
ENV PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock ./
COPY app ./app
COPY alembic ./alembic
COPY tests ./tests
COPY alembic.ini ./
COPY docker-compose.ollama.yml ./
COPY docker/entrypoint.sh /usr/local/bin/fred-entrypoint

RUN uv sync --frozen --extra dev

RUN chmod +x /usr/local/bin/fred-entrypoint

EXPOSE 8000

CMD ["/usr/local/bin/fred-entrypoint"]
