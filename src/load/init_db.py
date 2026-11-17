"""Tạo schema và bảng trong PostgreSQL (chạy 1 lần trước khi nạp dữ liệu).

Thực thi lần lượt các file trong sql/schema/ (01 -> 04).
Các file dùng CREATE ... IF NOT EXISTS nên có thể chạy lại an toàn.
"""
from pathlib import Path
import os

import psycopg2
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = PROJECT_ROOT / "sql" / "schema"


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(f"Thiếu cấu hình trong .env: {missing}")

    schema_files = sorted(SCHEMA_DIR.glob("*.sql"))

    if not schema_files:
        raise FileNotFoundError(f"Không tìm thấy file schema trong {SCHEMA_DIR}")

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
                for schema_file in schema_files:
                    print(f"Applying {schema_file.name}")
                    cursor.execute(schema_file.read_text(encoding="utf-8"))
    finally:
        connection.close()

    print("Database schema is ready.")


if __name__ == "__main__":
    main()
