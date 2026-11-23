# syntax=docker/dockerfile:1

# Migration image. Application services use their package-specific Dockerfiles.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# The shared package includes FastEmbed, which may load onnxruntime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
COPY shared/ /app/shared/
COPY services/ /app/services/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package zellovest-shared

CMD ["alembic", "upgrade", "head"]
