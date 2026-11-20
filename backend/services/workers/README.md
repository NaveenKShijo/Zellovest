# zellovest-workers

## Seat forecasting

The PRD's deterministic/ML split is implemented under `zellovest_workers.ml`:

- `ml/sql/` defines Bronze -> Silver -> Gold BigQuery transformations. `pipeline.py` renders the documented `{{...}}` placeholders and executes them in order.
- `ml/train_vertex.py` trains and promotes approved model artifacts from a Vertex AI custom training container; Celery imports its probability-calibration helpers for batch inference.
- `ml/vertex_training.py` refreshes features and submits an explicitly requested Vertex AI training job. It is not triggered by model performance monitoring.
- `ml/feature_pipeline.py` refreshes BigQuery Bronze -> Silver -> Gold features independently of model training.
- `ml/optimizer.py` uses exact Poisson-binomial demand plus the penalty-aware newsvendor critical fractile. A higher true-up penalty therefore yields an equal or higher commitment.
- `tasks/seat_forecasting.py` provides `zellovest.workers.tasks.forecasting.run_seat_forecast`; it SHA-256-verifies the cached GCS model and writes immutable tenant-scoped `seat_forecasts` rows.

Set `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCS_ML_BUCKET`, `GCS_RAW_BUCKET`, and `TENANT_ID` in `backend/.env` (see `.env.example`). Cloud Scheduler can invoke `zellovest_workers.ml.feature_pipeline.scheduled_feature_refresh` to refresh features. Forecasting uses the latest approved model already stored in GCS and writes batch results to PostgreSQL.

### GitHub Actions

`.github/workflows/ci.yaml` runs the focused forecasting checks on pull requests, verifies the worker container builds, and publishes a commit-SHA image to Artifact Registry after a successful push to `main`. `.github/workflows/ml-train.yaml` is manually dispatched when training data is ready; it refreshes BigQuery features and submits training to Vertex AI. No performance-triggered retraining is configured.

Configure these GitHub repository **variables** before enabling the workflows:

- Both workflows: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_ARTIFACT_REGISTRY_LOCATION`, `GCP_ARTIFACT_REGISTRY_REPOSITORY`, and `GCP_SERVICE_ACCOUNT`.
- Training workflow: `GCS_RAW_BUCKET`, `GCS_ML_BUCKET`; optional `BIGQUERY_BRONZE_DATASET`, `BIGQUERY_SILVER_DATASET`, `BIGQUERY_GOLD_DATASET`, `BIGQUERY_LOCATION`, `VERTEX_AI_REGION`, and `VERTEX_TRAINING_MACHINE_TYPE`.

Set up Google Workload Identity Federation to trust this GitHub repository/ref. The shared service account needs Artifact Registry write access for CI and BigQuery/Vertex permissions for manually submitted training jobs. The Vertex training runtime identity needs BigQuery feature read and GCS model artifact write access. No service-account key is stored in GitHub. Celery workers only read the approved model from GCS for batch inference.

Workers 4–7 (Celery): ingestion (Ramp/Okta), document OCR & extraction, AP audit & reconciliation (deterministic), maverick spend ML, zombie license analytics. Queues: ingestion_tasks, document_tasks, analytics_tasks.
