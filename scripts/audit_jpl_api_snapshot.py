"""Summarize the genuine JPL API session snapshot downloaded by extract_api.py."""
from collections import Counter
from pathlib import Path
import json, sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from project_config import RAW_API_FILE

def main():
    if not RAW_API_FILE.exists():
        raise FileNotFoundError(f"{RAW_API_FILE} not found. Run python run_pipeline.py --stage extract first.")
    data = json.loads(RAW_API_FILE.read_text(encoding="utf-8"))
    df = pd.DataFrame(data)
    if df.empty: raise RuntimeError("JPL API snapshot is empty.")
    print("===== JPL API SNAPSHOT AUDIT =====")
    print(f"Sessions: {len(df):,}")
    for col in ["siteID", "stationID", "userID", "connectionTime", "disconnectTime", "doneChargingTime", "kWhDelivered"]:
        if col not in df: print(f"{col}: COLUMN MISSING"); continue
        print(f"{col}: non-null={df[col].notna().sum():,}; null={df[col].isna().sum():,}")
    station_count = df["stationID"].nunique(dropna=True) if "stationID" in df else 0
    site_codes = sorted(df["siteID"].dropna().astype(str).unique().tolist()) if "siteID" in df else []
    print(f"Unique station IDs: {station_count:,}")
    print(f"Requested API site alias: jpl")
    print(f"Payload siteID value(s): {site_codes}")
    if len(site_codes) != 1:
        raise ValueError(
            "Expected one non-null payload siteID from /sessions/jpl; "
            f"found {len(site_codes)}. Do not mix site snapshots."
        )
    starts = pd.to_datetime(df.get("connectionTime"), utc=True, errors="coerce")
    print(f"Connection range (UTC): {starts.min()} -> {starts.max()}")
    if "userInputs" in df:
        input_count = sum(len(x) for x in df["userInputs"] if isinstance(x, list))
        sessions_with_inputs = sum(isinstance(x, list) and len(x)>0 for x in df["userInputs"])
        print(f"User input rows: {input_count:,}; sessions with userInputs: {sessions_with_inputs:,}")
    print("Snapshot audit completed: one payload site identifier found for the JPL endpoint.")

if __name__ == "__main__": main()
