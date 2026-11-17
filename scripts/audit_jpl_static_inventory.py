"""Inventory the JPL Static folder through Git metadata (no CSV.GZ bodies are read)."""
from collections import Counter
from pathlib import Path
import csv, json, re, subprocess, sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import STATIC_REPO

REPO = STATIC_REPO
RELATIVE_DIR = "time series data/jpl/Arroyo_Garage_01"
OUT_DIR = PROJECT_ROOT / "data" / "inventory"

def main():
    if not (REPO / ".git").exists():
        raise FileNotFoundError(f"Static repo not found: {REPO}. Run scripts/clone_jpl_static_repo.ps1 first.")
    commit = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    branch = subprocess.run(
        ["git", "-C", str(REPO), "branch", "--show-current"],
        text=True, capture_output=True, check=True,
    ).stdout.strip() or "detached-HEAD"
    cmd = ["git", "-C", str(REPO), "ls-tree", "-rl", "HEAD", "--", RELATIVE_DIR]
    result = subprocess.run(cmd, text=True, capture_output=True, check=True)
    station_counts, month_counts = Counter(), Counter()
    rows, total_bytes, min_date, max_date = [], 0, None, None
    pattern = re.compile(r"^(.+)-(\d{4}-\d{2}-\d{2})T")
    for line in result.stdout.splitlines():
        parts = line.split(None, 4)
        if len(parts) != 5 or not parts[4].endswith(".csv.gz"):
            continue
        size = int(parts[3])
        name = Path(parts[4]).name
        match = pattern.match(name)
        if not match:
            continue
        station, date = match.groups()
        month = date[:7]
        station_counts[station] += 1
        month_counts[month] += 1
        total_bytes += size
        min_date = date if min_date is None or date < min_date else min_date
        max_date = date if max_date is None or date > max_date else max_date
        rows.append((name, station, date, month, size))
    if not rows:
        raise RuntimeError("No JPL CSV.GZ entries found in Git tree.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "jpl_static_file_inventory.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["filename", "station_id_from_filename", "session_date", "month", "compressed_bytes"]); w.writerows(rows)
    with (OUT_DIR / "jpl_static_station_inventory.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["station_id_from_filename", "static_file_count"]); w.writerows(sorted(station_counts.items()))
    with (OUT_DIR / "jpl_static_monthly_inventory.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(["month", "static_file_count"]); w.writerows(sorted(month_counts.items()))
    print("===== JPL STATIC INVENTORY =====")
    print(f"Files: {len(rows):,}")
    print(f"Unique filename station IDs: {len(station_counts):,}")
    print(f"Date range: {min_date} to {max_date}")
    print(f"Compressed bytes: {total_bytes:,} ({total_bytes / (1024**2):,.1f} MiB)")
    print(f"Months with data: {len(month_counts)}")
    summary = {
        "repository": "tongxin-li/ACN-Data-Static",
        "branch": branch,
        "git_commit": commit,
        "snapshot_date": __import__("datetime").date.today().isoformat(),
        "directory": RELATIVE_DIR,
        "file_count": len(rows),
        "unique_filename_station_ids": len(station_counts),
        "date_min": min_date,
        "date_max": max_date,
        "compressed_bytes": total_bytes,
        "compressed_mib": round(total_bytes / (1024**2), 2),
        "months_with_data": len(month_counts),
        "files_by_year": dict(sorted(Counter(date[:4] for _, _, date, _, _ in rows).items())),
    }
    (OUT_DIR / "jpl_static_inventory_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Output directory: {OUT_DIR}")
    print("Note: filename station-ID count is historical IDs in this snapshot, not the official installed EVSE count.")

if __name__ == "__main__":
    main()
