from pathlib import Path
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_database_url() -> str:
    load_dotenv(PROJECT_ROOT / ".env")

    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT")
    database = os.getenv("DB_NAME")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")

    required = {
        "DB_HOST": host,
        "DB_PORT": port,
        "DB_NAME": database,
        "DB_USER": user,
        "DB_PASSWORD": password,
    }

    missing = [key for key, value in required.items() if not value]

    if missing:
        raise RuntimeError(
            f"Missing database environment variables: {', '.join(missing)}"
        )

    return (
        f"postgresql+psycopg2://{user}:{password}"
        f"@{host}:{port}/{database}"
    )


# =========================================================
# 1. DIM STATION
# =========================================================

def load_dim_station(connection) -> None:
    print("===== LOADING DIM STATION =====")

    connection.execute(text("""
        INSERT INTO warehouse.dim_station (
            station_id,
            space_id,
            site_id,
            cluster_id
        )
        SELECT DISTINCT
            station_id,
            space_id,
            site_id,
            cluster_id
        FROM staging.stg_charging_sessions
        ON CONFLICT (station_id) DO NOTHING;
    """))

    print("DIM STATION loaded.")


# =========================================================
# 2. DIM USER
# =========================================================

def load_dim_user(connection) -> None:
    print("===== LOADING DIM USER =====")

    # Unknown / anonymous user
    connection.execute(text("""
        INSERT INTO warehouse.dim_user (
            user_key,
            user_id,
            user_type
        )
        VALUES (
            0,
            NULL,
            'Unknown'
        )
        ON CONFLICT (user_key) DO NOTHING;
    """))

    # Identified users
    connection.execute(text("""
        INSERT INTO warehouse.dim_user (
            user_id,
            user_type
        )
        SELECT DISTINCT
            user_id,
            'Identified'
        FROM staging.stg_charging_sessions
        WHERE user_id IS NOT NULL
        ON CONFLICT (user_id) DO NOTHING;
    """))

    print("DIM USER loaded.")


# =========================================================
# 3. DIM DATE
# =========================================================

def load_dim_date(connection) -> None:
    print("===== LOADING DIM DATE =====")

    connection.execute(text("""
        INSERT INTO warehouse.dim_date (
            date_key,
            full_date,
            day,
            day_of_week,
            day_name,
            week_of_year,
            month,
            month_name,
            quarter,
            year
        )
        SELECT
            TO_CHAR(d, 'YYYYMMDD')::INTEGER AS date_key,
            d::DATE AS full_date,
            EXTRACT(DAY FROM d)::INTEGER AS day,
            EXTRACT(ISODOW FROM d)::INTEGER AS day_of_week,
            TO_CHAR(d, 'Day') AS day_name,
            EXTRACT(WEEK FROM d)::INTEGER AS week_of_year,
            EXTRACT(MONTH FROM d)::INTEGER AS month,
            TO_CHAR(d, 'Month') AS month_name,
            EXTRACT(QUARTER FROM d)::INTEGER AS quarter,
            EXTRACT(YEAR FROM d)::INTEGER AS year
        FROM generate_series(
            (
                SELECT MIN(
                    connection_time AT TIME ZONE 'America/Los_Angeles'
                )::DATE
                FROM staging.stg_charging_sessions
            ),
            (
                SELECT MAX(
                    disconnect_time AT TIME ZONE 'America/Los_Angeles'
                )::DATE
                FROM staging.stg_charging_sessions
            ),
            INTERVAL '1 day'
        ) AS d
        ON CONFLICT (date_key) DO NOTHING;
    """))

    print("DIM DATE loaded.")


# =========================================================
# 4. DIM TIME
# Grain: 1 row = 1 minute
# =========================================================

def load_dim_time(connection) -> None:
    print("===== LOADING DIM TIME =====")

    connection.execute(text("""
        INSERT INTO warehouse.dim_time (
            time_key,
            full_time,
            hour,
            minute,
            time_of_day
        )
        SELECT
            (EXTRACT(HOUR FROM t)::INTEGER * 100)
                + EXTRACT(MINUTE FROM t)::INTEGER AS time_key,
            t::TIME AS full_time,
            EXTRACT(HOUR FROM t)::INTEGER AS hour,
            EXTRACT(MINUTE FROM t)::INTEGER AS minute,
            CASE
                WHEN EXTRACT(HOUR FROM t) < 6
                    THEN 'Night'
                WHEN EXTRACT(HOUR FROM t) < 12
                    THEN 'Morning'
                WHEN EXTRACT(HOUR FROM t) < 18
                    THEN 'Afternoon'
                ELSE 'Evening'
            END AS time_of_day
        FROM generate_series(
            TIMESTAMP '2000-01-01 00:00:00',
            TIMESTAMP '2000-01-01 23:59:00',
            INTERVAL '1 minute'
        ) AS t
        ON CONFLICT (time_key) DO NOTHING;
    """))

    print("DIM TIME loaded.")


# =========================================================
# 5. FACT CHARGING SESSIONS
# =========================================================

def load_fact_charging_sessions(connection) -> None:
    print("===== LOADING FACT CHARGING SESSIONS =====")

    connection.execute(text("""
        INSERT INTO warehouse.fact_charging_sessions (
            session_id,
            date_key,
            time_key,
            station_key,
            user_key,
            energy_kwh,
            connection_duration_minutes,
            avg_power_kw,
            done_charging_time,
            post_charge_connection_minutes,
            has_user_metadata,
            done_after_disconnect
        )
        SELECT
            s.session_id,

            TO_CHAR(
                s.connection_time AT TIME ZONE s.timezone,
                'YYYYMMDD'
            )::INTEGER AS date_key,

            (
                EXTRACT(
                    HOUR FROM (
                        s.connection_time AT TIME ZONE s.timezone
                    )
                )::INTEGER * 100
                +
                EXTRACT(
                    MINUTE FROM (
                        s.connection_time AT TIME ZONE s.timezone
                    )
                )::INTEGER
            ) AS time_key,

            ds.station_key,

            COALESCE(du.user_key, 0) AS user_key,

            s.energy_kwh,
            s.connection_duration_minutes,

            ROUND(
                (
                    s.energy_kwh
                    / NULLIF(
                        s.connection_duration_minutes / 60.0,
                        0
                    )
                )::NUMERIC,
                3
            ) AS avg_power_kw,

            s.done_charging_time,
            CASE
                WHEN s.done_charging_time IS NOT NULL
                 AND s.done_charging_time >= s.connection_time
                 AND s.done_charging_time <= s.disconnect_time
                THEN ROUND(
                    (
                        EXTRACT(
                            EPOCH FROM (s.disconnect_time - s.done_charging_time)
                        ) / 60.0
                    )::NUMERIC,
                    3
                )
                ELSE NULL
            END AS post_charge_connection_minutes,

            s.has_user_metadata,
            s.done_after_disconnect

        FROM staging.stg_charging_sessions s

        JOIN warehouse.dim_station ds
            ON ds.station_id = s.station_id

        LEFT JOIN warehouse.dim_user du
            ON du.user_id = s.user_id

        ON CONFLICT (session_id) DO UPDATE SET
            date_key = EXCLUDED.date_key,
            time_key = EXCLUDED.time_key,
            station_key = EXCLUDED.station_key,
            user_key = EXCLUDED.user_key,
            energy_kwh = EXCLUDED.energy_kwh,
            connection_duration_minutes = EXCLUDED.connection_duration_minutes,
            avg_power_kw = EXCLUDED.avg_power_kw,
            done_charging_time = EXCLUDED.done_charging_time,
            post_charge_connection_minutes = EXCLUDED.post_charge_connection_minutes,
            has_user_metadata = EXCLUDED.has_user_metadata,
            done_after_disconnect = EXCLUDED.done_after_disconnect;
    """))

    print("FACT CHARGING SESSIONS loaded.")


# =========================================================
# 6. FACT USER REQUESTS
# =========================================================

def load_fact_user_requests(connection) -> None:
    print("===== LOADING FACT USER REQUESTS =====")

    connection.execute(text("""
        INSERT INTO warehouse.fact_user_requests (
            session_id,
            input_id,
            date_key,
            time_key,
            user_key,
            miles_requested,
            wh_per_mile,
            minutes_available,
            kwh_requested,
            modified_at,
            requested_departure,
            payment_required,
            departure_before_modified
        )
        SELECT
            u.session_id,
            u.input_id,

            TO_CHAR(
                u.modified_at AT TIME ZONE s.timezone,
                'YYYYMMDD'
            )::INTEGER AS date_key,

            (
                EXTRACT(
                    HOUR FROM (
                        u.modified_at AT TIME ZONE s.timezone
                    )
                )::INTEGER * 100
                +
                EXTRACT(
                    MINUTE FROM (
                        u.modified_at AT TIME ZONE s.timezone
                    )
                )::INTEGER
            ) AS time_key,

            COALESCE(du.user_key, 0) AS user_key,

            u.miles_requested,
            u.wh_per_mile,
            u.minutes_available,
            u.kwh_requested,
            u.modified_at,
            u.requested_departure,
            u.payment_required,
            u.departure_before_modified

        FROM staging.stg_user_inputs u

        JOIN staging.stg_charging_sessions s
            ON s.session_id = u.session_id

        LEFT JOIN warehouse.dim_user du
            ON du.user_id = u.user_id

        WHERE u.modified_at IS NOT NULL

        ON CONFLICT (session_id, input_id) DO UPDATE SET
            user_key = EXCLUDED.user_key,
            miles_requested = EXCLUDED.miles_requested,
            wh_per_mile = EXCLUDED.wh_per_mile,
            minutes_available = EXCLUDED.minutes_available,
            kwh_requested = EXCLUDED.kwh_requested,
            modified_at = EXCLUDED.modified_at,
            requested_departure = EXCLUDED.requested_departure,
            payment_required = EXCLUDED.payment_required,
            departure_before_modified = EXCLUDED.departure_before_modified;
    """))

    print("FACT USER REQUESTS loaded.")


# =========================================================
# MAIN ETL
# =========================================================

def main() -> None:
    print("========================================")
    print("WAREHOUSE ETL STARTED")
    print("========================================")

    engine = create_engine(get_database_url())

    with engine.begin() as connection:
        load_dim_station(connection)
        load_dim_user(connection)
        load_dim_date(connection)
        load_dim_time(connection)
        load_fact_charging_sessions(connection)
        load_fact_user_requests(connection)

    print("\n========================================")
    print("WAREHOUSE ETL COMPLETED")
    print("========================================")


if __name__ == "__main__":
    main()