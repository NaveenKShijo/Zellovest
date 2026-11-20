-- BigQuery Standard SQL. Render named template placeholders before execution.
-- The deployment owns one tenant-isolated bucket; tenant_id is injected in
-- downstream transforms because native Okta logs do not carry Zellovest IDs.

CREATE SCHEMA IF NOT EXISTS `{{PROJECT_ID}}.{{BRONZE_DATASET}}`
OPTIONS(location = '{{BQ_LOCATION}}');

CREATE OR REPLACE EXTERNAL TABLE
  `{{PROJECT_ID}}.{{BRONZE_DATASET}}.okta_logs`
WITH PARTITION COLUMNS (sync STRING)
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/okta_logs/*.jsonl.gz'],
  hive_partition_uri_prefix = 'gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/okta_logs',
  ignore_unknown_values = TRUE
);

-- License assignment, HRIS, and contract feeds use the same immutable JSONL
-- landing convention. They are declared here so the Gold transformation is
-- reproducible rather than depending on manually-created BigQuery tables.
CREATE OR REPLACE EXTERNAL TABLE
  `{{PROJECT_ID}}.{{BRONZE_DATASET}}.license_assignments`
WITH PARTITION COLUMNS (sync STRING)
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/license_assignments/*.jsonl.gz'],
  hive_partition_uri_prefix = 'gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/license_assignments',
  ignore_unknown_values = TRUE
);

CREATE OR REPLACE EXTERNAL TABLE
  `{{PROJECT_ID}}.{{BRONZE_DATASET}}.hris_employees`
WITH PARTITION COLUMNS (sync STRING)
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/hris_employees/*.jsonl.gz'],
  hive_partition_uri_prefix = 'gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/hris_employees',
  ignore_unknown_values = TRUE
);

CREATE OR REPLACE EXTERNAL TABLE
  `{{PROJECT_ID}}.{{BRONZE_DATASET}}.license_contracts`
WITH PARTITION COLUMNS (sync STRING)
OPTIONS (
  format = 'NEWLINE_DELIMITED_JSON',
  uris = ['gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/license_contracts/*.jsonl.gz'],
  hive_partition_uri_prefix = 'gs://{{GCS_RAW_BUCKET}}/{{RAW_PREFIX}}/license_contracts',
  ignore_unknown_values = TRUE
);
