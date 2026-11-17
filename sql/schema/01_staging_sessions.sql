CREATE SCHEMA IF NOT EXISTS staging;


-- =========================================================
-- 1. CHARGING SESSIONS
-- Grain: 1 row = 1 charging session
-- =========================================================

CREATE TABLE IF NOT EXISTS staging.stg_charging_sessions (
    record_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) PRIMARY KEY,
    user_id VARCHAR(20),
    station_id VARCHAR(50) NOT NULL,
    space_id VARCHAR(50),
    site_id VARCHAR(50) NOT NULL,
    cluster_id VARCHAR(50),

    connection_time TIMESTAMPTZ NOT NULL,
    disconnect_time TIMESTAMPTZ NOT NULL,
    done_charging_time TIMESTAMPTZ,

    energy_kwh NUMERIC(10,3) NOT NULL,
    timezone VARCHAR(50) NOT NULL,
    has_user_metadata BOOLEAN NOT NULL,

    connection_duration_minutes NUMERIC(12,3) NOT NULL,
    done_after_disconnect BOOLEAN NOT NULL DEFAULT FALSE
);


-- =========================================================
-- 2. USER INPUTS
-- Grain: 1 row = 1 user request/input within a session
-- =========================================================

CREATE TABLE IF NOT EXISTS staging.stg_user_inputs (
    session_id VARCHAR(100) NOT NULL,
    input_id INTEGER NOT NULL,

    user_id VARCHAR(50),

    miles_requested NUMERIC(12,3),
    wh_per_mile NUMERIC(12,3),
    minutes_available NUMERIC(12,3),

    modified_at TIMESTAMPTZ,
    payment_required BOOLEAN,

    requested_departure TIMESTAMPTZ,
    kwh_requested NUMERIC(10,3),

    departure_before_modified BOOLEAN NOT NULL DEFAULT FALSE,

    PRIMARY KEY (session_id, input_id),

    CONSTRAINT fk_user_inputs_session
        FOREIGN KEY (session_id)
        REFERENCES staging.stg_charging_sessions(session_id)
);


-- =========================================================
-- INDEXES
-- =========================================================

CREATE INDEX IF NOT EXISTS idx_sessions_station
    ON staging.stg_charging_sessions(station_id);

CREATE INDEX IF NOT EXISTS idx_sessions_connection_time
    ON staging.stg_charging_sessions(connection_time);

CREATE INDEX IF NOT EXISTS idx_sessions_user
    ON staging.stg_charging_sessions(user_id);

CREATE INDEX IF NOT EXISTS idx_user_inputs_user
    ON staging.stg_user_inputs(user_id);

CREATE INDEX IF NOT EXISTS idx_user_inputs_modified
    ON staging.stg_user_inputs(modified_at);


-- Safe migrations for nullable/optional ACN metadata on an existing database.
ALTER TABLE staging.stg_charging_sessions ALTER COLUMN space_id DROP NOT NULL;
ALTER TABLE staging.stg_charging_sessions ALTER COLUMN cluster_id DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN user_id DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN miles_requested DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN wh_per_mile DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN minutes_available DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN modified_at DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN payment_required DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN requested_departure DROP NOT NULL;
ALTER TABLE staging.stg_user_inputs ALTER COLUMN kwh_requested DROP NOT NULL;
