# Synthetic seat model training

This manual workflow is for development using the checked-in telemetry. It creates
synthetic data and a model in separate locations from the real data and model.

1. Configure repository variables `GCS_RAW_SYNTH` and `GCS_ML_SYNTH`. The latter
   must differ from production `GCS_ML_BUCKET`.
   The service account needs access to these buckets and the BigQuery and Vertex
   resources. The raw bucket must be compatible with `BIGQUERY_LOCATION`.
2. Push the code to main and wait for the worker image CI job to publish the image.
3. In Actions, select **Train seat model with synthetic telemetry**, choose the
   same commit, and supply its full SHA as `training_image_tag`. Keep
   `source_tenant_id` as `tenant_002` and set `tenant_id` to `default_org` to
   train using those checked-in rows while tagging the generated features for
   the application tenant.

The workflow converts the selected source tenant's Parquet records to four compressed
JSONL feeds under `synthetic/<run-id>-<attempt>/raw/` in the synthetic raw bucket.
It remaps tenant-scoped employee, assignment and vendor IDs and writes the feeds
under the target tenant. The manifest records both source and target tenant IDs,
source commit, checksums and row counts.
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
GCS_RAW_SYNTH=your-synthetic-raw-bucket
GCS_ML_SYNTH=your-synthetic-model-bucket
SEAT_SYNTHETIC_MODE=true
BIGQUERY_BRONZE_DATASET=zellovest_synthetic_bronze
BIGQUERY_SILVER_DATASET=zellovest_synthetic_silver
BIGQUERY_GOLD_DATASET=zellovest_synthetic_gold
BIGQUERY_SEAT_FEATURES_TABLE=gold_seat_features
BIGQUERY_LOCATION=asia-south1
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/development_db
REDIS_URL=redis://localhost:6379/0
```

Provide Google Application Default Credentials with access to the buckets and
BigQuery. For local development, either set `GOOGLE_APPLICATION_CREDENTIALS` in
`backend/.env` to your service account JSON file, or authenticate with
`gcloud auth application-default login`. Do not commit credentials or the `.env`
file. On Windows, quote a JSON key path and use forward slashes, for example
`GOOGLE_APPLICATION_CREDENTIALS="C:/Users/you/Downloads/service-account.json"`.
Set `BIGQUERY_LOCATION` to the exact location of your synthetic datasets; the
example project uses `asia-south1`. Replace every example value above with your actual project, buckets,
database, and BigQuery location. Run these commands from
`backend/services/workers` on a host with access to the development database
and Redis. `../../.env` resolves to `backend/.env` from this directory:

```powershell
uv run --env-file ../../.env celery -A zellovest_workers.celery_app.celery_app worker -Q analytics_tasks --pool=solo --loglevel=info
```

In a second terminal with the same environment, choose a unique raw prefix and run:

```powershell
$env:SEAT_RAW_PREFIX = "synthetic/local-default-org/raw"
uv run --env-file ../../.env python -m zellovest_workers.ml.synthetic_forecast_setup --directory ../../../data/telemetry --source-tenant-id tenant_002 --tenant-id default_org --horizon 120 --development-database
```

This creates matching synthetic vendors, employees, and assignments in the
development database under `default_org`, uploads the mapped feeds, refreshes
the synthetic BigQuery datasets for `default_org`, and enqueues one inference
task for `default_org`. It does not train a model.
Use the model bucket from synthetic training; the worker reads `models/latest`.
Check the worker logs and query `seat_forecasts` for `default_org`.
Open **License forecasting** and select **Refresh forecasts** to load the saved
results. The forecast API recognizes `default_org` and the application's
`default-org` as the same default organization. Other tenant IDs are matched
exactly; the browser cannot choose a different organization.

The preparation uses a synthetic renewal date equal to today plus the chosen
horizon, so the corresponding features are as of today. Multi-horizon forecasts
for the same vendor, department, and forecast date are keyed by ``horizon_days``.
This synthetic data and its predictions are for development only.
