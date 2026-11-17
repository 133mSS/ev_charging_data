import gzip
import os
from pathlib import Path

import psycopg2
import pandas as pd
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from project_config import MATCHED_STATIC_FILE as INPUT_FILE



SCHEMA_FILE = (
    ROOT
    / "sql"
    / "schema"
    / "02_staging_static_measurements.sql"
)


COPY_SQL = """
COPY staging.stg_static_measurements (
    site_id,
    station_id,
    static_session_id,
    api_session_id,
    timestamp_utc,
    charging_current_a,
    actual_pilot_a,
    voltage_v,
    charging_state,
    energy_delivered_kwh,
    power_kw,
    energy_quality,
    measurement_source
)
FROM STDIN
WITH (
    FORMAT CSV,
    HEADER TRUE,
    NULL ''
);
"""


def main() -> None:
    if not INPUT_FILE.exists():
        raise FileNotFoundError(INPUT_FILE)

    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(SCHEMA_FILE)

    load_dotenv(ROOT / ".env")

    required_env = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing_env = [
        key for key in required_env
        if not os.getenv(key)
    ]

    if missing_env:
        raise RuntimeError(
            f"Missing database settings in .env: {missing_env}"
        )

    connection = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

    try:
        with connection:
            with connection.cursor() as cursor:
                # Tạo schema và bảng nếu chưa tồn tại.
                cursor.execute(
                    SCHEMA_FILE.read_text(encoding="utf-8")
                )

                # Loader là full refresh cho bảng staging này.
                cursor.execute(
                    """
                    TRUNCATE TABLE staging.stg_static_measurements
                    RESTART IDENTITY;
                    """
                )

                print("Loading static measurements with COPY...")

                with gzip.open(
                    INPUT_FILE,
                    "rt",
                    encoding="utf-8",
                    newline="",
                ) as file:
                    cursor.copy_expert(
                        COPY_SQL,
                        file,
                        size=1024 * 1024,
                    )

                # Tạo index sau khi nạp bulk.
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS
                        idx_stg_static_api_session
                    ON staging.stg_static_measurements (api_session_id);
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS
                        idx_stg_static_station_time
                    ON staging.stg_static_measurements
                        (station_id, timestamp_utc);
                """)

                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS
                        idx_stg_static_timestamp_brin
                    ON staging.stg_static_measurements
                    USING BRIN (timestamp_utc);
                """)

                cursor.execute("""
                    SELECT
                        COUNT(*),
                        COUNT(DISTINCT static_session_id),
                        COUNT(DISTINCT api_session_id),
                        COUNT(*) FILTER (
                            WHERE voltage_v IS NOT NULL
                        ),
                        COUNT(*) FILTER (
                            WHERE power_kw IS NOT NULL
                        )
                    FROM staging.stg_static_measurements;
                """)

                (
                    row_count,
                    static_sessions,
                    api_sessions,
                    voltage_count,
                    power_count,
                ) = cursor.fetchone()

                print("\n===== STAGING LOAD REPORT =====")
                print(f"Rows loaded: {row_count:,}")
                print(f"Static sessions: {static_sessions:,}")
                print(f"API sessions: {api_sessions:,}")
                print(f"Rows with voltage: {voltage_count:,}")
                print(f"Rows with power: {power_count:,}")

                cursor.execute("""
                    SELECT energy_quality, COUNT(DISTINCT api_session_id)
                    FROM staging.stg_static_measurements
                    GROUP BY energy_quality
                    ORDER BY energy_quality;
                """)

                print("\nSession quality labels:")
                for quality, count in cursor.fetchall():
                    print(f"{quality}: {count:,}")

                if row_count <= 0 or static_sessions <= 0 or api_sessions <= 0:
                    raise RuntimeError("JPL matched measurements are empty; check API/static session matching.")
                if static_sessions != api_sessions:
                    raise RuntimeError(
                        f"One-to-one mapping expected for matched sessions; static={static_sessions:,}, API={api_sessions:,}."
                    )

        print("\nSTAGING LOAD COMPLETED.")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
