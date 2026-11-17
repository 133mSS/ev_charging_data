-- 24_requested_vs_delivered.sql
-- Chọn bản user input cập nhật gần nhất của mỗi phiên để tránh đếm lặp các lần thay đổi.
-- So sánh mô tả kWhDelivered của phiên với kWhRequested cuối cùng được ghi nhận.

WITH latest_request AS (
    SELECT DISTINCT ON (r.session_id)
        r.session_id,
        r.input_id,
        r.kwh_requested,
        r.modified_at,
        r.minutes_available,
        r.requested_departure
    FROM warehouse.fact_user_requests r
    WHERE r.kwh_requested > 0
    ORDER BY
        r.session_id,
        r.modified_at DESC,
        r.input_id DESC
)
SELECT
    f.session_id,
    ds.station_id,
    d.full_date,
    f.energy_kwh AS delivered_kwh,
    lr.kwh_requested,
    ROUND(
        100.0 * f.energy_kwh / NULLIF(lr.kwh_requested, 0),
        2
    ) AS delivered_vs_requested_pct,
    ROUND(f.energy_kwh - lr.kwh_requested, 3) AS energy_gap_kwh,
    lr.modified_at AS request_modified_at,
    lr.minutes_available,
    lr.requested_departure,
    f.connection_duration_minutes
FROM warehouse.fact_charging_sessions f
JOIN latest_request lr
    ON lr.session_id = f.session_id
JOIN warehouse.dim_station ds
    ON ds.station_key = f.station_key
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key
WHERE d.full_date >= CAST(:start_date AS DATE)
  AND d.full_date < CAST(:end_date_exclusive AS DATE)
ORDER BY f.energy_kwh / NULLIF(lr.kwh_requested, 0);
