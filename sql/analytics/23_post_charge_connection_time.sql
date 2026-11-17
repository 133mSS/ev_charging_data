-- 23_post_charge_connection_time.sql
-- Khoảng thời gian xe vẫn kết nối sau thời điểm cuối cùng ghi nhận dòng điện khác 0.
-- Chỉ lấy các phiên có done_charging_time nằm trong [connection_time, disconnect_time].

SELECT
    f.session_id,
    ds.station_id,
    d.full_date,
    f.energy_kwh,
    f.done_charging_time,
    f.post_charge_connection_minutes
FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_station ds
    ON ds.station_key = f.station_key
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key
WHERE d.full_date >= CAST(:start_date AS DATE)
  AND d.full_date < CAST(:end_date_exclusive AS DATE)
  AND f.post_charge_connection_minutes IS NOT NULL
  AND f.post_charge_connection_minutes >= 0
ORDER BY f.post_charge_connection_minutes DESC;
