-- =========================================================
-- 01. OVERVIEW ANALYSIS
-- Purpose:
--   Tổng quan hoạt động sạc tại JPL
-- Grain:
--   Toàn bộ charging sessions
-- =========================================================


-- ---------------------------------------------------------
-- 1. Tổng quan hệ thống
-- ---------------------------------------------------------

SELECT
    COUNT(*) AS total_sessions,
    ROUND(SUM(energy_kwh), 3) AS total_energy_kwh,
    ROUND(SUM(connection_duration_minutes) / 60.0, 2)
        AS total_connection_hours,
    ROUND(
        SUM(energy_kwh)
        / NULLIF(SUM(connection_duration_minutes) / 60.0, 0),
        3
    ) AS weighted_avg_power_kw
FROM warehouse.fact_charging_sessions;


-- ---------------------------------------------------------
-- 2. Thống kê năng lượng mỗi session
-- ---------------------------------------------------------

SELECT
    ROUND(AVG(energy_kwh), 3) AS avg_energy_kwh_per_session,
    ROUND(MIN(energy_kwh), 3) AS min_energy_kwh,
    ROUND(MAX(energy_kwh), 3) AS max_energy_kwh,
    ROUND(
    (
        PERCENTILE_CONT(0.5)
        WITHIN GROUP (ORDER BY energy_kwh)
    )::NUMERIC,
    3
) AS median_energy_kwh
FROM warehouse.fact_charging_sessions;


-- ---------------------------------------------------------
-- 3. Thống kê thời gian kết nối
-- ---------------------------------------------------------

SELECT
    ROUND(AVG(connection_duration_minutes), 2)
        AS avg_connection_minutes,
    ROUND(MIN(connection_duration_minutes), 2)
        AS min_connection_minutes,
    ROUND(MAX(connection_duration_minutes), 2)
        AS max_connection_minutes,
    ROUND(
        (
            PERCENTILE_CONT(0.5)
            WITHIN GROUP (
                ORDER BY connection_duration_minutes
            )
        )::NUMERIC,
        2
    ) AS median_connection_minutes
FROM warehouse.fact_charging_sessions;


-- ---------------------------------------------------------
-- 4. Phân bố session theo năm
-- ---------------------------------------------------------

SELECT
    d.year,
    COUNT(*) AS total_sessions,
    ROUND(SUM(f.energy_kwh), 3) AS total_energy_kwh,
    ROUND(AVG(f.energy_kwh), 3) AS avg_energy_kwh
FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key
GROUP BY d.year
ORDER BY d.year;


-- ---------------------------------------------------------
-- 5. Tỷ lệ session có user metadata
-- ---------------------------------------------------------

SELECT
    has_user_metadata,
    COUNT(*) AS total_sessions,
    ROUND(
        COUNT(*) * 100.0
        / SUM(COUNT(*)) OVER (),
        2
    ) AS percentage
FROM warehouse.fact_charging_sessions
GROUP BY has_user_metadata
ORDER BY has_user_metadata;
