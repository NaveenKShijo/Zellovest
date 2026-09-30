FROM python:3.11-slim

WORKDIR /app
COPY shared/ /app/shared/
COPY services/ingestion-api/ /app/services/ingestion-api/
RUN pip install --no-cache-dir -e /app/shared -e /app/services/ingestion-api

EXPOSE 8003
CMD ["uvicorn", "zellovest_ingestion.main:app", "--host", "0.0.0.0", "--port", "8003"]
