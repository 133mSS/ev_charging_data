
-- =========================================================
-- 02. MONTHLY TREND ANALYSIS
-- Purpose:
--   Phân tích xu hướng sử dụng trạm sạc theo tháng
-- Grain:
--   1 dòng = 1 tháng
-- =========================================================


-- ---------------------------------------------------------
-- 1. Tổng quan theo tháng
-- ---------------------------------------------------------

SELECT
    d.year,
    d.month,
    d.month_name,

    COUNT(*) AS total_sessions,

    ROUND(
        SUM(f.energy_kwh),
        3
    ) AS total_energy_kwh,

    ROUND(
        AVG(f.energy_kwh),
        3
    ) AS avg_energy_kwh_per_session,

    ROUND(
        SUM(f.connection_duration_minutes) / 60.0,
        2
    ) AS total_connection_hours,

    ROUND(
        SUM(f.energy_kwh)
        / NULLIF(
            SUM(f.connection_duration_minutes) / 60.0,
            0
        ),
        3
    ) AS weighted_avg_power_kw

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key

GROUP BY
    d.year,
    d.month,
    d.month_name

ORDER BY
    d.year,
    d.month;


-- ---------------------------------------------------------
-- 2. Tổng điện năng theo tháng
-- ---------------------------------------------------------

SELECT
    d.year,
    d.month,
    d.month_name,
    ROUND(SUM(f.energy_kwh), 3) AS total_energy_kwh

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key

GROUP BY
    d.year,
    d.month,
    d.month_name

ORDER BY
    d.year,
    d.month;


-- ---------------------------------------------------------
-- 3. Số session theo tháng
-- ---------------------------------------------------------

SELECT
    d.year,
    d.month,
    d.month_name,
    COUNT(*) AS total_sessions

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key

GROUP BY
    d.year,
    d.month,
    d.month_name

ORDER BY
    d.year,
    d.month;

