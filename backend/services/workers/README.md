# zellovest-workers

## Seat forecasting

The PRD's deterministic/ML split is implemented under `zellovest_workers.ml`:

- `ml/sql/` defines Bronze -> Silver -> Gold BigQuery transformations. `pipeline.py` renders the documented `{{...}}` placeholders and executes them in order.
- `ml/train_vertex.py` reads Gold features through the BigQuery Storage Read API, tunes and calibrates LightGBM, rejects Brier score > 0.05 or an F1 regression, stores versioned GCS artifacts, and records Vertex AI lineage.
- `ml/optimizer.py` uses exact Poisson-binomial demand plus the penalty-aware newsvendor critical fractile. A higher true-up penalty therefore yields an equal or higher commitment.
- `tasks/seat_forecasting.py` provides `zellovest.workers.tasks.forecasting.run_seat_forecast`; it SHA-256-verifies the cached GCS model and writes immutable tenant-scoped `seat_forecasts` rows.

Set `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCS_ML_BUCKET`, `GCS_RAW_BUCKET`, `TENANT_ID`, and the Vertex image URIs in `backend/.env` (see `.env.example`). Cloud Scheduler can invoke `zellovest_workers.ml.pipeline.scheduled_training`; it refreshes features then submits an ephemeral custom-training container, with no deployed prediction endpoint.

### GitHub Actions

`.github/workflows/ci.yaml` runs the focused forecasting checks on pull requests, verifies the worker container builds, and publishes a commit-SHA image to Artifact Registry after a successful push to `main`. `.github/workflows/ml-retrain.yaml` is manual to avoid running paid training for ordinary code changes; dispatch it with a tenant ID and an image SHA published by CI. It runs BigQuery ELT and submits the Vertex job.

Configure these GitHub repository **variables** before enabling the workflows:

- Both workflows: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_ARTIFACT_REGISTRY_LOCATION`, and `GCP_ARTIFACT_REGISTRY_REPOSITORY`.
- Image publishing: `GCP_CI_SERVICE_ACCOUNT`.
- Retraining: `GCP_ML_ORCHESTRATOR_SERVICE_ACCOUNT`, `GCS_RAW_BUCKET`, `GCS_ML_BUCKET`, and `VERTEX_MODEL_SERVING_IMAGE_URI`.
- Optional retraining overrides: `BIGQUERY_BRONZE_DATASET`, `BIGQUERY_SILVER_DATASET`, `BIGQUERY_GOLD_DATASET`, `BIGQUERY_SEAT_FEATURES_TABLE`, `BIGQUERY_LOCATION`, `VERTEX_AI_REGION`, and `VERTEX_TRAINING_MACHINE_TYPE`.

Set up Google Workload Identity Federation to trust this GitHub repository/ref and grant the two service accounts the narrow Artifact Registry writer or BigQuery/GCS/Vertex permissions needed for their job. No service-account key is stored in GitHub. Vertex training runs as the Vertex service identity, which separately needs BigQuery read, GCS model artifact write, and Vertex experiment/model registry permissions.

Workers 4–7 (Celery): ingestion (Ramp/Okta), document OCR & extraction, AP audit & reconciliation (deterministic), maverick spend ML, zombie license analytics. Queues: ingestion_tasks, document_tasks, analytics_tasks.
