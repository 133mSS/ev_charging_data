from pathlib import Path
import os

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import CLEAN_SESSIONS_FILE as SESSIONS_FILE, CLEAN_USER_INPUTS_FILE as USER_INPUTS_FILE




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


def load_sessions() -> None:
    print("===== LOADING SESSIONS =====")

    print(f"Input file: {SESSIONS_FILE}")

    df = pd.read_csv(SESSIONS_FILE)

    print(f"Rows read: {len(df)}")

    engine = create_engine(get_database_url())

    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE staging.stg_user_inputs"))
        connection.execute(text("TRUNCATE TABLE staging.stg_charging_sessions CASCADE"))

        df.to_sql(
            "stg_charging_sessions",
            con=connection,
            schema="staging",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )

    print("Rows loaded:", len(df))
    print("===== SESSIONS LOAD COMPLETED =====")
def load_user_inputs() -> None:
    print("\n===== LOADING USER INPUTS =====")

    print(f"Input file: {USER_INPUTS_FILE}")

    df = pd.read_csv(USER_INPUTS_FILE)

    print(f"Rows read: {len(df)}")

    engine = create_engine(get_database_url())

    with engine.begin() as connection:
        df.to_sql(
            "stg_user_inputs",
            con=connection,
            schema="staging",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=500,
        )

    print("Rows loaded:", len(df))
    print("===== USER INPUTS LOAD COMPLETED =====")

if __name__ == "__main__":
    load_sessions()
    load_user_inputs()