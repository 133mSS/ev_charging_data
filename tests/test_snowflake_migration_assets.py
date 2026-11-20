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

    def test_q1_calendar_uses_gap_free_day_sequence_and_vietnamese_weekdays(self):
        queries = read("snowflake/analytics_queries.py")
        self.assertIn("ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS DAY_OFFSET", queries)
        self.assertIn("AVG_SESSIONS_PER_DAY", queries)
        for day in ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]:
            self.assertIn(day, queries)

    def test_q3_last_current_sample_is_within_api_connection_interval(self):
        sql = read("snowflake/03_power_marts.sql")
        view_sql = sql[sql.index("CREATE OR REPLACE VIEW MART.SESSION_POST_CURRENT"):]
        self.assertIn("L.LAST_NONZERO_CURRENT_UTC >= F.CONNECTION_TIME_UTC", view_sql)
        self.assertIn("L.LAST_NONZERO_CURRENT_UTC <= F.DISCONNECT_TIME_UTC", view_sql)

    def test_q5_queries_are_parameterized_and_use_the_selected_power_window(self):
        queries = read("snowflake/analytics_queries.py")
        app = read("snowflake/streamlit_app.py")
        self.assertGreaterEqual(
            queries.count("WHERE LOCAL_MONTH >= TO_DATE(?) AND LOCAL_MONTH < TO_DATE(?)"),
            3,
        )
        self.assertGreaterEqual(
            queries.count("WHERE LOCAL_DATE >= TO_DATE(?) AND LOCAL_DATE < TO_DATE(?)"),
            2,
        )
        self.assertIn('POWER_START_DATE = "2020-07-01"', app)
        self.assertIn('POWER_END_DATE_EXCLUSIVE = "2020-12-01"', app)
        self.assertIn("power_start_date = max(start_date, POWER_START_DATE)", app)
        self.assertIn("station_scope = query(Q5_STATION_SCOPE_SQL)", app)

    def test_q4_selects_latest_request_before_filtering_positive_kwh(self):
        queries = read("snowflake/analytics_queries.py")
        q4 = queries[queries.index("Q4_LATEST_REQUESTS_SQL"):queries.index("Q4_TOTAL_SESSIONS_SQL")]
        self.assertIn("QUALIFY ROW_NUMBER()", q4)
        self.assertLess(q4.index("QUALIFY ROW_NUMBER()"), q4.index("L.KWH_REQUESTED > 0"))
        self.assertIn("MODIFIED_AT DESC NULLS LAST", q4)

    def test_q3_uses_precise_last_positive_current_semantics(self):
        sql = read("snowflake/03_power_marts.sql")
        app = read("snowflake/streamlit_app.py")
        self.assertIn("MAX(IFF(S.CHARGING_CURRENT_A > 0, S.TIMESTAMP_UTC, NULL))", sql)
        self.assertIn("mẫu dòng điện dương cuối", app)
        self.assertIn("không phải thời điểm pin đầy", app)

    def test_q2_visuals_sort_independently_and_keep_all_evse_in_detail_table(self):
        app = read("snowflake/streamlit_app.py")
        q2_section = app.split("# Q2", 1)[1].split("# Q3", 1)[0]
        self.assertIn('q2_by_sessions = q2.sort_values(', q2_section)
        self.assertIn('"SESSION_COUNT", ascending=False', q2_section)
        self.assertIn('q2_by_energy = q2.sort_values(', q2_section)
        self.assertIn('"TOTAL_ENERGY_KWH", ascending=False', q2_section)
        self.assertIn("top_n = min(15, len(q2))", q2_section)
        self.assertIn('orientation="h"', q2_section)
        self.assertIn("q2_sessions_plot", q2_section)
        self.assertIn("q2_energy_plot", q2_section)
        self.assertIn('q2_detail["SESSION_COUNT"].rank(', q2_section)
        self.assertIn('q2_detail["TOTAL_ENERGY_KWH"].rank(', q2_section)
        self.assertIn('method="min", ascending=False', q2_section)
        self.assertIn('"RANK_BY_SESSIONS": "Hạng theo số phiên"', q2_section)
        self.assertIn('"RANK_BY_ENERGY": "Hạng theo tổng kWh"', q2_section)
        self.assertIn("len(q2)} EVSE", q2_section)

    def test_q4_restores_share_of_sessions_at_or_above_90_percent(self):
        app = read("snowflake/streamlit_app.py")
        self.assertIn('achieved_90_pct =', app)
        self.assertIn('(ratio >= 90).mean()', app)
        self.assertIn('e.metric(\n            "Phiên đạt ≥ 90% yêu cầu"', app)
        self.assertIn('e.metric("Phiên đạt ≥ 90% yêu cầu", "N/A")', app)

    def test_q5_multi_series_legends_use_vietnamese_labels(self):
        app = read("snowflake/streamlit_app.py")
        for label in [
            "Coverage trung bình",
            "Coverage trung vị",
            "EVSE có Power trung bình",
            "EVSE có Power tối đa",
            "Power trung bình (kW)",
            "Power P95 (kW)",
        ]:
            self.assertIn(label, app)
        self.assertIn("y=[\"Coverage trung bình\", \"Coverage trung vị\"]", app)
        self.assertIn("y=[\"EVSE có Power trung bình\", \"EVSE có Power tối đa\"]", app)
        self.assertIn("y=[\"Power trung bình (kW)\", \"Power P95 (kW)\"]", app)

    def test_q5_heatmap_renders_all_fixed_evse_labels(self):
        app = read("snowflake/streamlit_app.py")
        q5_section = app.split("# Q5", 1)[1]
        self.assertIn("heatmap_matrix = (", q5_section)
        self.assertIn(".reindex(index=station_ids, columns=month_values)", q5_section)
        self.assertIn('tickmode="array"', q5_section)
        self.assertIn("tickvals=station_ids", q5_section)
        self.assertIn("ticktext=station_ids", q5_section)
        self.assertIn('tickfont={"size": 9}', q5_section)
        self.assertIn("height=max(760, 18 * len(station_ids))", q5_section)
        self.assertIn("len(station_ids) * len(month_values)", q5_section)

    def test_q1_heatmap_draws_all_weekday_labels(self):
        app = read("snowflake/streamlit_app.py")
        q1_section = app.split("# Q1", 1)[1].split("# Q2", 1)[0]
        self.assertIn("tickmode=\"array\"", q1_section)
        self.assertIn("tickvals=weekday_order", q1_section)
        self.assertIn("ticktext=weekday_order", q1_section)

    def test_q3_duration_chart_displays_counts_and_session_share(self):
        app = read("snowflake/streamlit_app.py")
        q3_section = app.split("# Q3", 1)[1].split("# Q4", 1)[0]
        self.assertIn("SESSION_SHARE_PCT", q3_section)
        self.assertIn('text="SESSION_COUNT"', q3_section)
        self.assertIn('texttemplate="%{y:,.0f} · %{customdata[0]:.1f}%"', q3_section)
        self.assertIn('"Tỷ trọng phiên (%)"', q3_section)

    def test_q4_exposes_request_coverage_and_scatter_uses_svg(self):
        app = read("snowflake/streamlit_app.py")
        self.assertIn("Q4_TOTAL_SESSIONS_SQL", app)
        self.assertIn("request_coverage_pct", app)
        self.assertIn('render_mode="svg"', app)

    def test_q4_scatter_uses_single_color_and_keeps_evse_on_hover(self):
        app = read("snowflake/streamlit_app.py")
        q4_section = app.split("# Q4", 1)[1].split("# Q5", 1)[0]
        self.assertNotIn('color="STATION_ID"', q4_section)
        self.assertIn('hover_name="STATION_ID"', q4_section)
        self.assertIn('"color": "#5B9BFF"', q4_section)
        self.assertIn('"size": 4', q4_section)
        self.assertIn('"opacity": 0.22', q4_section)
        self.assertIn('"color": "#5B9BFF"', q4_section)
        self.assertIn('range=[0, lim]', q4_section)
        self.assertIn('rangemode="tozero"', q4_section)
        self.assertIn('scaleanchor="x"', q4_section)
        self.assertIn('scaleratio=1', q4_section)
        self.assertIn('constrain="domain"', q4_section)

    def test_warehouse_runtime_uses_builtin_python_without_installing_python_package(self):
        environment = read("snowflake/environment.yml")
        deploy = read("scripts/deploy_snowflake.py")
        dependency_lines = [
            line.strip()
            for line in environment.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertNotIn("  - python=3.11", environment)
        self.assertNotIn("  - python==3.11", environment)
        self.assertIn("RUNTIME_NAME = 'SYSTEM$WAREHOUSE_RUNTIME'", deploy)

    def test_dashboard_sql_is_deployed_as_a_sibling_module(self):
        app = read("snowflake/streamlit_app.py")
        deploy = read("scripts/deploy_snowflake.py")
        self.assertIn("from analytics_queries import", app)
        self.assertIn('query_module = ROOT / "snowflake" / "analytics_queries.py"', deploy)
        self.assertIn("STREAMLIT SQL MODULE PUT", deploy)

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

    def test_project_env_overrides_stale_process_environment(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('load_dotenv(ROOT / ".env", override=True)', script)

    def test_oauth_authorization_code_uses_token_identity_without_user_parameter(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('if authenticator != "oauth_authorization_code":', script)
        self.assertIn('if authenticator != "oauth_authorization_code":\n        kwargs["user"]', script)
        self.assertIn("OAUTH_USERNAMES_MISMATCH", script)

    def test_sso_authentication_does_not_require_snowflake_password(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('os.getenv("SNOWFLAKE_AUTHENTICATOR", "snowflake")', script)
        self.assertIn('authenticator == "externalbrowser"', script)
        self.assertIn('authenticator == "oauth_authorization_code"', script)
        self.assertIn('kwargs["authenticator"] = "externalbrowser"', script)
        self.assertIn('kwargs["authenticator"] = "OAUTH_AUTHORIZATION_CODE"', script)
        self.assertIn('if authenticator == "snowflake":', script)

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

    def test_put_and_copy_stage_directories_end_with_slash(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('return f"{STAGE}/{folder}/"', script)

        upload_start = script.index("def upload_and_copy(")
        upload_assignment = script.index(
            "stage_path = build_stage_directory(stage_folder)", upload_start
        )
        upload_put = script.index(
            'f"PUT \'{file_uri}\' {stage_path} "', upload_start
        )
        self.assertLess(upload_assignment, upload_put)

        app_start = script.index("def deploy_streamlit_app(")
        app_assignment = script.index(
            'stage_path = build_stage_directory("app")', app_start
        )
        app_put = script.index(
            'f"PUT \'{file_uri}\' {stage_path} "', app_start
        )
        app_create = script.index("FROM '{stage_path}'", app_start)
        self.assertLess(app_assignment, app_put)
        self.assertLess(app_assignment, app_create)
        self.assertNotIn("\\n    stage_path =", script)

    def test_loader_records_run_id_hash_size_and_copy_query_id(self):
        raw_sql = read("snowflake/01_raw_staging.sql")
        deploy = read("scripts/deploy_snowflake.py")
        self.assertIn("RUN_ID VARCHAR", raw_sql)
        self.assertIn("SOURCE_SHA256 VARCHAR(64)", raw_sql)
        self.assertIn("COPY_QUERY_ID VARCHAR", raw_sql)
        self.assertIn("def sha256_file(", deploy)
        self.assertIn("ETL RUN_ID:", deploy)
        self.assertIn("FILE_SIZE_BYTES", deploy)
        self.assertIn("COPY_QUERY_ID", deploy)

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
        self.assertIn("run_data_quality_checks(connection)", script)
        self.assertIn('ROOT / "snowflake" / "05_data_quality.sql"', script)

    def test_read_only_snowflake_connection_smoke_test_exists(self):
        script = read("scripts/test_snowflake_connection.py")
        self.assertIn("from deploy_snowflake import get_connection", script)
        self.assertIn("CURRENT_USER()", script)
        self.assertIn("CURRENT_ACCOUNT()", script)
        self.assertIn("Authentication: SUCCESS", script)
        self.assertNotIn("CREATE DATABASE", script)
        self.assertNotIn("COPY INTO", script)

    def test_large_static_load_is_explicit_opt_in(self):
        script = read("scripts/deploy_snowflake.py")
        self.assertIn('"--include-static"', script)
        self.assertIn("if args.include_static:", script)

    def test_app_only_deploy_skips_data_and_mart_rebuild(self):
        script = read("scripts/deploy_snowflake.py")
        wrapper = read("scripts/run_snowflake_deploy.ps1")
        self.assertIn('"--app-only"', script)
        app_only = script[script.index('if args.app_only:'):script.index('run_id = str(uuid.uuid4())')]
        self.assertIn("deploy_streamlit_app(connection)", app_only)
        self.assertNotIn("run_sql_file(connection, \"snowflake/03_power_marts.sql\")", app_only)
        self.assertIn("[switch]$AppOnly", wrapper)
        self.assertIn('$PythonArgs += "--app-only"', wrapper)


if __name__ == "__main__":
    unittest.main()
