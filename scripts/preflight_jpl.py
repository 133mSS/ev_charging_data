"""Check whether the local JPL source files and environment are ready for ETL."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from project_config import RAW_API_FILE, RAW_API_DIR, RAW_STATIC_DIR, STATIC_REPO, STATIC_SITE_RELATIVE

EXPECTED_STATIC_FILES = 27_723


def main() -> int:
    load_dotenv(ROOT / ".env")
    token_ready = bool(os.getenv("ACN_API_TOKEN", "").strip())
    repo_ready = (STATIC_REPO / ".git").exists()
    static_dir_ready = RAW_STATIC_DIR.exists()
    static_files = list(RAW_STATIC_DIR.glob("*.csv.gz")) if static_dir_ready else []
    api_snapshot_ready = RAW_API_FILE.exists()

    print("===== JPL PROJECT PREFLIGHT =====")
    print(f"Project root: {ROOT}")
    print(f"API token configured: {'YES' if token_ready else 'NO'} (value not displayed)")
    print(f"Static Git repository: {'FOUND' if repo_ready else 'NOT FOUND'} ({STATIC_REPO})")
    print(f"Static site folder: {'FOUND' if static_dir_ready else 'NOT FOUND'} ({RAW_STATIC_DIR})")
    print(f"Static CSV.GZ files: {len(static_files):,}")
    if static_files and len(static_files) != EXPECTED_STATIC_FILES:
        print(f"NOTICE: repository snapshot has {len(static_files):,} files; README reference count is {EXPECTED_STATIC_FILES:,}.")
    print(f"Raw API snapshot: {'FOUND' if api_snapshot_ready else 'NOT FOUND'} ({RAW_API_FILE})")

    if not token_ready:
        print("NEXT: add ACN_API_TOKEN to .env; register at https://ev.caltech.edu/dataset.html.")
    if not repo_ready or not static_dir_ready or not static_files:
        print(f"NEXT: run scripts/clone_jpl_static_repo.ps1 to sparse-checkout {STATIC_SITE_RELATIVE}.")
    if token_ready and static_files:
        print("READY: run python run_pipeline.py --stage extract, then --stage transform and --stage load.")
        return 0
    print("PREFLIGHT INCOMPLETE: missing source access; no sample or synthetic data has been substituted.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
