from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class TestSnowflakeMigrationAssets(unittest.TestCase):
    def test_bootstrap_uses_small_auto_suspending_warehouse(self):
        sql = read("snowflake/00_bootstrap.sql")
        self.assertIn("WAREHOUSE_SIZE = 'XSMALL'", sql)
        self.assertIn("AUTO_SUSPEND = 60", sql)
        self.assertIn("INITIALLY_SUSPENDED = TRUE", sql)
        self.assertIn("JPL_RAW_STAGE", sql)

    def test_raw_static_landing_table_has_expected_source_columns(self):
        sql = read("snowflake/01_raw_staging.sql")
        for column in [
            "SITE_ID", "STATION_ID", "SESSION_ID", "TIMESTAMP_UTC",
            "CHARGING_CURRENT_A", "ACTUAL_PILOT_A", "VOLTAGE_V",
            "CHARGING_STATE", "ENERGY_DELIVERED_KWH", "POWER_KW",
        ]:
            self.assertIn(column, sql)

    def test_full_static_warehouse_object_is_a_view_and_keeps_unmatched_rows(self):
        sql = read("snowflake/02_warehouse.sql")
        self.assertIn("CREATE OR REPLACE VIEW WAREHOUSE.FACT_STATIC_MEASUREMENTS", sql)
        self.assertIn("LEFT JOIN RAW.STG_SESSION_MAPPING", sql)
        self.assertIn("UNMAPPED_STATIC", sql)
        self.assertNotIn("CREATE OR REPLACE TABLE WAREHOUSE.FACT_STATIC_MEASUREMENTS", sql)

    def test_power_site_hour_uses_complete_gap_free_utc_calendar(self):
        sql = read("snowflake/03_power_marts.sql")
        self.assertIn("ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS HOUR_OFFSET", sql)
        self.assertIn("CREATE OR REPLACE TABLE MART.POWER_SITE_HOUR", sql)
        self.assertIn("LEFT JOIN AGG A USING (UTC_HOUR_START)", sql)
        self.assertIn("STATION_SCOPE", sql)
        self.assertIn("SITE_HOUR_HAS_ANY_OBSERVATION", sql)
        self.assertIn("'2020-07-01 00:00:00'", sql)
        self.assertIn("'2020-12-01 00:00:00'", sql)

    def test_q1_calendar_uses_gap_free_day_sequence_and_no_invalid_qualify(self):
        app = read("snowflake/streamlit_app.py")
        q1 = app[app.index("# Q1"):app.index("# Q2")]
        self.assertIn("ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS DAY_OFFSET", q1)
        self.assertIn("AVG_SESSIONS_PER_DAY", q1)
        self.assertNotIn("QUALIFY LOCAL_DATE", q1)

    def test_q3_last_current_sample_is_within_api_connection_interval(self):
        sql = read("snowflake/03_power_marts.sql")
        view_sql = sql[sql.index("CREATE OR REPLACE VIEW MART.SESSION_POST_CURRENT"):]
        self.assertIn("L.LAST_NONZERO_CURRENT_UTC >= F.CONNECTION_TIME_UTC", view_sql)
        self.assertIn("L.LAST_NONZERO_CURRENT_UTC <= F.DISCONNECT_TIME_UTC", view_sql)

    def test_q5_uses_the_selected_date_range_for_each_power_visual(self):
        app = read("snowflake/streamlit_app.py")
        q5 = app[app.index("# Q5"):]
        self.assertGreaterEqual(
            q5.count("WHERE LOCAL_MONTH >= TO_DATE(?) AND LOCAL_MONTH < TO_DATE(?)"),
            3,
        )
        self.assertIn("WHERE LOCAL_DATE >= TO_DATE(?) AND LOCAL_DATE < TO_DATE(?)", q5)

    def test_q4_selects_latest_request_before_filtering_positive_kwh(self):
        app = read("snowflake/streamlit_app.py")
        q4 = app[app.index("# Q4"):app.index("# Q5")]
        self.assertIn("QUALIFY ROW_NUMBER()", q4)
        self.assertLess(q4.index("QUALIFY ROW_NUMBER()"), q4.index("L.KWH_REQUESTED > 0"))

    def test_streamlit_uses_snowflake_active_session_not_local_postgres(self):
        app = read("snowflake/streamlit_app.py")
        self.assertIn("get_active_session", app)
        self.assertNotIn("import psycopg2", app)
        self.assertNotIn("from psycopg2", app)
        self.assertNotIn("DB_PASSWORD", app)

    def test_deployment_uses_put_and_copy_into_without_secrets_in_source(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn("SNOWFLAKE_ACCOUNT", script)
        self.assertIn("SNOWFLAKE_USER", script)
        self.assertIn("SNOWFLAKE_PASSWORD", script)
        self.assertIn("PUT ", script)
        self.assertIn("COPY INTO", script)
        self.assertNotIn("password = '", script.lower())

    def test_sql_runner_calls_execute_string_on_connection_not_cursor(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn("connection.execute_string(", script)
        self.assertNotIn("cursor.execute_string(", script)

    def test_first_login_does_not_require_database_or_warehouse_to_exist(self):
        script = read("scripts/deploy_snowflake.py")
        start = script.index("    kwargs = {")
        end = script.index("    }", start)
        connection_kwargs = script[start:end]
        self.assertNotIn('"warehouse"', connection_kwargs)
        self.assertNotIn('"database"', connection_kwargs)
        self.assertIn('run_sql_file(connection, "snowflake/00_bootstrap.sql")', script)

    def test_windows_wrapper_keeps_environment_and_temp_files_off_project_drive(self):
        script = read("scripts/run_snowflake_deploy.ps1")
        self.assertIn("$env:LOCALAPPDATA", script)
        self.assertIn("$env:TEMP", script)
        self.assertIn("$env:TMP", script)
        self.assertIn("requirements-snowflake.txt", script)
        self.assertIn("--include-static", script)
        self.assertIn("--skip-core-load", script)

    def test_loader_copies_to_temp_then_atomically_replaces_raw_table(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn("CREATE OR REPLACE TEMPORARY TABLE", script)
        self.assertIn("COPY INTO {temp_table}", script)
        self.assertIn("DELETE FROM {DATABASE}.RAW.{target_table}", script)
        self.assertIn("INSERT INTO {DATABASE}.RAW.{target_table}", script)
        self.assertIn('cursor.execute("BEGIN")', script)
        self.assertIn('cursor.execute("COMMIT")', script)
        self.assertIn('cursor.execute("ROLLBACK")', script)
        self.assertNotIn("TRUNCATE TABLE {DATABASE}.RAW.{target_table}", script)
        self.assertIn("loaded <= 0", script)

    def test_large_static_load_is_explicit_opt_in(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('"--include-static"', script)
        self.assertIn("if args.include_static:", script)


if __name__ == "__main__":
    unittest.main()
