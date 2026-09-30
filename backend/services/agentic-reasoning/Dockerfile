FROM python:3.11-slim

WORKDIR /app
COPY shared/ /app/shared/
COPY services/agentic-reasoning/ /app/services/agentic-reasoning/
RUN pip install --no-cache-dir -e /app/shared -e /app/services/agentic-reasoning

EXPOSE 8002
CMD ["uvicorn", "zellovest_agentic.main:app", "--host", "0.0.0.0", "--port", "8002"]
