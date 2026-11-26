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

`.github/workflows/ci.yaml` runs forecasting and frontend checks, builds all runtime images on pull requests, and publishes commit-SHA images to Artifact Registry after a successful push to `main`. The deployment job waits for approval in the GitHub `production` environment, then updates the configured Compose VM over IAP/OS Login. Run the workflow manually with an existing 40-character commit SHA to redeploy or roll back to that image set. `.github/workflows/ml-train.yaml` remains manually dispatched when training data is ready; it refreshes BigQuery features and submits training to Vertex AI. No performance-triggered retraining is configured.

Configure these GitHub repository **variables** (or secrets) before enabling the workflows. `GCP_WIF_PROVIDER` is an identifier, so a repository variable is the usual choice.

- Both workflows: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_ARTIFACT_REGISTRY_LOCATION`, `GCP_ARTIFACT_REGISTRY_REPOSITORY`, and `GCP_SERVICE_ACCOUNT`.
- Deployment workflow: repository variables `GCP_VM_NAME`, `GCP_VM_ZONE`, and `GCP_DEPLOY_DIR`; configure a required reviewer on the `production` environment. The VM needs IAP/OS Login access, Docker Compose and `gcloud`, its app `.env`, a host credential file for GCP integrations, and an attached service account with Artifact Registry Reader access.
- Training workflow: `GCS_RAW_BUCKET`, `GCS_ML_BUCKET`; optional `BIGQUERY_BRONZE_DATASET`, `BIGQUERY_SILVER_DATASET`, `BIGQUERY_GOLD_DATASET`, `BIGQUERY_LOCATION`, `VERTEX_AI_REGION`, and `VERTEX_TRAINING_MACHINE_TYPE`.

Set up Google Workload Identity Federation to trust this GitHub repository/ref. The shared GitHub service account needs Artifact Registry write access and IAP/OS Login permissions for deployment, plus BigQuery/Vertex permissions for manually submitted training jobs. The Vertex training runtime identity needs BigQuery feature read and GCS model artifact write access. No service-account key is stored in GitHub. Celery workers only read the approved model from GCS for batch inference.

Workers 4–7 (Celery): ingestion (Ramp/Okta), document OCR & extraction, AP audit & reconciliation (deterministic), maverick spend ML, zombie license analytics. Queues: ingestion_tasks, document_tasks, analytics_tasks.
