# zellovest-workers

## Seat forecasting

The PRD's deterministic/ML split is implemented under `zellovest_workers.ml`:

- `ml/sql/` defines Bronze -> Silver -> Gold BigQuery transformations (`01_bronze_okta_logs.sql` -> `03_gold_seat_features.sql`) and delayed outcome evaluation (`04_gold_prediction_evaluation.sql`). `feature_pipeline.py` renders the documented `{{...}}` placeholders and executes them in order.
- `ml/train_vertex.py` performs leakage-free renewal-cohort splitting, trains and calibrates a LightGBM challenger, checks slice/calibration/financial backtest gates, emits `baseline_stats.json` and `feature_schema.json`, and promotes approved artifacts to versioned + `latest` GCS prefixes (with `--shadow-only` and `promote_model_version` rollback support).
- `ml/benchmark_generator.py` generates multi-renewal-cohort training benchmarks and independent unseen-vendor inference datasets.
- `ml/evaluation.py` logs seat-level predictions to BigQuery (`gold_seat_prediction_logs`) and joins matured renewals to compute online AUC, Brier, ECE, and realized financial regret in `ml_model_metrics`.
- `ml/monitoring.py` + `tasks/ml_ops.py` run scheduled PSI/sentinel drift checks against `baseline_stats.json`, persist `ml_drift_reports`, and trigger continuous retraining on Vertex AI when `ML_AUTO_RETRAIN_ENABLED=true`.
- `ml/vertex_training.py` refreshes features and submits an explicitly requested Vertex AI training job.
- `ml/feature_pipeline.py` refreshes BigQuery Bronze -> Silver -> Gold features independently of model training.
- `ml/optimizer.py` uses exact Poisson-binomial demand convolved with Poisson headcount growth plus the penalty-aware newsvendor critical fractile. A higher true-up penalty therefore yields an equal or higher commitment.
- `tasks/seat_forecasting.py` provides `zellovest.workers.tasks.forecasting.run_seat_forecast`; it SHA-256-verifies the cached GCS model, writes immutable tenant-scoped `seat_forecasts` rows keyed per horizon, and logs seat-level predictions.

Set `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCS_ML_BUCKET`, `GCS_RAW_BUCKET`, and `TENANT_ID` in `backend/.env` (see `.env.example`). Cloud Scheduler can invoke `zellovest_workers.ml.feature_pipeline.scheduled_feature_refresh` to refresh features. Forecasting uses the latest approved model already stored in GCS and writes batch results to PostgreSQL.

### GitHub Actions

`.github/workflows/ci.yaml` runs forecasting and frontend checks, builds all runtime images on pull requests, and publishes commit-SHA images to Artifact Registry after a successful push to `main`. `.github/workflows/cd-deploy.yaml` waits for approval in the GitHub `production` environment, then updates the configured Compose VM over IAP/OS Login. Run `CD production` manually with an existing 40-character commit SHA to redeploy or roll back to that image set. `.github/workflows/ml-train.yaml` remains manually dispatched when training data is ready; it refreshes BigQuery features and submits training to Vertex AI. No performance-triggered retraining is configured.

Configure these GitHub repository **variables** (or secrets) before enabling the workflows. WIF provider names are identifiers, so repository variables are usually easiest to manage.

- Image publishing and training workflows: `GCP_PROJECT_ID`, `GCP_WIF_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `GCP_ARTIFACT_REGISTRY_LOCATION`, and `GCP_ARTIFACT_REGISTRY_REPOSITORY`.
- Deployment workflow: `GCP_VM_WIF_PROVIDER` and `GCP_VM_SERVICE_ACCOUNT` identify the GitHub deployer, plus `GCP_VM_NAME`, `GCP_VM_ZONE`, and `GCP_DEPLOY_DIR`. Configure a required reviewer on the `production` environment. The VM needs Docker Compose and `gcloud`, its app `.env`, a host credential file for GCP integrations, and an attached runtime service account with Artifact Registry Reader access.
- Training workflow: `GCS_RAW_BUCKET`, `GCS_ML_BUCKET`; optional `BIGQUERY_BRONZE_DATASET`, `BIGQUERY_SILVER_DATASET`, `BIGQUERY_GOLD_DATASET`, `BIGQUERY_LOCATION`, `VERTEX_AI_REGION`, and `VERTEX_TRAINING_MACHINE_TYPE`.

Set up Google Workload Identity Federation to trust this GitHub repository/ref. `GCP_SERVICE_ACCOUNT` is used by GitHub to publish images and run the training workflow. `GCP_VM_SERVICE_ACCOUNT` is a separate GitHub deployer identity: grant it Compute OS Admin Login at project scope, IAP-secured Tunnel User on the VM or project, and Service Account User on the VM's attached runtime service account. The VM-attached identity supplies credentials to Docker image pulls and application code. If reusing `GCP_SERVICE_ACCOUNT` as that runtime identity, it also needs the runtime roles and will retain its image-publishing permissions; a dedicated runtime identity is narrower. The Vertex training runtime identity needs BigQuery feature read and GCS model artifact write access. No service-account key is stored in GitHub. Celery workers only read the approved model from GCS for batch inference.

Workers 4–7 (Celery): ingestion (Ramp/Okta), document OCR & extraction, AP audit & reconciliation (deterministic), maverick spend ML, zombie license analytics. Queues: ingestion_tasks, document_tasks, analytics_tasks.
