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

    def test_q4_selects_latest_request_before_filtering_positive_kwh(self):
        app = read("snowflake/streamlit_app.py")
        q4 = app[app.index("# Q4"):app.index("# Q5")]
        self.assertIn("QUALIFY ROW_NUMBER()", q4)
        self.assertLess(q4.index("QUALIFY ROW_NUMBER()"), q4.index("L.KWH_REQUESTED > 0"))

    def test_streamlit_uses_snowflake_active_session_not_local_postgres(self):
        app = read("snowflake/streamlit_app.py")
        self.assertIn("get_active_session", app)
        self.assertNotIn("psycopg2", app)
        self.assertNotIn("DB_PASSWORD", app)

    def test_deployment_uses_put_and_copy_into_without_secrets_in_source(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn("SNOWFLAKE_ACCOUNT", script)
        self.assertIn("SNOWFLAKE_USER", script)
        self.assertIn("SNOWFLAKE_PASSWORD", script)
        self.assertIn("PUT ", script)
        self.assertIn("COPY INTO", script)
        self.assertNotIn("password = '", script.lower())

    def test_large_static_load_is_explicit_opt_in(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('"--include-static"', script)
        self.assertIn("if args.include_static:", script)


if __name__ == "__main__":
    unittest.main()
