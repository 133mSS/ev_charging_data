-- Repeatable Snowflake data-quality and reconciliation gate.
-- Each row is a check; deployment stops when any status is FAIL.
USE DATABASE JPL_ANALYTICS;
USE WAREHOUSE JPL_ETL_WH;

WITH CHECKS AS (
    SELECT
        'DUPLICATE_SESSION_KEYS' AS CHECK_NAME,
        (
            SELECT COUNT(*)
            FROM (
                SELECT SESSION_ID
                FROM WAREHOUSE.FACT_CHARGING_SESSIONS
                GROUP BY SESSION_ID
                HAVING COUNT(*) > 1
            )
        ) AS OBSERVED_VALUE,
        0 AS EXPECTED_VALUE,
        'EQUAL' AS CHECK_TYPE,
        'FACT_CHARGING_SESSIONS must contain one row per SESSION_ID.' AS DETAILS

    UNION ALL
    SELECT
        'DUPLICATE_STATION_DIMENSION_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT STATION_ID
                FROM WAREHOUSE.DIM_STATION
                GROUP BY STATION_ID
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'DIM_STATION must contain one row per STATION_ID.'

    UNION ALL
    SELECT
        'DUPLICATE_DATE_DIMENSION_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT DATE_KEY
                FROM WAREHOUSE.DIM_DATE
                GROUP BY DATE_KEY
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'DIM_DATE must contain one row per DATE_KEY.'

    UNION ALL
    SELECT
        'DUPLICATE_TIME_DIMENSION_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT TIME_KEY
                FROM WAREHOUSE.DIM_TIME
                GROUP BY TIME_KEY
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'DIM_TIME must contain one row per TIME_KEY.'

    UNION ALL
    SELECT
        'ORPHAN_SESSION_DATE_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
            LEFT JOIN WAREHOUSE.DIM_DATE D ON D.DATE_KEY = F.DATE_KEY
            WHERE D.DATE_KEY IS NULL
        ),
        0,
        'EQUAL',
        'Every charging-session DATE_KEY must resolve to DIM_DATE.'

    UNION ALL
    SELECT
        'ORPHAN_SESSION_TIME_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
            LEFT JOIN WAREHOUSE.DIM_TIME T ON T.TIME_KEY = F.TIME_KEY
            WHERE T.TIME_KEY IS NULL
        ),
        0,
        'EQUAL',
        'Every charging-session TIME_KEY must resolve to DIM_TIME.'

    UNION ALL
    SELECT
        'DUPLICATE_USER_REQUEST_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT SESSION_ID, INPUT_ID
                FROM WAREHOUSE.FACT_USER_REQUESTS
                GROUP BY SESSION_ID, INPUT_ID
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'FACT_USER_REQUESTS grain is one row per SESSION_ID and INPUT_ID.'

    UNION ALL
    SELECT
        'DUPLICATE_USER_DIMENSION_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT USER_ID_KEY
                FROM WAREHOUSE.DIM_USER
                GROUP BY USER_ID_KEY
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'DIM_USER must have one row per canonical USER_ID_KEY.'

    UNION ALL
    SELECT
        'MISSING_SESSION_USER_KEYS',
        (
            SELECT COALESCE(COUNT_IF(USER_ID IS NOT NULL AND USER_ID_KEY IS NULL), 0)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS
        ),
        0,
        'EQUAL',
        'Every non-null source USER_ID in the session fact must have a canonical key.'

    UNION ALL
    SELECT
        'MISSING_REQUEST_USER_KEYS',
        (
            SELECT COALESCE(COUNT_IF(USER_ID IS NOT NULL AND USER_ID_KEY IS NULL), 0)
            FROM WAREHOUSE.FACT_USER_REQUESTS
        ),
        0,
        'EQUAL',
        'Every non-null source USER_ID in the request fact must have a canonical key.'

    UNION ALL
    SELECT
        'ORPHAN_SESSION_USER_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
            LEFT JOIN WAREHOUSE.DIM_USER D
                ON D.USER_ID_KEY = F.USER_ID_KEY
            WHERE F.USER_ID_KEY IS NOT NULL
              AND D.USER_ID_KEY IS NULL
        ),
        0,
        'EQUAL',
        'Every non-null session USER_ID_KEY must resolve to DIM_USER.'

    UNION ALL
    SELECT
        'ORPHAN_REQUEST_USER_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS F
            LEFT JOIN WAREHOUSE.DIM_USER D
                ON D.USER_ID_KEY = F.USER_ID_KEY
            WHERE F.USER_ID_KEY IS NOT NULL
              AND D.USER_ID_KEY IS NULL
        ),
        0,
        'EQUAL',
        'Every non-null request USER_ID_KEY must resolve to DIM_USER.'

    UNION ALL
    SELECT
        'REQUEST_SESSION_USER_KEY_MISMATCHES',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS R
            JOIN WAREHOUSE.FACT_CHARGING_SESSIONS S
                ON S.SESSION_ID = R.SESSION_ID
            WHERE R.USER_ID IS NOT NULL
              AND S.USER_ID IS NOT NULL
              AND R.USER_ID_KEY <> S.USER_ID_KEY
        ),
        0,
        'EQUAL',
        'Each request USER_ID_KEY must match the USER_ID_KEY of its parent session.'

    UNION ALL
    SELECT
        'ORPHAN_REQUEST_SESSION_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_USER_REQUESTS R
            LEFT JOIN WAREHOUSE.FACT_CHARGING_SESSIONS S
                ON S.SESSION_ID = R.SESSION_ID
            WHERE S.SESSION_ID IS NULL
        ),
        0,
        'EQUAL',
        'Every request must resolve to exactly one session fact; duplicate session keys are checked separately.'

    UNION ALL
    SELECT
        'Q4_LATEST_REQUEST_DUPLICATE_SESSIONS',
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
        0,
        'EQUAL',
        'Q4 output must contain at most one row per session after selecting the latest request and joining session energy.'

    UNION ALL
    SELECT
        'DUPLICATE_STATIC_MAPPING_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT STATIC_SESSION_ID
                FROM RAW.STG_SESSION_MAPPING
                WHERE STATIC_SESSION_ID IS NOT NULL
                GROUP BY STATIC_SESSION_ID
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'Each Static session identifier must map to at most one mapping row.'

    UNION ALL
    SELECT
        'DUPLICATE_API_MAPPING_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT API_SESSION_ID
                FROM RAW.STG_SESSION_MAPPING
                WHERE API_SESSION_ID IS NOT NULL
                GROUP BY API_SESSION_ID
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'Each non-null API session identifier must map to at most one mapping row.'

    UNION ALL
    SELECT
        'STATIC_ROW_RECONCILIATION_DELTA',
        (
            SELECT ABS(
                COUNT(*) - COUNT_IF(MATCH_STATUS IN ('MATCHED', 'STATIC_ONLY'))
            )
            FROM WAREHOUSE.FACT_STATIC_MEASUREMENTS
        ),
        0,
        'EQUAL',
        'All Static measurement rows must be classified as MATCHED or STATIC_ONLY.'

    UNION ALL
    SELECT
        'UNMAPPED_STATIC_ROWS',
        (
            SELECT COALESCE(COUNT_IF(MATCH_STATUS = 'UNMAPPED_STATIC'), 0)
            FROM WAREHOUSE.FACT_STATIC_MEASUREMENTS
        ),
        0,
        'EQUAL',
        'The full Static view must preserve and classify every source Static session.'

    UNION ALL
    SELECT
        'ORPHAN_SESSION_STATION_KEYS',
        (
            SELECT COUNT(*)
            FROM WAREHOUSE.FACT_CHARGING_SESSIONS F
            LEFT JOIN WAREHOUSE.DIM_STATION D
                ON D.STATION_ID = F.STATION_ID
            WHERE F.STATION_ID IS NOT NULL
              AND D.STATION_ID IS NULL
        ),
        0,
        'EQUAL',
        'Every non-null station on a charging-session fact must resolve to DIM_STATION.'

    UNION ALL
    SELECT
        'INVALID_POST_LAST_CURRENT_INTERVALS',
        (
            SELECT COALESCE(COUNT_IF(
                POST_LAST_CURRENT_MINUTES < 0
                OR LAST_NONZERO_CURRENT_UTC < F.CONNECTION_TIME_UTC
                OR LAST_NONZERO_CURRENT_UTC > F.DISCONNECT_TIME_UTC
            ), 0)
            FROM MART.SESSION_POST_CURRENT F
        ),
        0,
        'EQUAL',
        'The last positive-current timestamp must be inside the API connection interval.'

    UNION ALL
    SELECT
        'POWER_SITE_HOUR_COUNT',
        (SELECT COUNT(*) FROM MART.POWER_SITE_HOUR),
        3673,
        'EQUAL',
        'The July-November 2020 site calendar contains 3,673 elapsed UTC hours.'

    UNION ALL
    SELECT
        'DUPLICATE_POWER_SITE_HOUR_KEYS',
        (
            SELECT COUNT(*)
            FROM (
                SELECT UTC_HOUR_START
                FROM MART.POWER_SITE_HOUR
                GROUP BY UTC_HOUR_START
                HAVING COUNT(*) > 1
            )
        ),
        0,
        'EQUAL',
        'The complete site-hour calendar must have one row per UTC hour.'

    UNION ALL
    SELECT
        'CHARGING_SESSION_FACT_NONEMPTY',
        (SELECT COUNT(*) FROM WAREHOUSE.FACT_CHARGING_SESSIONS),
        1,
        'AT_LEAST',
        'The API charging-session fact must contain records.'

    UNION ALL
    SELECT
        'STATIC_MEASUREMENT_FACT_NONEMPTY',
        (SELECT COUNT(*) FROM WAREHOUSE.FACT_STATIC_MEASUREMENTS),
        1,
        'AT_LEAST',
        'The full Static measurement view must contain records.'
)
SELECT
    CHECK_NAME,
    OBSERVED_VALUE,
    EXPECTED_VALUE,
    CASE
        WHEN CHECK_TYPE = 'EQUAL' AND OBSERVED_VALUE = EXPECTED_VALUE THEN 'PASS'
        WHEN CHECK_TYPE = 'AT_LEAST' AND OBSERVED_VALUE >= EXPECTED_VALUE THEN 'PASS'
        ELSE 'FAIL'
    END AS STATUS,
    DETAILS
FROM CHECKS
ORDER BY STATUS DESC, CHECK_NAME;
