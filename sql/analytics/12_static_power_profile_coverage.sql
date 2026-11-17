WITH station_minute AS (
    SELECT
        station_id,
        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        ) AS local_minute,
        AVG(power_kw) AS avg_power_kw
    FROM warehouse.fact_static_measurements
    WHERE power_kw IS NOT NULL
    GROUP BY
        station_id,
        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        )
),

site_minute AS (
    SELECT
        local_minute,
        SUM(avg_power_kw) AS observed_power_sum_kw,
        COUNT(DISTINCT station_id) AS stations_observed
    FROM station_minute
    GROUP BY local_minute
),

expected AS (
    SELECT COUNT(*) AS expected_stations
    FROM warehouse.dim_station
)

SELECT
    EXTRACT(HOUR FROM local_minute)::INTEGER AS local_hour,

    COUNT(*) AS observed_minute_buckets,

    COUNT(*) FILTER (
        WHERE stations_observed = expected_stations
    ) AS full_coverage_minute_buckets,

    ROUND(
        AVG(observed_power_sum_kw)::NUMERIC,
        3
    ) AS avg_partial_coverage_kw,

    ROUND(
        AVG(observed_power_sum_kw) FILTER (
            WHERE stations_observed = expected_stations
        )::NUMERIC,
        3
    ) AS avg_full_coverage_kw,

    ROUND(
        PERCENTILE_CONT(0.95)
        WITHIN GROUP (ORDER BY observed_power_sum_kw)
        FILTER (
            WHERE stations_observed = expected_stations
        )::NUMERIC,
        3
    ) AS p95_full_coverage_kw,

    ROUND(
        MAX(observed_power_sum_kw) FILTER (
            WHERE stations_observed = expected_stations
        )::NUMERIC,
        3
    ) AS max_full_coverage_kw

FROM site_minute
CROSS JOIN expected

GROUP BY
    EXTRACT(HOUR FROM local_minute)::INTEGER,
    expected_stations

ORDER BY local_hour;
