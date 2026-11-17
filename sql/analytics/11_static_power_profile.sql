-- 11_static_power_profile.sql
-- Phân tích công suất static theo giờ địa phương.
-- Chỉ tính các station có phép đo quan sát được.
-- Không giả định station thiếu dữ liệu có công suất bằng 0.

WITH station_minute AS (
    SELECT
        station_id,

        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        ) AS local_minute,

        AVG(power_kw) AS avg_power_kw,
        COUNT(*) AS measurement_count,
        COUNT(DISTINCT api_session_id) AS sessions_observed

    FROM warehouse.fact_static_measurements

    WHERE power_kw IS NOT NULL

    GROUP BY
        station_id,
        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        )
),

observed_site_minute AS (
    SELECT
        local_minute,

        SUM(avg_power_kw) AS observed_power_sum_kw,
        COUNT(DISTINCT station_id) AS stations_observed,
        SUM(measurement_count) AS measurement_count,
        SUM(sessions_observed) AS station_session_pairs

    FROM station_minute

    GROUP BY local_minute
)

SELECT
    EXTRACT(HOUR FROM local_minute)::INTEGER AS local_hour,

    COUNT(*) AS observed_minute_buckets,

    ROUND(
        AVG(observed_power_sum_kw)::NUMERIC,
        3
    ) AS avg_observed_power_kw,

    ROUND(
        PERCENTILE_CONT(
            0.95
        ) WITHIN GROUP (
            ORDER BY observed_power_sum_kw
        )::NUMERIC,
        3
    ) AS p95_observed_power_kw,

    ROUND(
        MAX(observed_power_sum_kw)::NUMERIC,
        3
    ) AS max_observed_power_kw,

    ROUND(
        AVG(stations_observed)::NUMERIC,
        2
    ) AS avg_stations_observed,

    MAX(stations_observed) AS max_stations_observed,

    SUM(measurement_count) AS total_measurements

FROM observed_site_minute

GROUP BY EXTRACT(HOUR FROM local_minute)::INTEGER

ORDER BY local_hour;
