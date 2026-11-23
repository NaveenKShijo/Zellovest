FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# libgomp1 is required by onnxruntime (FastEmbed BM42) used by MCP-2.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/
COPY shared/ /app/shared/
COPY services/ /app/services/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --package zellovest-mcp-servers

# One image serves all three logical servers; compose overrides the command.
EXPOSE 8101 8102 8103
CMD ["uvicorn", "zellovest_mcp.main_procurement:app", "--host", "0.0.0.0", "--port", "8101"]
