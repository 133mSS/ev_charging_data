-- 22_station_usage_ranking.sql
-- Xếp hạng mức sử dụng ghi nhận theo từng trạm trong khoảng thời gian chọn.
-- Lưu ý: số phiên và kWh không phải utilization rate theo thời gian hoạt động.

SELECT
    ds.station_id,
    COUNT(*) AS session_count,
    ROUND(SUM(f.energy_kwh), 3) AS total_energy_kwh,
    ROUND(AVG(f.energy_kwh), 3) AS avg_energy_per_session_kwh,
    ROUND(AVG(f.connection_duration_minutes), 2)
        AS avg_connection_minutes,
    ROUND(
        100.0 * SUM(f.energy_kwh)
        / NULLIF(SUM(SUM(f.energy_kwh)) OVER (), 0),
        2
    ) AS energy_share_pct
FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_station ds
    ON ds.station_key = f.station_key
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key
WHERE d.full_date >= CAST(:start_date AS DATE)
  AND d.full_date < CAST(:end_date_exclusive AS DATE)
GROUP BY ds.station_id
ORDER BY total_energy_kwh DESC, session_count DESC;
