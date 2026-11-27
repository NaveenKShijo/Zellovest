-- Join logged seat-level inference predictions with delayed post-renewal outcomes.
-- Creates the prediction log table if absent and materializes matured outcomes
-- for online calibration, AUC, and financial-regret evaluation.

CREATE SCHEMA IF NOT EXISTS `{{PROJECT_ID}}.{{GOLD_DATASET}}`
OPTIONS(location = '{{BQ_LOCATION}}');

CREATE TABLE IF NOT EXISTS `{{PROJECT_ID}}.{{GOLD_DATASET}}.{{PREDICTION_LOGS_TABLE}}` (
  prediction_id STRING NOT NULL,
  tenant_id STRING NOT NULL,
  vendor_id STRING NOT NULL,
  employee_id STRING NOT NULL,
  department STRING,
  app_category STRING,
  renewal_date DATE,
  horizon_days INT64 NOT NULL,
  forecast_date DATE NOT NULL,
  model_version STRING NOT NULL,
  raw_probability FLOAT64 NOT NULL,
  calibrated_probability FLOAT64 NOT NULL,
  annual_seat_cost FLOAT64,
  trueup_penalty_rate FLOAT64,
  recommended_cohort_seats INT64,
  current_cohort_seats INT64,
  features_json STRING,
  logged_at TIMESTAMP NOT NULL
)
PARTITION BY forecast_date
CLUSTER BY tenant_id, model_version;

CREATE OR REPLACE TABLE `{{PROJECT_ID}}.{{GOLD_DATASET}}.gold_seat_prediction_outcomes`
PARTITION BY renewal_date
CLUSTER BY tenant_id, model_version AS
WITH latest_logs AS (
  SELECT
    logs.*,
    ROW_NUMBER() OVER (
      PARTITION BY
        logs.tenant_id,
        logs.vendor_id,
        logs.employee_id,
        logs.renewal_date,
        logs.horizon_days
      ORDER BY logs.forecast_date DESC, logs.logged_at DESC
    ) AS row_num
  FROM `{{PROJECT_ID}}.{{GOLD_DATASET}}.{{PREDICTION_LOGS_TABLE}}` AS logs
  WHERE logs.renewal_date IS NOT NULL
    AND logs.renewal_date <= CURRENT_DATE()
)
SELECT
  logs.prediction_id,
  logs.tenant_id,
  logs.vendor_id,
  logs.employee_id,
  COALESCE(logs.department, features.department, 'Unassigned') AS department,
  COALESCE(logs.app_category, features.app_category, 'Other') AS app_category,
  logs.renewal_date,
  logs.horizon_days,
  logs.forecast_date,
  logs.model_version,
  logs.raw_probability,
  logs.calibrated_probability,
  COALESCE(logs.annual_seat_cost, features.annual_seat_cost, 0.0) AS annual_seat_cost,
  COALESCE(logs.trueup_penalty_rate, features.trueup_penalty_rate, 0.25) AS trueup_penalty_rate,
  logs.recommended_cohort_seats,
  logs.current_cohort_seats,
  features.retained_label AS actual_retained
FROM latest_logs AS logs
JOIN `{{PROJECT_ID}}.{{GOLD_DATASET}}.{{SEAT_FEATURES_TABLE}}` AS features
  ON features.tenant_id = logs.tenant_id
 AND features.vendor_id = logs.vendor_id
 AND features.employee_id = logs.employee_id
 AND features.renewal_date = logs.renewal_date
 AND features.renewal_horizon_days = logs.horizon_days
WHERE logs.row_num = 1
  AND features.retained_label IS NOT NULL;
