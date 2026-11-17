WITH session_buckets AS (
    SELECT
        CASE
            WHEN connection_duration_minutes < 60
                THEN '< 1 hour'
            WHEN connection_duration_minutes < 180
                THEN '1–3 hours'
            WHEN connection_duration_minutes < 360
                THEN '3–6 hours'
            ELSE '>= 6 hours'
        END AS duration_group,

        connection_duration_minutes,
        energy_kwh

    FROM warehouse.fact_charging_sessions

    WHERE connection_duration_minutes > 0
      AND energy_kwh IS NOT NULL
)

SELECT
    duration_group,
    COUNT(*) AS session_count,

    ROUND(
        AVG(connection_duration_minutes)::NUMERIC,
        2
    ) AS avg_connection_minutes,

    ROUND(
        AVG(energy_kwh)::NUMERIC,
        3
    ) AS avg_energy_per_session_kwh,

    ROUND(
        SUM(energy_kwh)::NUMERIC,
        3
    ) AS total_energy_kwh,

    ROUND(
        (
            SUM(energy_kwh)
            / NULLIF(
                SUM(connection_duration_minutes) / 60.0,
                0
            )
        )::NUMERIC,
        3
    ) AS energy_per_connection_hour

FROM session_buckets

GROUP BY duration_group

ORDER BY
    CASE duration_group
        WHEN '< 1 hour' THEN 1
        WHEN '1–3 hours' THEN 2
        WHEN '3–6 hours' THEN 3
        ELSE 4
    END;