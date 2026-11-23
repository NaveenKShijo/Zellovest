# syntax=docker/dockerfile:1

# Shared production image for the backend API, MCP, migration, and worker
# processes. Compose selects the process command for each container.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# libgomp1 is required by LightGBM, scikit-learn, and onnxruntime.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
COPY shared/ /app/shared/
COPY services/ /app/services/
COPY alembic.ini /app/alembic.ini
COPY alembic/ /app/alembic/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --all-packages

RUN python -c "import lightgbm, fastembed, mcp"

# Default: procurement-core. Compose overrides the command per service.
EXPOSE 8001 8002 8003 8101 8102 8103
CMD ["uvicorn", "zellovest_procurement.main:app", "--host", "0.0.0.0", "--port", "8001"]
