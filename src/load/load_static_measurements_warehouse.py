import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[2]

SCHEMA_FILE = (
    ROOT / "sql" / "schema"
    / "04_warehouse_static_measurements.sql"
)

TIMEZONE = "America/Los_Angeles"


def main() -> None:
    load_dotenv(ROOT / ".env")

    required_env = [
        "DB_HOST",
        "DB_PORT",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing = [
        key for key in required_env
        if not os.getenv(key)
    ]

    if missing:
        raise RuntimeError(
            f"Missing database settings in .env: {missing}"
        )

    if not SCHEMA_FILE.exists():
        raise FileNotFoundError(SCHEMA_FILE)

    conn = psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )

    try:
        with conn:
            with conn.cursor() as cur:
                # 1. Tạo bảng fact nếu chưa tồn tại.
                cur.execute(
                    SCHEMA_FILE.read_text(encoding="utf-8")
                )

                # 2. Kiểm tra khóa tra cứu có duy nhất không.
                cur.execute("""
                    SELECT
                        EXISTS (
                            SELECT 1
                            FROM warehouse.fact_charging_sessions
                            GROUP BY session_id
                            HAVING COUNT(*) > 1
                        ),
                        EXISTS (
                            SELECT 1
                            FROM warehouse.dim_station
                            GROUP BY station_id
                            HAVING COUNT(*) > 1
                        ),
                        EXISTS (
                            SELECT 1
                            FROM warehouse.dim_date
                            GROUP BY full_date
                            HAVING COUNT(*) > 1
                        ),
                        EXISTS (
                            SELECT 1
                            FROM warehouse.dim_time
                            GROUP BY full_time
                            HAVING COUNT(*) > 1
                        );
                """)

                (
                    duplicate_sessions,
                    duplicate_stations,
                    duplicate_dates,
                    duplicate_times,
                ) = cur.fetchone()

                if any((
                    duplicate_sessions,
                    duplicate_stations,
                    duplicate_dates,
                    duplicate_times,
                )):
                    raise RuntimeError(
                        "Dimension/fact lookup keys are not unique. "
                        "Stop before loading."
                    )

                # 3. Kiểm tra khả năng ánh xạ tất cả phép đo.
                cur.execute(f"""
                    SELECT
                        COUNT(*) AS staging_rows,

                        COUNT(*) FILTER (
                            WHERE fs.session_id IS NULL
                        ) AS missing_sessions,

                        COUNT(*) FILTER (
                            WHERE ds.station_key IS NULL
                        ) AS missing_stations,

                        COUNT(*) FILTER (
                            WHERE dd.date_key IS NULL
                        ) AS missing_dates,

                        COUNT(*) FILTER (
                            WHERE dt.time_key IS NULL
                        ) AS missing_times

                    FROM staging.stg_static_measurements s

                    LEFT JOIN warehouse.fact_charging_sessions fs
                        ON fs.session_id = s.api_session_id

                    LEFT JOIN warehouse.dim_station ds
                        ON ds.station_id = s.station_id

                    LEFT JOIN warehouse.dim_date dd
                        ON dd.full_date = (
                            s.timestamp_utc
                            AT TIME ZONE '{TIMEZONE}'
                        )::date

                    LEFT JOIN warehouse.dim_time dt
                        ON dt.full_time = (
                            DATE_TRUNC(
                                'minute',
                                s.timestamp_utc
                                AT TIME ZONE '{TIMEZONE}'
                            )
                        )::time;
                """)

                (
                    staging_rows,
                    missing_sessions,
                    missing_stations,
                    missing_dates,
                    missing_times,
                ) = cur.fetchone()

                print("===== WAREHOUSE LOAD PREFLIGHT =====")
                print(f"Staging rows: {staging_rows:,}")
                print(f"Missing sessions: {missing_sessions:,}")
                print(f"Missing stations: {missing_stations:,}")
                print(f"Missing dates: {missing_dates:,}")
                print(f"Missing times: {missing_times:,}")

                if staging_rows <= 0:
                    raise RuntimeError("No staging static measurement rows found for JPL.")

                if any((
                    missing_sessions,
                    missing_stations,
                    missing_dates,
                    missing_times,
                )):
                    raise RuntimeError(
                        "Some staging rows cannot be mapped to "
                        "warehouse dimensions or sessions."
                    )

                # 4. Full refresh chỉ bảng fact static này.
                # Không thay đổi các bảng fact/dim khác trong warehouse.
                for index_name in [
                    "idx_static_fact_api_session",
                    "idx_static_fact_station_time",
                    "idx_static_fact_date_time",
                    "idx_static_fact_timestamp_brin",
                ]:
                    cur.execute(
                        f"DROP INDEX IF EXISTS warehouse.{index_name};"
                    )

                cur.execute("""
                    TRUNCATE TABLE
                        warehouse.fact_static_measurements
                    RESTART IDENTITY;
                """)

                # 5. Nạp bằng một câu INSERT ... SELECT ở PostgreSQL.
                cur.execute(f"""
                    INSERT INTO warehouse.fact_static_measurements (
                        static_session_id,
                        api_session_id,
                        site_id,
                        station_id,
                        station_key,
                        date_key,
                        time_key,
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
                    SELECT
                        s.static_session_id,
                        s.api_session_id,
                        s.site_id,
                        s.station_id,
                        ds.station_key,
                        dd.date_key,
                        dt.time_key,
                        s.timestamp_utc,
                        s.charging_current_a,
                        s.actual_pilot_a,
                        s.voltage_v,
                        s.charging_state,
                        s.energy_delivered_kwh,
                        s.power_kw,
                        s.energy_quality,
                        s.measurement_source

                    FROM staging.stg_static_measurements s

                    JOIN warehouse.fact_charging_sessions fs
                        ON fs.session_id = s.api_session_id

                    JOIN warehouse.dim_station ds
                        ON ds.station_id = s.station_id

                    JOIN warehouse.dim_date dd
                        ON dd.full_date = (
                            s.timestamp_utc
                            AT TIME ZONE '{TIMEZONE}'
                        )::date

                    JOIN warehouse.dim_time dt
                        ON dt.full_time = (
                            DATE_TRUNC(
                                'minute',
                                s.timestamp_utc
                                AT TIME ZONE '{TIMEZONE}'
                            )
                        )::time;
                """)

                inserted_rows = cur.rowcount

                # 6. Tạo index sau khi nạp số lượng lớn bản ghi.
                cur.execute("""
                    CREATE INDEX idx_static_fact_api_session
                    ON warehouse.fact_static_measurements (
                        api_session_id
                    );
                """)

                cur.execute("""
                    CREATE INDEX idx_static_fact_station_time
                    ON warehouse.fact_static_measurements (
                        station_key,
                        timestamp_utc
                    );
                """)

                cur.execute("""
                    CREATE INDEX idx_static_fact_date_time
                    ON warehouse.fact_static_measurements (
                        date_key,
                        time_key
                    );
                """)

                cur.execute("""
                    CREATE INDEX idx_static_fact_timestamp_brin
                    ON warehouse.fact_static_measurements
                    USING BRIN (timestamp_utc);
                """)

                # 7. Kiểm tra số lượng sau khi nạp.
                cur.execute("""
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
                    FROM warehouse.fact_static_measurements;
                """)

                (
                    fact_rows,
                    static_sessions,
                    api_sessions,
                    voltage_rows,
                    power_rows,
                ) = cur.fetchone()

                print("\n===== STATIC FACT LOAD REPORT =====")
                print(f"Rows inserted: {inserted_rows:,}")
                print(f"Rows in fact: {fact_rows:,}")
                print(f"Static sessions: {static_sessions:,}")
                print(f"API sessions: {api_sessions:,}")
                print(f"Rows with voltage: {voltage_rows:,}")
                print(f"Rows with power: {power_rows:,}")

                cur.execute("""
                    SELECT
                        energy_quality,
                        COUNT(DISTINCT api_session_id)
                    FROM warehouse.fact_static_measurements
                    GROUP BY energy_quality
                    ORDER BY energy_quality;
                """)

                print("\nEnergy quality by session:")
                for quality, count in cur.fetchall():
                    print(f"{quality}: {count:,}")

                if inserted_rows != staging_rows or fact_rows != staging_rows:
                    raise RuntimeError(
                        f"Fact/staging row counts differ: staging={staging_rows:,}, inserted={inserted_rows:,}, fact={fact_rows:,}."
                    )
                if static_sessions <= 0 or api_sessions <= 0 or static_sessions != api_sessions:
                    raise RuntimeError(
                        f"Matched session counts are inconsistent: static={static_sessions:,}, API={api_sessions:,}."
                    )

                cur.execute("""
                    ANALYZE warehouse.fact_static_measurements;
                """)

        print("\nSTATIC MEASUREMENT WAREHOUSE LOAD COMPLETED.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
