CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.stg_static_measurements (
    measurement_id BIGSERIAL PRIMARY KEY,

    site_id VARCHAR(100),
    station_id VARCHAR(100) NOT NULL,

    static_session_id VARCHAR(200) NOT NULL,
    api_session_id VARCHAR(200) NOT NULL,

    timestamp_utc TIMESTAMPTZ NOT NULL,

    charging_current_a DOUBLE PRECISION,
    actual_pilot_a DOUBLE PRECISION,
    voltage_v DOUBLE PRECISION,

    charging_state VARCHAR(50),
    energy_delivered_kwh DOUBLE PRECISION,
    power_kw DOUBLE PRECISION,

    energy_quality VARCHAR(30) NOT NULL,
    measurement_source VARCHAR(30) NOT NULL
);

COMMENT ON TABLE staging.stg_static_measurements IS
'Static ACN-Data measurements linked to API sessions; one row per source measurement.';

COMMENT ON COLUMN staging.stg_static_measurements.api_session_id IS
'Normalized API session identifier used to link measurements with session metadata.';

COMMENT ON COLUMN staging.stg_static_measurements.energy_quality IS
'Session-level energy consistency label; not a complete measurement-quality guarantee.';
