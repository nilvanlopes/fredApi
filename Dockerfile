FROM ghcr.io/astral-sh/uv:0.10.12 AS uv

FROM python:3.12-slim

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

RUN uv sync --frozen --extra dev

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
