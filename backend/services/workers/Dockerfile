FROM python:3.11-slim

WORKDIR /app
COPY shared/ /app/shared/
COPY services/workers/ /app/services/workers/
RUN pip install --no-cache-dir -e /app/shared -e /app/services/workers

# Default: ingestion queue. Override command per worker type in compose.
CMD ["celery", "-A", "zellovest_workers.celery_app.celery_app", "worker", "-Q", "ingestion_tasks", "--loglevel=info", "--concurrency=2"]
