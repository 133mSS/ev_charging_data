-- =========================================================
-- 03. HOURLY / TIME-OF-DAY ANALYSIS
-- Purpose:
--   Phân tích phụ tải sạc theo giờ trong ngày
-- Grain:
--   1 dòng = 1 giờ
-- =========================================================


-- ---------------------------------------------------------
-- 1. Tổng quan theo giờ
-- ---------------------------------------------------------

SELECT
    t.hour,
    COUNT(*) AS total_sessions,

    ROUND(SUM(f.energy_kwh), 3) AS total_energy_kwh,

    ROUND(AVG(f.energy_kwh), 3) AS avg_energy_kwh_per_session,

    ROUND(
        SUM(f.connection_duration_minutes) / 60.0,
        2
    ) AS total_connection_hours,

    ROUND(
        (
            SUM(f.energy_kwh)
            / NULLIF(
                SUM(f.connection_duration_minutes) / 60.0,
                0
            )
        )::NUMERIC,
        3
    ) AS weighted_avg_power_kw

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_time t
    ON t.time_key = f.time_key

GROUP BY t.hour
ORDER BY t.hour;


-- ---------------------------------------------------------
-- 2. Phân tích theo khung thời gian trong ngày
-- ---------------------------------------------------------

SELECT
    t.time_of_day,
    COUNT(*) AS total_sessions,

    ROUND(SUM(f.energy_kwh), 3) AS total_energy_kwh,

    ROUND(AVG(f.energy_kwh), 3) AS avg_energy_kwh_per_session

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_time t
    ON t.time_key = f.time_key

GROUP BY t.time_of_day
ORDER BY
    CASE t.time_of_day
        WHEN 'Night' THEN 1
        WHEN 'Morning' THEN 2
        WHEN 'Afternoon' THEN 3
        WHEN 'Evening' THEN 4
    END;
