WITH session_pattern AS (
    SELECT
        CASE
            WHEN EXTRACT(ISODOW FROM d.full_date) IN (6, 7)
                THEN 'Weekend'
            ELSE 'Weekday'
        END AS day_type,

        t.hour AS start_hour,
        f.energy_kwh

    FROM warehouse.fact_charging_sessions f

    JOIN warehouse.dim_date d
        ON d.date_key = f.date_key

    JOIN warehouse.dim_time t
        ON t.time_key = f.time_key
)

SELECT
    day_type,
    start_hour,
    COUNT(*) AS session_count,

    ROUND(
        SUM(energy_kwh)::NUMERIC,
        3
    ) AS total_energy_kwh,

    ROUND(
        AVG(energy_kwh)::NUMERIC,
        3
    ) AS avg_energy_per_session_kwh

FROM session_pattern

GROUP BY day_type, start_hour
ORDER BY day_type, start_hour;