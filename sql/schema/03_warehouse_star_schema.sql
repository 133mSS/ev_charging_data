CREATE SCHEMA IF NOT EXISTS warehouse;


-- =========================================================
-- 1. DIM DATE
-- Grain: 1 row = 1 calendar date
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,

    day INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    day_name VARCHAR(20) NOT NULL,

    week_of_year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name VARCHAR(20) NOT NULL,

    quarter INTEGER NOT NULL,
    year INTEGER NOT NULL
);


-- =========================================================
-- 2. DIM TIME
-- Grain: 1 row = 1 minute of a day
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.dim_time (
    time_key INTEGER PRIMARY KEY,
    full_time TIME NOT NULL UNIQUE,

    hour INTEGER NOT NULL,
    minute INTEGER NOT NULL,

    time_of_day VARCHAR(20) NOT NULL
);


-- =========================================================
-- 3. DIM STATION
-- Grain: 1 row = 1 charging station
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.dim_station (
    station_key SERIAL PRIMARY KEY,

    station_id VARCHAR(50) NOT NULL UNIQUE,
    space_id VARCHAR(50),
    site_id VARCHAR(50) NOT NULL,
    cluster_id VARCHAR(50)
);


-- =========================================================
-- 4. DIM USER
-- Grain: 1 row = 1 identified user
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.dim_user (
    user_key SERIAL PRIMARY KEY,

    user_id VARCHAR(20) UNIQUE,
    user_type VARCHAR(20) NOT NULL
);

-- =========================================================
-- 5. FACT CHARGING SESSIONS
-- Grain: 1 row = 1 charging session
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.fact_charging_sessions (
    session_key BIGSERIAL PRIMARY KEY,

    session_id VARCHAR(100) NOT NULL UNIQUE,

    date_key INTEGER NOT NULL,
    time_key INTEGER NOT NULL,
    station_key INTEGER NOT NULL,
    user_key INTEGER NOT NULL,

    energy_kwh NUMERIC(10,3) NOT NULL,
    connection_duration_minutes NUMERIC(12,3) NOT NULL,
    avg_power_kw NUMERIC(12,3),

    -- Timestamp cuối cùng ghi nhận dòng điện khác 0 theo ACN-Data.
    done_charging_time TIMESTAMPTZ,
    -- Khoảng xe còn kết nối sau done_charging_time (phút), chỉ tính khi mốc thời gian hợp lệ.
    post_charge_connection_minutes NUMERIC(12,3),

    has_user_metadata BOOLEAN NOT NULL,
    done_after_disconnect BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT fk_fact_session_date
        FOREIGN KEY (date_key)
        REFERENCES warehouse.dim_date(date_key),

    CONSTRAINT fk_fact_session_time
        FOREIGN KEY (time_key)
        REFERENCES warehouse.dim_time(time_key),

    CONSTRAINT fk_fact_session_station
        FOREIGN KEY (station_key)
        REFERENCES warehouse.dim_station(station_key),

    CONSTRAINT fk_fact_session_user
        FOREIGN KEY (user_key)
        REFERENCES warehouse.dim_user(user_key)
);


-- Migration an toàn cho database đã được tạo từ phiên bản schema trước.
ALTER TABLE warehouse.fact_charging_sessions
    ADD COLUMN IF NOT EXISTS done_charging_time TIMESTAMPTZ;

ALTER TABLE warehouse.fact_charging_sessions
    ADD COLUMN IF NOT EXISTS post_charge_connection_minutes NUMERIC(12,3);

-- =========================================================
-- 6. FACT USER REQUESTS
-- Grain: 1 row = 1 user input within a charging session
-- =========================================================

CREATE TABLE IF NOT EXISTS warehouse.fact_user_requests (
    request_key BIGSERIAL PRIMARY KEY,

    session_id VARCHAR(100) NOT NULL,
    input_id INTEGER NOT NULL,

    date_key INTEGER NOT NULL,
    time_key INTEGER NOT NULL,
    user_key INTEGER NOT NULL,

    miles_requested NUMERIC(12,3),
    wh_per_mile NUMERIC(12,3),
    minutes_available NUMERIC(12,3),
    kwh_requested NUMERIC(10,3),

    modified_at TIMESTAMPTZ NOT NULL,
    requested_departure TIMESTAMPTZ,

    payment_required BOOLEAN,
    departure_before_modified BOOLEAN NOT NULL DEFAULT FALSE,

    CONSTRAINT uq_fact_user_request
        UNIQUE (session_id, input_id),

    CONSTRAINT fk_fact_request_date
        FOREIGN KEY (date_key)
        REFERENCES warehouse.dim_date(date_key),

    CONSTRAINT fk_fact_request_time
        FOREIGN KEY (time_key)
        REFERENCES warehouse.dim_time(time_key),

    CONSTRAINT fk_fact_request_user
        FOREIGN KEY (user_key)
        REFERENCES warehouse.dim_user(user_key)
);
CREATE INDEX IF NOT EXISTS idx_fact_user_requests_latest
    ON warehouse.fact_user_requests (session_id, modified_at DESC, input_id DESC);


-- Keep optional ACN metadata nullable across reruns/migrations.
ALTER TABLE warehouse.dim_station ALTER COLUMN space_id DROP NOT NULL;
ALTER TABLE warehouse.dim_station ALTER COLUMN cluster_id DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN miles_requested DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN wh_per_mile DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN minutes_available DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN kwh_requested DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN requested_departure DROP NOT NULL;
ALTER TABLE warehouse.fact_user_requests ALTER COLUMN payment_required DROP NOT NULL;

ALTER TABLE warehouse.fact_charging_sessions ALTER COLUMN avg_power_kw DROP NOT NULL;
