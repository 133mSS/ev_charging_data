-- =========================================================
-- 04. STATION ANALYSIS
-- Purpose:
--   So sánh mức độ sử dụng và tiêu thụ điện giữa các station
-- Grain:
--   1 dòng = 1 station
-- =========================================================


SELECT
    ds.station_id,
    ds.space_id,
    ds.site_id,
    ds.cluster_id,

    COUNT(f.session_id) AS total_sessions,

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

JOIN warehouse.dim_station ds
    ON ds.station_key = f.station_key

GROUP BY
    ds.station_id,
    ds.space_id,
    ds.site_id,
    ds.cluster_id

ORDER BY total_energy_kwh DESC;
