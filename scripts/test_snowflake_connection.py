"""Test Snowflake authentication without creating or changing database objects."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from deploy_snowflake import get_connection  # noqa: E402


def main() -> None:
    print("===== SNOWFLAKE CONNECTION TEST =====", flush=True)
    connection = get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    CURRENT_USER(),
                    CURRENT_ROLE(),
                    CURRENT_ACCOUNT(),
                    CURRENT_REGION(),
                    CURRENT_WAREHOUSE()
                """
            )
            row = cursor.fetchone()

        print("Authentication: SUCCESS")
        print(f"Current user: {row[0]}")
        print(f"Current role: {row[1]}")
        print(f"Current account: {row[2]}")
        print(f"Current region: {row[3]}")
        print(f"Current warehouse: {row[4]}")
        print("No database, warehouse, stage, table, or data was created or modified.")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
