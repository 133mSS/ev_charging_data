from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class TestSnowflakeDataQualityAssets(unittest.TestCase):
    def test_data_quality_gate_covers_keys_mapping_and_row_reconciliation(self):
        sql = read("snowflake/05_data_quality.sql")
        for check in [
            "DUPLICATE_SESSION_KEYS",
            "DUPLICATE_USER_REQUEST_KEYS",
            "DUPLICATE_STATIC_MAPPING_KEYS",
            "DUPLICATE_API_MAPPING_KEYS",
            "DUPLICATE_STATION_DIMENSION_KEYS",
            "DUPLICATE_DATE_DIMENSION_KEYS",
            "DUPLICATE_TIME_DIMENSION_KEYS",
            "ORPHAN_SESSION_DATE_KEYS",
            "ORPHAN_SESSION_TIME_KEYS",
            "STATIC_ROW_RECONCILIATION_DELTA",
            "UNMAPPED_STATIC_ROWS",
            "ORPHAN_SESSION_STATION_KEYS",
            "INVALID_POST_LAST_CURRENT_INTERVALS",
        ]:
            self.assertIn(check, sql)

    def test_data_quality_gate_checks_complete_utc_calendar(self):
        sql = read("snowflake/05_data_quality.sql")
        self.assertIn("'POWER_SITE_HOUR_COUNT'", sql)
        self.assertIn("3673", sql)
        self.assertIn("'DUPLICATE_POWER_SITE_HOUR_KEYS'", sql)

    def test_q3_interval_check_joins_fact_for_connection_timestamp(self):
        sql = read("snowflake/05_data_quality.sql")
        block = sql[
            sql.index("'INVALID_POST_LAST_CURRENT_INTERVALS'"):
            sql.index("'POWER_SITE_HOUR_COUNT'")
        ]
        self.assertIn("INNER JOIN WAREHOUSE.FACT_CHARGING_SESSIONS S", block)
        self.assertIn("S.CONNECTION_TIME_UTC", block)
        self.assertIn("F.DISCONNECT_TIME_UTC", block)
        self.assertNotIn("F.CONNECTION_TIME_UTC", block)

    def test_quality_sql_emits_explicit_pass_fail_rows(self):
        sql = read("snowflake/05_data_quality.sql")
        self.assertIn("AS STATUS", sql)
        self.assertIn("'PASS'", sql)
        self.assertIn("'FAIL'", sql)
        self.assertIn("AS DETAILS", sql)

    def test_deployer_runs_quality_gate_before_publishing_streamlit(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertLess(
            script.index("run_data_quality_checks(connection)"),
            script.index("deploy_streamlit_app(connection)"),
        )

    def test_quality_gate_supports_multi_statement_sql_file(self):
        script = read("scripts/deploy_snowflake.py")
        block = script[
            script.index("def run_data_quality_checks("):
            script.index("def deploy_streamlit_app(")
        ]
        self.assertIn("connection.execute_string(", block)
        self.assertIn("return_cursors=True", block)
        self.assertNotIn("cursor.execute(sql_path.read_text", block)


if __name__ == "__main__":
    unittest.main()
