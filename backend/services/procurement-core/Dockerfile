FROM python:3.11-slim

WORKDIR /app
COPY shared/ /app/shared/
COPY services/procurement-core/ /app/services/procurement-core/
RUN pip install --no-cache-dir -e /app/shared -e /app/services/procurement-core

EXPOSE 8001
CMD ["uvicorn", "zellovest_procurement.main:app", "--host", "0.0.0.0", "--port", "8001"]
