-- Q1: Compare typical weekday and weekend charging demand by local start hour.
-- Counts and kWh are normalized by the number of calendar days in each day type,
-- so five weekdays per week are not compared directly with two weekend days.
WITH calendar_days AS (
    SELECT
        d.full_date,
        CASE
            WHEN EXTRACT(ISODOW FROM d.full_date) IN (6, 7)
                THEN 'Cuối tuần'
            ELSE 'Ngày thường'
        END AS day_type
    FROM warehouse.dim_date d
    WHERE d.full_date >= CAST(:start_date AS DATE)
      AND d.full_date < CAST(:end_date_exclusive AS DATE)
),
day_type_counts AS (
    SELECT
        day_type,
        COUNT(*) AS calendar_days
    FROM calendar_days
    GROUP BY day_type
),
activity AS (
    SELECT
        cd.day_type,
        t.hour AS local_hour,
        COUNT(*) AS session_count,
        SUM(f.energy_kwh) AS total_energy_kwh
    FROM warehouse.fact_charging_sessions f
    JOIN warehouse.dim_date d
        ON d.date_key = f.date_key
    JOIN warehouse.dim_time t
        ON t.time_key = f.time_key
    JOIN calendar_days cd
        ON cd.full_date = d.full_date
    GROUP BY cd.day_type, t.hour
),
hours AS (
    SELECT generate_series(0, 23)::INTEGER AS local_hour
)
SELECT
    dc.day_type,
    h.local_hour,
    dc.calendar_days,
    COALESCE(a.session_count, 0) AS session_count,
    COALESCE(a.total_energy_kwh, 0) AS total_energy_kwh,
    COALESCE(a.session_count, 0)::NUMERIC
        / NULLIF(dc.calendar_days, 0) AS avg_sessions_per_day,
    COALESCE(a.total_energy_kwh, 0)::NUMERIC
        / NULLIF(dc.calendar_days, 0) AS avg_start_hour_energy_kwh_per_day
FROM day_type_counts dc
CROSS JOIN hours h
LEFT JOIN activity a
    ON a.day_type = dc.day_type
   AND a.local_hour = h.local_hour
ORDER BY
    CASE dc.day_type
        WHEN 'Ngày thường' THEN 1
        ELSE 2
    END,
    h.local_hour;
