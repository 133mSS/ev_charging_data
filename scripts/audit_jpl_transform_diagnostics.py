from pathlib import Path
import re
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "jpl"

mapping = pd.read_csv(
    DATA / "jpl_static_api_session_mapping.csv",
    dtype=str
)

quality = pd.read_csv(
    DATA / "jpl_static_api_session_quality.csv"
)

print("\n===== 1. MATCHING SUMMARY =====")
print(mapping["match_status"].value_counts())

print("\n===== 2. UNMATCHED SESSIONS BY MONTH =====")

def extract_api_date(series):
    s = series.fillna("").str.extract(
        r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)$",
        expand=False
    )
    return pd.to_datetime(s, errors="coerce")

def extract_static_date(series):
    s = series.fillna("").str.extract(
        r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d+)$",
        expand=False
    )
    return pd.to_datetime(
        s,
        format="%Y-%m-%dT%H-%M-%S-%f",
        errors="coerce"
    )

for status, col, parser in [
    ("API_ONLY", "api_session_id", extract_api_date),
    ("STATIC_ONLY", "static_session_id", extract_static_date)
]:
    part = mapping[mapping["match_status"] == status].copy()
    dates = parser(part[col])
    print(f"\n{status}: {len(part):,}")
    print(
        dates.dt.to_period("M")
        .value_counts()
        .sort_index()
        .to_string()
    )

print("\n===== 3. LARGE TIMESTAMP DIFFERENCES =====")

columns = [
    "station_id",
    "static_session_id",
    "api_session_id",
    "static_first_ts",
    "api_connection_time",
    "start_abs_diff_seconds",
    "static_last_ts",
    "api_disconnect_time",
    "end_abs_diff_seconds",
]

available = [c for c in columns if c in quality.columns]

for col in ["start_abs_diff_seconds", "end_abs_diff_seconds"]:
    quality[col] = pd.to_numeric(quality[col], errors="coerce")

outliers = quality[
    (quality["start_abs_diff_seconds"] > 60) |
    (quality["end_abs_diff_seconds"] > 60)
].copy()

print("Sessions with time difference > 60 seconds:", len(outliers))

print(
    outliers.sort_values(
        ["start_abs_diff_seconds", "end_abs_diff_seconds"],
        ascending=False
    )[available].head(20).to_string(index=False)
)

print("\n===== DIAGNOSTIC COMPLETED =====")
