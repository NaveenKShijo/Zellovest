# Synthetic seat model training

This manual workflow is for development using the checked-in telemetry. It creates
synthetic data and a model in separate locations from the real data and model.

1. Configure repository variables `SYNTHETIC_GCS_RAW_BUCKET` and
   `SYNTHETIC_GCS_ML_BUCKET`. The latter must differ from `GCS_ML_BUCKET`.
   The service account needs access to these buckets and the BigQuery and Vertex
   resources. The raw bucket must be compatible with `BIGQUERY_LOCATION`.
2. Push the code to main and wait for the worker image CI job to publish the image.
3. In Actions, select **Train seat model with synthetic telemetry**, choose the
   same commit, and supply its full SHA as `training_image_tag`. Use a telemetry
   tenant such as `tenant_001`.

The workflow converts the selected tenant's Parquet records to four compressed
JSONL feeds under `synthetic/<run-id>-<attempt>/raw/` in the synthetic raw bucket.
It writes a manifest containing the source commit, checksums and row counts there.
The ELT uses `zellovest_synthetic_bronze`, `zellovest_synthetic_silver` and
`zellovest_synthetic_gold` datasets. It copies that tenant's Gold rows to a
run-specific snapshot table and submits a Vertex custom training job. Experiment
parameters include the snapshot table, tenant and artifact URI.

The GitHub job finishes after submission; check the Vertex custom job for the
training outcome. Model evaluation can reject a run, and synthetic results must
not be used to make real purchasing decisions. To inspect features, query the
Gold dataset in BigQuery and select the run's `snapshot_<run-id>_<attempt>` table.
Snapshots and GCS objects persist and may incur storage costs.

## Run a synthetic forecast without retraining

Use a disposable development PostgreSQL database with the project migrations
applied and a running Redis instance. Configure the following environment for
both the analytics worker and the setup command (use actual bucket names):

```text
GOOGLE_CLOUD_PROJECT=your-project
GCS_RAW_BUCKET=your-synthetic-raw-bucket
GCS_ML_BUCKET=your-synthetic-model-bucket
BIGQUERY_BRONZE_DATASET=zellovest_synthetic_bronze
BIGQUERY_SILVER_DATASET=zellovest_synthetic_silver
BIGQUERY_GOLD_DATASET=zellovest_synthetic_gold
BIGQUERY_SEAT_FEATURES_TABLE=gold_seat_features
BIGQUERY_LOCATION=asia-south1
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/development_db
REDIS_URL=redis://localhost:6379/0
```

Provide Google Application Default Credentials with access to the buckets and
BigQuery. Run these commands from `backend/services/workers` on a host with
access to the development database and Redis:

```powershell
uv run celery -A zellovest_workers.celery_app.celery_app worker -Q analytics_tasks --pool=solo --loglevel=info
```

In a second terminal with the same environment, choose a unique raw prefix and run:

```powershell
$env:SEAT_RAW_PREFIX = "synthetic/local-20261121/raw"
uv run python -m zellovest_workers.ml.synthetic_forecast_setup --directory ../../../data/telemetry --tenant-id tenant_002 --horizon 120 --development-database
```

This creates matching synthetic vendors, employees, and assignments in the
development database, uploads the synthetic feeds, refreshes the synthetic
BigQuery datasets, and enqueues one inference task. It does not train a model.
Use the model bucket from synthetic training; the worker reads `models/latest`.
Check the worker logs and query `seat_forecasts` for `tenant_002`.

The preparation uses a synthetic renewal date equal to today plus the chosen
horizon, so the corresponding features are as of today. Do not run all four
horizons on the same day: the current PostgreSQL uniqueness key cannot store
multiple horizons for the same vendor and department on a forecast date.
This synthetic data and its predictions are for development only. The current
frontend may still use mock forecasts until its database integration is complete.
