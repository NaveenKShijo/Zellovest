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
