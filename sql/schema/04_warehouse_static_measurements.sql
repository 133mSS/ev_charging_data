CREATE SCHEMA IF NOT EXISTS warehouse;

CREATE TABLE IF NOT EXISTS warehouse.fact_static_measurements (
    static_measurement_key BIGSERIAL PRIMARY KEY,

    static_session_id VARCHAR(200) NOT NULL,
    api_session_id VARCHAR(200) NOT NULL,

    site_id VARCHAR(100),
    station_id VARCHAR(100) NOT NULL,
    station_key INTEGER NOT NULL,

    date_key INTEGER NOT NULL,
    time_key INTEGER NOT NULL,
    timestamp_utc TIMESTAMPTZ NOT NULL,

    charging_current_a DOUBLE PRECISION,
    actual_pilot_a DOUBLE PRECISION,
    voltage_v DOUBLE PRECISION,
    charging_state VARCHAR(50),

    energy_delivered_kwh DOUBLE PRECISION,
    power_kw DOUBLE PRECISION,

    energy_quality VARCHAR(30) NOT NULL,
    measurement_source VARCHAR(30) NOT NULL,

    CONSTRAINT fk_static_measurement_session
        FOREIGN KEY (api_session_id)
        REFERENCES warehouse.fact_charging_sessions(session_id),

    CONSTRAINT fk_static_measurement_station
        FOREIGN KEY (station_key)
        REFERENCES warehouse.dim_station(station_key),

    CONSTRAINT fk_static_measurement_date
        FOREIGN KEY (date_key)
        REFERENCES warehouse.dim_date(date_key),

    CONSTRAINT fk_static_measurement_time
        FOREIGN KEY (time_key)
        REFERENCES warehouse.dim_time(time_key)
);

COMMENT ON TABLE warehouse.fact_static_measurements IS
'Time-series measurements from ACN-Data Static, linked to API sessions.';

COMMENT ON COLUMN warehouse.fact_static_measurements.timestamp_utc IS
'Original measurement timestamp in UTC.';

COMMENT ON COLUMN warehouse.fact_static_measurements.energy_quality IS
'Session-level energy consistency label; not a guarantee of sensor accuracy.';

COMMENT ON COLUMN warehouse.fact_static_measurements.energy_delivered_kwh IS
'Cumulative static energy measurement; may reset when unplugged.';
