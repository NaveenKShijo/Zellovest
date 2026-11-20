FROM python:3.11-slim

WORKDIR /app
COPY shared/ /app/shared/
COPY services/mcp-servers/ /app/services/mcp-servers/
RUN pip install --no-cache-dir -e /app/shared \
    && pip install --no-cache-dir -e /app/services/mcp-servers

# One image serves all three logical servers; compose overrides the command.
EXPOSE 8101 8102 8103
CMD ["uvicorn", "zellovest_mcp.main_procurement:app", "--host", "0.0.0.0", "--port", "8101"]
