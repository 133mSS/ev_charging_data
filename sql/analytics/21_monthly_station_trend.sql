-- 21_monthly_station_trend.sql
-- Theo dõi năng lượng từng trạm và biến động so với tháng trước.

WITH bounds AS (
    SELECT
        DATE_TRUNC('month', MIN(d.full_date))::date AS start_month,
        DATE_TRUNC('month', MAX(d.full_date))::date AS end_month
    FROM warehouse.fact_charging_sessions f
    JOIN warehouse.dim_date d
        ON d.date_key = f.date_key
),

months AS (
    SELECT gs.month_start::date AS month_start
    FROM bounds b
    CROSS JOIN LATERAL GENERATE_SERIES(
        b.start_month::timestamp,
        b.end_month::timestamp,
        INTERVAL '1 month'
    ) AS gs(month_start)
),

stations AS (
    SELECT station_key, station_id
    FROM warehouse.dim_station
),

monthly_actual AS (
    SELECT
        f.station_key,
        DATE_TRUNC('month', d.full_date)::date AS month_start,
        COUNT(*) AS session_count,
        SUM(f.energy_kwh) AS energy_kwh
    FROM warehouse.fact_charging_sessions f
    JOIN warehouse.dim_date d
        ON d.date_key = f.date_key
    GROUP BY
        f.station_key,
        DATE_TRUNC('month', d.full_date)::date
),

monthly_grid AS (
    SELECT
        m.month_start,
        s.station_key,
        s.station_id,
        COALESCE(a.session_count, 0) AS session_count,
        COALESCE(a.energy_kwh, 0)::numeric AS energy_kwh
    FROM months m
    CROSS JOIN stations s
    LEFT JOIN monthly_actual a
        ON a.month_start = m.month_start
       AND a.station_key = s.station_key
),

with_previous_month AS (
    SELECT
        *,
        LAG(session_count) OVER (
            PARTITION BY station_key
            ORDER BY month_start
        ) AS previous_session_count,

        LAG(energy_kwh) OVER (
            PARTITION BY station_key
            ORDER BY month_start
        ) AS previous_energy_kwh
    FROM monthly_grid
)

SELECT
    TO_CHAR(month_start, 'YYYY-MM') AS month_label,
    station_id,
    session_count,
    ROUND(energy_kwh, 3) AS total_energy_kwh,

    ROUND(
        100.0 * energy_kwh
        / NULLIF(
            SUM(energy_kwh) OVER (PARTITION BY month_start),
            0
        ),
        2
    ) AS monthly_energy_share_pct,

    previous_session_count,

    session_count - previous_session_count
        AS session_change,

    ROUND(
        energy_kwh - previous_energy_kwh,
        3
    ) AS energy_change_kwh,

    ROUND(
        100.0 * (energy_kwh - previous_energy_kwh)
        / NULLIF(previous_energy_kwh, 0),
        2
    ) AS energy_change_pct

FROM with_previous_month
ORDER BY month_start, station_id;