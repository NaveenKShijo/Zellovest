-- Deduplicated, successful Okta SSO/session activity resolved to employee IDs.
-- JSON_VALUE over the serialized source row tolerates optional Okta fields.

CREATE SCHEMA IF NOT EXISTS `{{PROJECT_ID}}.{{SILVER_DATASET}}`
OPTIONS(location = '{{BQ_LOCATION}}');

CREATE OR REPLACE TABLE `{{PROJECT_ID}}.{{SILVER_DATASET}}.user_activity`
PARTITION BY DATE(occurred_at)
CLUSTER BY tenant_id, employee_id, app_id AS
WITH raw_logs AS (
  SELECT
    TO_JSON_STRING(log_row) AS raw_json,
    _FILE_NAME AS source_file
  FROM `{{PROJECT_ID}}.{{BRONZE_DATASET}}.okta_logs` AS log_row
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
      LOWER(COALESCE(
        JSON_VALUE(raw_json, '$.email'),
        JSON_VALUE(raw_json, '$.profile.email')
      )) AS email,
      ROW_NUMBER() OVER (
        PARTITION BY LOWER(COALESCE(
          JSON_VALUE(raw_json, '$.email'),
          JSON_VALUE(raw_json, '$.profile.email')
        ))
        ORDER BY _FILE_NAME DESC
      ) AS row_number
    FROM (
      SELECT TO_JSON_STRING(employee_row) AS raw_json, _FILE_NAME
      FROM `{{PROJECT_ID}}.{{BRONZE_DATASET}}.hris_employees` AS employee_row
    )
  )
  WHERE row_number = 1
),
parsed AS (
  SELECT
    '{{TENANT_ID}}' AS tenant_id,
    JSON_VALUE(raw_json, '$.id') AS okta_event_id,
    SAFE_CAST(JSON_VALUE(raw_json, '$.published') AS TIMESTAMP) AS occurred_at,
    JSON_VALUE(raw_json, '$.eventType') AS event_type,
    UPPER(JSON_VALUE(raw_json, '$.outcome.result')) AS outcome_result,
    LOWER(JSON_VALUE(raw_json, '$.actor.alternateId')) AS actor_email,
    (
      SELECT JSON_VALUE(target, '$.id')
      FROM UNNEST(IFNULL(JSON_QUERY_ARRAY(raw_json, '$.target'), [])) AS target
      WHERE JSON_VALUE(target, '$.type') = 'AppInstance'
      LIMIT 1
    ) AS app_id,
    (
      SELECT JSON_VALUE(target, '$.displayName')
      FROM UNNEST(IFNULL(JSON_QUERY_ARRAY(raw_json, '$.target'), [])) AS target
      WHERE JSON_VALUE(target, '$.type') = 'AppInstance'
      LIMIT 1
    ) AS app_name,
    source_file,
    raw_json
  FROM raw_logs
)
SELECT
  parsed.tenant_id,
  parsed.okta_event_id,
  employees.employee_id,
  parsed.actor_email AS user_email,
  parsed.app_id,
  parsed.app_name,
  parsed.event_type,
  parsed.outcome_result,
  parsed.occurred_at,
  parsed.source_file,
  PARSE_JSON(parsed.raw_json) AS raw_signal
FROM parsed
LEFT JOIN employees
  ON employees.tenant_id = parsed.tenant_id
 AND employees.email = parsed.actor_email
WHERE parsed.okta_event_id IS NOT NULL
  AND parsed.occurred_at IS NOT NULL
  AND parsed.event_type IN ('user.authentication.sso', 'user.session.start')
  AND parsed.outcome_result = 'SUCCESS'
QUALIFY ROW_NUMBER() OVER (
  PARTITION BY parsed.tenant_id, parsed.okta_event_id
  ORDER BY parsed.source_file DESC
) = 1;
