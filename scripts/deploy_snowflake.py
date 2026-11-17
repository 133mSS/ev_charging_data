"""Deploy and load the JPL project into Snowflake.

Credentials are read from environment variables; never commit them:
  SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PASSWORD
Optional:
  SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE (default JPL_ETL_WH)

Run from repository root:
  python scripts/deploy_snowflake.py
  python scripts/deploy_snowflake.py --include-static

The large Static file is intentionally opt-in because it scans/loads 175M rows
and consumes trial credits. The script uploads already-compressed files directly
to an internal stage; it does not create another local copy.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from project_config import (  # noqa: E402
    CLEAN_SESSIONS_FILE,
    CLEAN_USER_INPUTS_FILE,
    CLEAN_STATIC_FILE,
    SESSION_MAPPING_FILE,
)

# Load local deployment credentials/config before reading optional warehouse name.
load_dotenv(ROOT / ".env", override=True)

DATABASE = "JPL_ANALYTICS"
WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "JPL_ETL_WH")
STAGE = "@JPL_ANALYTICS.RAW.JPL_RAW_STAGE"


def get_connection():
    try:
        import snowflake.connector
    except ImportError as exc:
        raise RuntimeError(
            "Snowflake connector not installed. Run: "
            "python -m pip install -r requirements-snowflake.txt"
        ) from exc

    load_dotenv(ROOT / ".env", override=True)
    authenticator = os.getenv("SNOWFLAKE_AUTHENTICATOR", "snowflake").strip().lower()
    supported_authenticators = {
        "snowflake",
        "externalbrowser",
        "oauth_authorization_code",
    }
    if authenticator not in supported_authenticators:
        raise RuntimeError(
            "Unsupported SNOWFLAKE_AUTHENTICATOR. Choose snowflake, "
            "externalbrowser (SAML SSO), or OAUTH_AUTHORIZATION_CODE (OIDC SSO)."
        )

    # OAuth Authorization Code identifies the user from the access token.
    # Do not require or pass SNOWFLAKE_USER in this mode: a separately supplied
    # username can differ from the identity authenticated in the browser and
    # trigger Snowflake error 390309 (OAUTH_USERNAMES_MISMATCH).
    required = ["SNOWFLAKE_ACCOUNT"]
    if authenticator != "oauth_authorization_code":
        required.append("SNOWFLAKE_USER")
    if authenticator == "snowflake":
        required.append("SNOWFLAKE_PASSWORD")
    missing = [name for name in required if not os.getenv(name) or not os.getenv(name).strip()]
    if missing:
        raise RuntimeError(
            "Missing Snowflake credentials in .env: " + ", ".join(missing)
        )

    # Do not select a database or warehouse at login: on first deployment
    # neither object exists yet. The bootstrap SQL creates them before USE.
    kwargs = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"].strip(),
        "login_timeout": 30,
        "network_timeout": 300,
    }
    # Password and SAML SSO modes need an explicit Snowflake login name.
    # OAuth Authorization Code derives the authenticated user from the token.
    if authenticator != "oauth_authorization_code":
        kwargs["user"] = os.environ["SNOWFLAKE_USER"].strip()
    if authenticator == "externalbrowser":
        # Browser-based SAML 2.0 SSO.
        kwargs["authenticator"] = "externalbrowser"
    elif authenticator == "oauth_authorization_code":
        # Browser-based OIDC SSO (for example, managed Google sign-in).
        kwargs["authenticator"] = "OAUTH_AUTHORIZATION_CODE"
    else:
        kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]
    role = os.getenv("SNOWFLAKE_ROLE")
    if role:
        kwargs["role"] = role
    return snowflake.connector.connect(**kwargs)


def run_sql_file(connection, relative_path: str) -> None:
    path = ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(path)
    print(f"\n===== APPLY {relative_path} =====", flush=True)
    # execute_string is a Connection method in snowflake-connector-python.
    # It returns one Cursor per statement when return_cursors=True.
    for result_cursor in connection.execute_string(
        path.read_text(encoding="utf-8"),
        return_cursors=True,
    ):
        try:
            if result_cursor.description:
                rows = result_cursor.fetchall()
                for row in rows[:10]:
                    print(row)
        finally:
            result_cursor.close()


def quote_sql_string(value: str) -> str:
    return value.replace("'", "''")


def build_stage_directory(stage_folder: str) -> str:
    """Return a Snowflake internal-stage directory URI with an explicit separator."""
    folder = stage_folder.strip("/")
    if not folder:
        raise ValueError("stage_folder must not be empty")
    return f"{STAGE}/{folder}/"


def upload_and_copy(
    connection,
    local_file: Path,
    stage_folder: str,
    target_table: str,
    copy_columns: str | None = None,
) -> int:
    if not local_file.exists():
        raise FileNotFoundError(
            f"Required processed JPL file not found: {local_file}"
        )
    size = local_file.stat().st_size
    if size > 250 * 1024**2:
        print(
            f"WARNING: {local_file.name} is {size / 1024**2:,.1f} MiB compressed. "
            "Snowflake PUT can upload large files in chunks, but COPY load parallelism "
            "is generally better with multiple 100–250 MiB compressed files. "
            "This script will proceed without creating a local duplicate.",
            flush=True,
        )

    print(
        f"\n===== UPLOAD {local_file.name} ({size / 1024**2:,.1f} MiB) =====",
        flush=True,
    )
    # Snowflake PUT reads this existing file and uploads it directly; no temp copy.
    file_uri = "file://" + local_file.resolve().as_posix()
    file_uri = quote_sql_string(file_uri)
    stage_path = build_stage_directory(stage_folder)

    with connection.cursor() as cursor:
        cursor.execute(
            f"PUT '{file_uri}' {stage_path} "
            "AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=4"
        )
        put_rows = cursor.fetchall()
        for row in put_rows:
            print("PUT:", row[:4])

        # Load into an isolated temporary table first. The published RAW table
        # remains intact if PUT/COPY fails or the file contains zero loadable rows.
        temp_table = f"TMP_LOAD_{target_table}"
        cursor.execute(
            f"CREATE OR REPLACE TEMPORARY TABLE {temp_table} "
            f"LIKE {DATABASE}.RAW.{target_table}"
        )
        file_name = quote_sql_string(local_file.name)
        if copy_columns:
            copy_sql = f"""
                COPY INTO {temp_table} ({copy_columns})
                FROM (
                    SELECT * FROM {stage_path}
                )
                FILE_FORMAT = (FORMAT_NAME = {DATABASE}.RAW.JPL_CSV_GZ_FORMAT)
                PATTERN = '.*{file_name}'
                ON_ERROR = 'ABORT_STATEMENT'
                FORCE = TRUE
            """
        else:
            copy_sql = f"""
                COPY INTO {temp_table}
                FROM {stage_path}
                FILES = ('{file_name}')
                FILE_FORMAT = (FORMAT_NAME = {DATABASE}.RAW.JPL_CSV_GZ_FORMAT)
                ON_ERROR = 'ABORT_STATEMENT'
                FORCE = TRUE
            """
        cursor.execute(copy_sql)
        results = cursor.fetchall()
        loaded = 0
        for row in results:
            print("COPY:", row)
            # COPY result fields: file, status, rows_parsed, rows_loaded, ...
            if len(row) > 3 and isinstance(row[3], (int, float)):
                loaded += int(row[3])

        if loaded <= 0:
            raise RuntimeError(
                f"Snowflake COPY loaded zero rows from {local_file.name}; "
                f"existing table {DATABASE}.RAW.{target_table} was not replaced."
            )

        # Replace rows transactionally without dropping the permanent table.
        # This preserves grants and dependent views (especially the full-Static view).
        cursor.execute("BEGIN")
        try:
            cursor.execute(f"DELETE FROM {DATABASE}.RAW.{target_table}")
            cursor.execute(
                f"INSERT INTO {DATABASE}.RAW.{target_table} "
                f"SELECT * FROM {temp_table}"
            )
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise

        cursor.execute(
            f"INSERT INTO {DATABASE}.RAW.LOAD_AUDIT "
            "(SOURCE_FILE, TARGET_TABLE, ROWS_LOADED, STATUS) "
            "VALUES (%s, %s, %s, %s)",
            (local_file.name, target_table, loaded, "LOADED"),
        )
        return loaded


def deploy_streamlit_app(connection) -> None:
    app_file = ROOT / "snowflake" / "streamlit_app.py"
    if not app_file.exists():
        raise FileNotFoundError(app_file)
    file_uri = quote_sql_string("file://" + app_file.resolve().as_posix())
    stage_path = build_stage_directory("app")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE", "JPL_ETL_WH")
    with connection.cursor() as cursor:
        cursor.execute(
            f"PUT '{file_uri}' {stage_path} "
            "AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=4"
        )
        print("STREAMLIT SOURCE PUT:", cursor.fetchall())
        environment_file = ROOT / "snowflake" / "environment.yml"
        if environment_file.exists():
            env_uri = quote_sql_string("file://" + environment_file.resolve().as_posix())
            cursor.execute(
                f"PUT '{env_uri}' {stage_path} "
                "AUTO_COMPRESS=FALSE OVERWRITE=TRUE PARALLEL=4"
            )
            print("STREAMLIT ENVIRONMENT PUT:", cursor.fetchall())
        cursor.execute(f"""
            CREATE OR REPLACE STREAMLIT {DATABASE}.ANALYTICS.JPL_EV_CHARGING_DASHBOARD
            FROM '{stage_path}'
            MAIN_FILE = 'streamlit_app.py'
            QUERY_WAREHOUSE = {warehouse}
            COMMENT = 'JPL EV Charging Analytics Q1-Q5'
        """)
        print("Streamlit object created.")
        cursor.execute(
            f"ALTER STREAMLIT {DATABASE}.ANALYTICS.JPL_EV_CHARGING_DASHBOARD "
            "ADD LIVE VERSION FROM LAST"
        )
        print("Streamlit live version published.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-static",
        action="store_true",
        help="Upload and load the 175M-row cleaned Static measurements file.",
    )
    parser.add_argument(
        "--skip-core-load",
        action="store_true",
        help="Do not upload/reload API sessions and user inputs.",
    )
    args = parser.parse_args()

    connection = get_connection()
    try:
        # Creates the database and warehouse, then selects both in the SQL file.
        run_sql_file(connection, "snowflake/00_bootstrap.sql")
        run_sql_file(connection, "snowflake/01_raw_staging.sql")

        if not args.skip_core_load:
            upload_and_copy(
                connection, CLEAN_SESSIONS_FILE, "sessions",
                "STG_CHARGING_SESSIONS",
            )
            upload_and_copy(
                connection, CLEAN_USER_INPUTS_FILE, "user_inputs",
                "STG_USER_INPUTS",
            )
            upload_and_copy(
                connection, SESSION_MAPPING_FILE, "session_mapping",
                "STG_SESSION_MAPPING",
            )

        if args.include_static:
            upload_and_copy(
                connection, CLEAN_STATIC_FILE, "static",
                "STG_STATIC_MEASUREMENTS",
            )
        else:
            print(
                "\nStatic upload skipped. Re-run with --include-static "
                "to load the full Static dataset.",
                flush=True,
            )

        run_sql_file(connection, "snowflake/02_warehouse.sql")

        # Always create the compact marts. Without --include-static they are
        # valid empty outputs, so the core deployment and validation still run.
        if args.include_static:
            print("Building Power marts from the complete Static feed...")
        else:
            print("Building empty Power marts; Q5 remains pending until Static is loaded.")
        run_sql_file(connection, "snowflake/03_power_marts.sql")

        run_sql_file(connection, "snowflake/04_validation.sql")
        deploy_streamlit_app(connection)
        print("\nSnowflake deployment/load sequence completed.")
        print("Streamlit app: JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
