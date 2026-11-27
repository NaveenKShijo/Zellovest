-- Point-in-time seat-retention features at the four renewal horizons.
-- Future renewals retain a NULL target for inference; completed renewals have
-- leakage-safe labels based only on activity in the final pre-renewal month.

CREATE SCHEMA IF NOT EXISTS `{{PROJECT_ID}}.{{GOLD_DATASET}}`
OPTIONS(location = '{{BQ_LOCATION}}');

CREATE OR REPLACE TABLE `{{PROJECT_ID}}.{{GOLD_DATASET}}.gold_seat_features`
PARTITION BY feature_as_of_date
CLUSTER BY tenant_id, app_id, department AS
WITH assignments AS (
  SELECT
    COALESCE(JSON_VALUE(raw_json, '$.tenant_id'), '{{TENANT_ID}}') AS tenant_id,
    COALESCE(JSON_VALUE(raw_json, '$.employee_id'), JSON_VALUE(raw_json, '$.user_id'))
      AS employee_id,
    COALESCE(JSON_VALUE(raw_json, '$.vendor_id'), JSON_VALUE(raw_json, '$.app_name'))
      AS vendor_id,
    COALESCE(JSON_VALUE(raw_json, '$.app_id'), JSON_VALUE(raw_json, '$.okta_app_id'))
      AS app_id,
    LOWER(JSON_VALUE(raw_json, '$.app_name')) AS app_name,
    COALESCE(JSON_VALUE(raw_json, '$.department'), 'Unassigned') AS assignment_department,
    SAFE_CAST(JSON_VALUE(raw_json, '$.assigned_at') AS DATE) AS assigned_at,
    SAFE_CAST(JSON_VALUE(raw_json, '$.unassigned_at') AS DATE) AS unassigned_at
  FROM (
    SELECT TO_JSON_STRING(assignment_row) AS raw_json
    FROM `{{PROJECT_ID}}.{{BRONZE_DATASET}}.license_assignments` AS assignment_row
  )
),
employees AS (
  SELECT * EXCEPT(row_number)
  FROM (
    SELECT
      COALESCE(JSON_VALUE(raw_json, '$.tenant_id'), '{{TENANT_ID}}') AS tenant_id,
      COALESCE(
        JSON_VALUE(raw_json, '$.employee_id'),
        JSON_VALUE(raw_json, '$.user_id'),
        JSON_VALUE(raw_json, '$.id')
      ) AS employee_id,
      COALESCE(JSON_VALUE(raw_json, '$.department_id'), '') AS department_id,
      COALESCE(JSON_VALUE(raw_json, '$.department'), 'Unassigned') AS department,
      SAFE_CAST(JSON_VALUE(raw_json, '$.hire_date') AS DATE) AS hire_date,
      SAFE_CAST(JSON_VALUE(raw_json, '$.termination_date') AS DATE) AS termination_date,
      UPPER(COALESCE(JSON_VALUE(raw_json, '$.status'), 'ACTIVE')) AS employment_status,
      ROW_NUMBER() OVER (
        PARTITION BY
          COALESCE(JSON_VALUE(raw_json, '$.tenant_id'), '{{TENANT_ID}}'),
          COALESCE(
            JSON_VALUE(raw_json, '$.employee_id'),
            JSON_VALUE(raw_json, '$.user_id'),
            JSON_VALUE(raw_json, '$.id')
          )
        ORDER BY source_file DESC
      ) AS row_number
    FROM (
      SELECT TO_JSON_STRING(employee_row) AS raw_json, _FILE_NAME AS source_file
      FROM `{{PROJECT_ID}}.{{BRONZE_DATASET}}.hris_employees` AS employee_row
    )
  )
  WHERE row_number = 1
),
contracts AS (
  SELECT
    COALESCE(JSON_VALUE(raw_json, '$.tenant_id'), '{{TENANT_ID}}') AS tenant_id,
    COALESCE(JSON_VALUE(raw_json, '$.vendor_id'), JSON_VALUE(raw_json, '$.app_name'))
      AS vendor_id,
    COALESCE(JSON_VALUE(raw_json, '$.app_id'), JSON_VALUE(raw_json, '$.okta_app_id'))
      AS app_id,
    LOWER(JSON_VALUE(raw_json, '$.app_name')) AS app_name,
    COALESCE(JSON_VALUE(raw_json, '$.category'), 'Other') AS app_category,
    SAFE_CAST(JSON_VALUE(raw_json, '$.renewal_date') AS DATE) AS renewal_date,
    SAFE_CAST(JSON_VALUE(raw_json, '$.seat_cost_annual') AS FLOAT64) AS annual_seat_cost,
    COALESCE(
      SAFE_CAST(JSON_VALUE(raw_json, '$.trueup_penalty_rate') AS FLOAT64),
      {{DEFAULT_TRUEUP_PENALTY_RATE}}
    ) AS trueup_penalty_rate
  FROM (
    SELECT TO_JSON_STRING(contract_row) AS raw_json
    FROM `{{PROJECT_ID}}.{{BRONZE_DATASET}}.license_contracts` AS contract_row
  )
  WHERE SAFE_CAST(JSON_VALUE(raw_json, '$.renewal_date') AS DATE) IS NOT NULL
),
seat_snapshots AS (
  SELECT
    assignments.tenant_id,
    assignments.employee_id,
    assignments.vendor_id,
    assignments.app_id,
    assignments.app_name,
    contracts.app_category,
    employees.department_id,
    COALESCE(employees.department, assignments.assignment_department, 'Unassigned')
      AS department,
    employees.hire_date,
    employees.termination_date,
    employees.employment_status,
    assignments.assigned_at,
    contracts.renewal_date,
    contracts.annual_seat_cost,
    contracts.trueup_penalty_rate,
    horizon_days AS renewal_horizon_days,
    DATE_SUB(contracts.renewal_date, INTERVAL horizon_days DAY) AS feature_as_of_date
  FROM assignments
  JOIN contracts
    ON contracts.tenant_id = assignments.tenant_id
   AND (
     (contracts.app_id IS NOT NULL AND contracts.app_id = assignments.app_id)
     OR (contracts.app_name IS NOT NULL AND contracts.app_name = assignments.app_name)
     OR (contracts.vendor_id IS NOT NULL AND contracts.vendor_id = assignments.vendor_id)
   )
  LEFT JOIN employees
    ON employees.tenant_id = assignments.tenant_id
   AND employees.employee_id = assignments.employee_id
  CROSS JOIN UNNEST([120, 90, 60, 30]) AS horizon_days
  WHERE assignments.assigned_at <= DATE_SUB(contracts.renewal_date, INTERVAL horizon_days DAY)
    AND (
      assignments.unassigned_at IS NULL
      OR assignments.unassigned_at > DATE_SUB(contracts.renewal_date, INTERVAL horizon_days DAY)
    )
),
activity_features AS (
  SELECT
    snapshots.*,
    COUNTIF(activity.occurred_at >= TIMESTAMP(DATE_SUB(snapshots.feature_as_of_date, INTERVAL 30 DAY)))
      AS logins_30d,
    COUNTIF(activity.occurred_at >= TIMESTAMP(DATE_SUB(snapshots.feature_as_of_date, INTERVAL 60 DAY)))
      AS logins_60d,
    COUNTIF(activity.occurred_at >= TIMESTAMP(DATE_SUB(snapshots.feature_as_of_date, INTERVAL 90 DAY)))
      AS logins_90d,
    MAX(DATE(activity.occurred_at)) AS last_login_date
  FROM seat_snapshots AS snapshots
  LEFT JOIN `{{PROJECT_ID}}.{{SILVER_DATASET}}.user_activity` AS activity
    ON activity.tenant_id = snapshots.tenant_id
   AND activity.employee_id = snapshots.employee_id
   AND (activity.app_id = snapshots.app_id OR snapshots.app_id IS NULL)
   AND activity.occurred_at < TIMESTAMP(DATE_ADD(snapshots.feature_as_of_date, INTERVAL 1 DAY))
   AND activity.occurred_at >= TIMESTAMP(DATE_SUB(snapshots.feature_as_of_date, INTERVAL 90 DAY))
  GROUP BY ALL
),
app_usage_baselines AS (
  SELECT
    features.*,
    PERCENTILE_CONT(CAST(features.logins_30d AS FLOAT64), 0.5) OVER (
      PARTITION BY
        features.tenant_id,
        features.vendor_id,
        features.renewal_horizon_days,
        features.feature_as_of_date
    ) AS app_median_logins_30d
  FROM activity_features AS features
),
department_snapshots AS (
  SELECT DISTINCT tenant_id, department, feature_as_of_date
  FROM seat_snapshots
),
department_churn AS (
  SELECT
    snapshot.tenant_id,
    snapshot.department,
    snapshot.feature_as_of_date,
    SAFE_DIVIDE(
      COUNTIF(
        employee.termination_date > DATE_SUB(snapshot.feature_as_of_date, INTERVAL 365 DAY)
        AND employee.termination_date <= snapshot.feature_as_of_date
      ),
      COUNTIF(employee.hire_date <= snapshot.feature_as_of_date)
    ) AS department_churn_rate,
    LEAST(
      0.50,
      GREATEST(
        -0.25,
        COALESCE(
          SAFE_DIVIDE(
            COUNTIF(
              employee.hire_date > DATE_SUB(snapshot.feature_as_of_date, INTERVAL 365 DAY)
              AND employee.hire_date <= snapshot.feature_as_of_date
            ) - COUNTIF(
              employee.termination_date > DATE_SUB(snapshot.feature_as_of_date, INTERVAL 365 DAY)
              AND employee.termination_date <= snapshot.feature_as_of_date
            ),
            NULLIF(
              COUNTIF(
                employee.hire_date <= DATE_SUB(snapshot.feature_as_of_date, INTERVAL 365 DAY)
                AND (
                  employee.termination_date IS NULL
                  OR employee.termination_date > DATE_SUB(snapshot.feature_as_of_date, INTERVAL 365 DAY)
                )
              ),
              0
            )
          ),
          0.0
        )
      )
    ) AS department_growth_rate
  FROM department_snapshots AS snapshot
  LEFT JOIN employees AS employee
    ON employee.tenant_id = snapshot.tenant_id
   AND employee.department = snapshot.department
  GROUP BY ALL
)
SELECT
  features.tenant_id,
  features.employee_id,
  features.vendor_id,
  features.app_id,
  features.app_name,
  features.app_category,
  NULLIF(features.department_id, '') AS department_id,
  features.department,
  features.renewal_date,
  features.renewal_horizon_days,
  features.feature_as_of_date,
  COALESCE(features.annual_seat_cost, 0.0) AS annual_seat_cost,
  features.trueup_penalty_rate,
  features.logins_30d,
  features.logins_60d,
  features.logins_90d,
  COALESCE(DATE_DIFF(features.feature_as_of_date, features.last_login_date, DAY), 9999)
    AS days_since_last_login,
  SAFE_DIVIDE(
    features.logins_30d / 30.0,
    (features.logins_90d / 90.0) + 0.0001
  ) AS login_momentum,
  GREATEST(COALESCE(DATE_DIFF(features.feature_as_of_date, features.hire_date, DAY), 0), 0)
    AS tenure_days,
  GREATEST(DATE_DIFF(features.feature_as_of_date, features.assigned_at, DAY), 0)
    AS days_since_assigned,
  COALESCE(churn.department_churn_rate, 0.0) AS department_churn_rate,
  COALESCE(churn.department_growth_rate, 0.0) AS department_growth_rate,
  COALESCE(features.app_median_logins_30d, 0.0) AS app_median_logins_30d,
  SAFE_DIVIDE(
    CAST(features.logins_30d AS FLOAT64) + 0.001,
    COALESCE(features.app_median_logins_30d, 0.0) + 1.0
  ) AS relative_login_ratio,
  CAST(LOWER(features.department) IN ('engineering', 'product', 'r&d') AS INT64)
    AS department_engineering,
  CAST(LOWER(features.department) IN ('sales', 'revenue', 'business development') AS INT64)
    AS department_sales,
  CAST(LOWER(features.department) IN ('marketing', 'growth') AS INT64)
    AS department_marketing,
  CAST(LOWER(features.department) IN ('finance', 'accounting', 'procurement') AS INT64)
    AS department_finance,
  CAST(LOWER(features.department) IN ('hr', 'people', 'hr & legal', 'legal') AS INT64)
    AS department_hr,
  CAST(LOWER(features.department) IN ('operations', 'customer success', 'support') AS INT64)
    AS department_operations,
  CAST(LOWER(features.department) NOT IN (
    'engineering', 'product', 'r&d', 'sales', 'revenue', 'business development',
    'marketing', 'growth', 'finance', 'accounting', 'procurement', 'hr', 'people',
    'hr & legal', 'legal', 'operations', 'customer success', 'support'
  ) AS INT64) AS department_other,
  CAST(LOWER(features.app_category) IN ('sales', 'crm', 'revenue') AS INT64)
    AS app_cat_sales,
  CAST(LOWER(features.app_category) IN ('collaboration', 'communication', 'productivity') AS INT64)
    AS app_cat_collaboration,
  CAST(LOWER(features.app_category) IN ('engineering', 'devtools', 'infrastructure', 'security') AS INT64)
    AS app_cat_engineering,
  CAST(LOWER(features.app_category) IN ('design', 'creative') AS INT64)
    AS app_cat_design,
  CAST(LOWER(features.app_category) IN ('marketing', 'analytics') AS INT64)
    AS app_cat_marketing,
  CAST(LOWER(features.app_category) NOT IN (
    'sales', 'crm', 'revenue', 'collaboration', 'communication', 'productivity',
    'engineering', 'devtools', 'infrastructure', 'security', 'design', 'creative',
    'marketing', 'analytics'
  ) AS INT64) AS app_cat_other,
  CASE
    WHEN features.renewal_date > CURRENT_DATE() THEN NULL
    WHEN features.hire_date <= features.renewal_date
      AND (features.termination_date IS NULL OR features.termination_date >= features.renewal_date)
      AND (
        SELECT COUNT(*)
        FROM `{{PROJECT_ID}}.{{SILVER_DATASET}}.user_activity` AS label_activity
        WHERE label_activity.tenant_id = features.tenant_id
          AND label_activity.employee_id = features.employee_id
          AND (label_activity.app_id = features.app_id OR features.app_id IS NULL)
          AND label_activity.occurred_at >= TIMESTAMP(DATE_SUB(features.renewal_date, INTERVAL 30 DAY))
          AND label_activity.occurred_at < TIMESTAMP(features.renewal_date)
      ) >= 2 THEN 1
    ELSE 0
  END AS retained_label
FROM app_usage_baselines AS features
LEFT JOIN department_churn AS churn
  USING (tenant_id, department, feature_as_of_date);
