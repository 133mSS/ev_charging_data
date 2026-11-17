-- JPL demand heatmap: day of week x local hour (America/Los_Angeles).
-- A row represents one charging session started in that weekday/hour bucket.
WITH weekdays AS (
    SELECT d::INTEGER AS day_of_week,
           CASE d
               WHEN 1 THEN 'Thứ Hai'
               WHEN 2 THEN 'Thứ Ba'
               WHEN 3 THEN 'Thứ Tư'
               WHEN 4 THEN 'Thứ Năm'
               WHEN 5 THEN 'Thứ Sáu'
               WHEN 6 THEN 'Thứ Bảy'
               ELSE 'Chủ Nhật'
           END AS weekday_name
    FROM generate_series(1, 7) AS series(d)
),
hours AS (
    SELECT generate_series(0, 23)::INTEGER AS local_hour
),
activity AS (
    SELECT
        d.day_of_week,
        t.hour AS local_hour,
        COUNT(*) AS session_count,
        SUM(f.energy_kwh) AS energy_kwh
    FROM warehouse.fact_charging_sessions f
    JOIN warehouse.dim_date d ON d.date_key = f.date_key
    JOIN warehouse.dim_time t ON t.time_key = f.time_key
    WHERE d.full_date >= CAST(:start_date AS DATE)
      AND d.full_date < CAST(:end_date_exclusive AS DATE)
    GROUP BY d.day_of_week, t.hour
)
SELECT
    w.day_of_week,
    w.weekday_name,
    h.local_hour,
    COALESCE(a.session_count, 0) AS session_count,
    COALESCE(a.energy_kwh, 0) AS energy_kwh
FROM weekdays w
CROSS JOIN hours h
LEFT JOIN activity a
    ON a.day_of_week = w.day_of_week
   AND a.local_hour = h.local_hour
ORDER BY w.day_of_week, h.local_hour;
