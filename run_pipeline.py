"""Chạy toàn bộ pipeline dữ liệu theo đúng thứ tự.

Ví dụ:
    python run_pipeline.py                  # làm sạch + nạp DB (dùng dữ liệu thô có sẵn)
    python run_pipeline.py --stage transform
    python run_pipeline.py --stage load
    python run_pipeline.py --stage extract  # tải lại dữ liệu thô (cần token + repo static)

Sau khi pipeline hoàn tất, chạy dashboard:
    streamlit run dashboard/app.py
"""
from pathlib import Path
import argparse
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parent

STAGES = {
    "extract": [
        ("Thu thập session từ ACN API", "src/ingestion/extract_api.py"),
        ("Trích xuất dữ liệu static (JPL Arroyo Garage 01)", "src/ingestion/extract_static.py"),
    ],
    "transform": [
        ("Làm sạch dữ liệu session API", "src/transform/clean_api.py"),
        ("Làm sạch dữ liệu đo static JPL", "src/transform/clean_static.py"),
        ("Ghép session static <-> API", "src/transform/audit_static_api_overlap.py"),
        ("Đối soát & phân loại chất lượng năng lượng", "src/transform/audit_static_api_metrics.py"),
        ("Tạo bảng đo static đã ghép", "src/transform/build_matched_static_measurements.py"),
    ],
    "load": [
        ("Tạo schema PostgreSQL", "src/load/init_db.py"),
        ("Nạp staging: session + user input", "src/load/load_staging.py"),
        ("Nạp warehouse: dim + fact session", "src/load/load_warehouse.py"),
        ("Nạp staging: phép đo static", "src/load/load_static_measurements.py"),
        ("Nạp warehouse: fact phép đo static", "src/load/load_static_measurements_warehouse.py"),
    ],
}


def run_step(index: int, total: int, title: str, script: str) -> None:
    print(f"\n[{index}/{total}] {title}  ({script})", flush=True)
    result = subprocess.run([sys.executable, str(PROJECT_ROOT / script)], cwd=PROJECT_ROOT)

    if result.returncode != 0:
        raise SystemExit(f"Bước thất bại: {script} (exit code {result.returncode})")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--stage",
        choices=["extract", "transform", "load", "all"],
        default="all",
        help="Giai đoạn cần chạy. 'all' = transform + load (không tải lại dữ liệu thô).",
    )
    args = parser.parse_args()

    if args.stage == "all":
        selected = STAGES["transform"] + STAGES["load"]
    else:
        selected = STAGES[args.stage]

    for index, (title, script) in enumerate(selected, start=1):
        run_step(index, len(selected), title, script)

    print("\nPipeline hoàn tất.")


if __name__ == "__main__":
    main()
