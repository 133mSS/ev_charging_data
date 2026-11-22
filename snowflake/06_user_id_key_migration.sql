-- Targeted, idempotent migration for an existing Snowflake warehouse.
-- Preserves source USER_ID values and does not reload RAW or rebuild Static marts.
USE DATABASE JPL_ANALYTICS;
USE WAREHOUSE JPL_ETL_WH;

ALTER TABLE WAREHOUSE.DIM_USER
    ADD COLUMN IF NOT EXISTS USER_ID_KEY VARCHAR;
ALTER TABLE WAREHOUSE.FACT_CHARGING_SESSIONS
    ADD COLUMN IF NOT EXISTS USER_ID_KEY VARCHAR;
ALTER TABLE WAREHOUSE.FACT_USER_REQUESTS
    ADD COLUMN IF NOT EXISTS USER_ID_KEY VARCHAR;

-- Canonicalize numeric identifiers only. Non-numeric identifiers are trimmed
-- but otherwise preserved; an all-zero identifier remains '0'.
UPDATE WAREHOUSE.DIM_USER
SET USER_ID_KEY = CASE
        WHEN USER_ID IS NULL THEN NULL
        WHEN TRIM(TO_VARCHAR(USER_ID)) = '' THEN NULL
        WHEN REGEXP_LIKE(TRIM(TO_VARCHAR(USER_ID)), '^[0-9]+$')
            THEN COALESCE(NULLIF(LTRIM(TRIM(TO_VARCHAR(USER_ID)), '0'), ''), '0')
        ELSE TRIM(TO_VARCHAR(USER_ID))
    END;
UPDATE WAREHOUSE.FACT_CHARGING_SESSIONS
SET USER_ID_KEY = CASE
        WHEN USER_ID IS NULL THEN NULL
        WHEN TRIM(TO_VARCHAR(USER_ID)) = '' THEN NULL
        WHEN REGEXP_LIKE(TRIM(TO_VARCHAR(USER_ID)), '^[0-9]+$')
            THEN COALESCE(NULLIF(LTRIM(TRIM(TO_VARCHAR(USER_ID)), '0'), ''), '0')
        ELSE TRIM(TO_VARCHAR(USER_ID))
    END;
UPDATE WAREHOUSE.FACT_USER_REQUESTS
SET USER_ID_KEY = CASE
        WHEN USER_ID IS NULL THEN NULL
        WHEN TRIM(TO_VARCHAR(USER_ID)) = '' THEN NULL
        WHEN REGEXP_LIKE(TRIM(TO_VARCHAR(USER_ID)), '^[0-9]+$')
            THEN COALESCE(NULLIF(LTRIM(TRIM(TO_VARCHAR(USER_ID)), '0'), ''), '0')
        ELSE TRIM(TO_VARCHAR(USER_ID))
    END;

-- This focused gate deliberately validates only small session/request tables.
-- It avoids scanning the 175M-row Static view or rebuilding Power marts.
WITH CHECKS AS (
    SELECT
        'DUPLICATE_USER_DIMENSION_KEYS' AS CHECK_NAME,
        (
            SELECT COUNT(*)
            FROM (
                SELECT USER_ID_KEY
                FROM WAREHOUSE.DIM_USER
                GROUP BY USER_ID_KEY
                HAVING COUNT(*) > 1
            )
        ) AS OBSERVED_VALUE,
        0 AS EXPECTED_VALUE,
        'EQUAL' AS CHECK_TYPE,
        'DIM_USER must contain one row per canonical USER_ID_KEY.' AS DETAILS

    UNION ALL
    SELECT
        'MISSING_SESSION_USER_KEYS',
        (
            SELECT COALESCE(COUNT_IF(USER_ID IS NOT NULL AND USER_ID_KEY IS NULL), 0)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS
        ),
        0, 'EQUAL',
        'Every non-null source USER_ID in the session fact must have a canonical key.'

    UNION ALL
    SELECT
        'MISSING_REQUEST_USER_KEYS',
        (
            SELECT COALESCE(COUNT_IF(USER_ID IS NOT NULL AND USER_ID_KEY IS NULL), 0)
            FROM WAREHOUSE.FACT_USER_REQUESTS
        ),
        0, 'EQUAL',
        'Every non-null source USER_ID in the request fact must have a canonical key.'

    UNION ALL
    SELECT
        'ORPHAN_SESSION_USER_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
            WHERE F.USER_ID_KEY IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM WAREHOUSE.DIM_USER D
                  WHERE D.USER_ID_KEY = F.USER_ID_KEY
              )
        ),
        0, 'EQUAL',
        'Every non-null session USER_ID_KEY must resolve to DIM_USER.'

    UNION ALL
    SELECT
        'ORPHAN_REQUEST_USER_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS F
            WHERE F.USER_ID_KEY IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM WAREHOUSE.DIM_USER D
                  WHERE D.USER_ID_KEY = F.USER_ID_KEY
              )
        ),
        0, 'EQUAL',
        'Every non-null request USER_ID_KEY must resolve to DIM_USER.'

    UNION ALL
    SELECT
        'REQUEST_SESSION_USER_KEY_MISMATCHES',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS R
            JOIN WAREHOUSE.FACT_CHARGING_SESSIONS S
                ON S.SESSION_ID = R.SESSION_ID
            WHERE R.USER_ID_KEY IS NULL
               OR S.USER_ID_KEY IS NULL
               OR R.USER_ID_KEY <> S.USER_ID_KEY
        ),
        0, 'EQUAL',
        'Each request USER_ID_KEY must match the USER_ID_KEY of its parent session.'

    UNION ALL
    SELECT
        'ORPHAN_REQUEST_SESSION_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS R
            WHERE NOT EXISTS (
                SELECT 1
                FROM WAREHOUSE.FACT_CHARGING_SESSIONS S
                WHERE S.SESSION_ID = R.SESSION_ID
            )
        ),
        0, 'EQUAL',
        'Every request must resolve to a session fact.'

    UNION ALL
    SELECT
        'SESSION_USERS_MISSING_FROM_REQUEST_USERS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT S.USER_ID_KEY
                FROM WAREHOUSE.FACT_CHARGING_SESSIONS S
                WHERE S.USER_ID_KEY IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM WAREHOUSE.FACT_USER_REQUESTS R
                      WHERE R.USER_ID_KEY = S.USER_ID_KEY
                  )
            )
        ),
        0, 'EQUAL',
        'The audited snapshot has the same normalized user population in both API surfaces.'

    UNION ALL
    SELECT
        'REQUEST_USERS_MISSING_FROM_SESSION_USERS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT R.USER_ID_KEY
                FROM WAREHOUSE.FACT_USER_REQUESTS R
                WHERE R.USER_ID_KEY IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM WAREHOUSE.FACT_CHARGING_SESSIONS S
                      WHERE S.USER_ID_KEY = R.USER_ID_KEY
                  )
            )
        ),
        0, 'EQUAL',
        'The audited snapshot has the same normalized user population in both API surfaces.'

    UNION ALL
    SELECT
        'DUPLICATE_SESSION_FACT_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT SESSION_ID
                FROM WAREHOUSE.FACT_CHARGING_SESSIONS
                GROUP BY SESSION_ID
                HAVING COUNT(*) > 1
            )
        ),
        0, 'EQUAL',
        'The session fact grain must remain one row per SESSION_ID.'

    UNION ALL
    SELECT
        'DUPLICATE_USER_REQUEST_FACT_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT SESSION_ID, INPUT_ID
                FROM WAREHOUSE.FACT_USER_REQUESTS
                GROUP BY SESSION_ID, INPUT_ID
                HAVING COUNT(*) > 1
            )
        ),
        0, 'EQUAL',
        'The request fact grain must remain one row per SESSION_ID and INPUT_ID.'

    UNION ALL
    SELECT
        'Q4_DUPLICATE_SESSION_ROWS_AFTER_LATEST_REQUEST',
        (
            SELECT COUNT(*)
            FROM (
                SELECT F.SESSION_ID
                FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
                JOIN (
                    SELECT SESSION_ID, KWH_REQUESTED
                    FROM WAREHOUSE.FACT_USER_REQUESTS
                    QUALIFY ROW_NUMBER() OVER (
                        PARTITION BY SESSION_ID
                        ORDER BY MODIFIED_AT DESC NULLS LAST, INPUT_ID DESC
                    ) = 1
                ) L
                    ON L.SESSION_ID = F.SESSION_ID
                WHERE L.KWH_REQUESTED > 0
                GROUP BY F.SESSION_ID
                HAVING COUNT(*) > 1
            )
        ),
        0, 'EQUAL',
        'Q4 must select at most one request per session before joining session energy.'
)
SELECT
    CHECK_NAME,
    OBSERVED_VALUE,
    EXPECTED_VALUE,
    CASE
        WHEN CHECK_TYPE = 'EQUAL' AND OBSERVED_VALUE = EXPECTED_VALUE THEN 'PASS'
        ELSE 'FAIL'
    END AS STATUS,
    DETAILS
FROM CHECKS
ORDER BY STATUS DESC, CHECK_NAME;
