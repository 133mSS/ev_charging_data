from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import STATIC_SOURCE_DIR


def main() -> None:
    if not STATIC_SOURCE_DIR.exists():
        raise FileNotFoundError(
            f"JPL static folder not found: {STATIC_SOURCE_DIR}\n"
            "Run scripts/clone_jpl_static_repo.ps1 first, or set ACN_STATIC_DATA_DIR in .env."
        )
    files = list(STATIC_SOURCE_DIR.glob("*.csv.gz"))
    if not files:
        raise RuntimeError(f"No .csv.gz files found in {STATIC_SOURCE_DIR}")
    total_bytes = sum(f.stat().st_size for f in files)
    print("===== JPL STATIC SOURCE CHECK =====")
    print(f"Files available: {len(files):,}")
    print(f"Compressed size: {total_bytes / (1024**2):,.1f} MiB")
    print(f"Source folder: {STATIC_SOURCE_DIR}")
    print("No second copy is made; the transform stage reads from this sparse-checkout folder directly.")


if __name__ == "__main__":
    main()
