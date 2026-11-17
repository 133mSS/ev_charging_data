from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import SITE_ID, RAW_STATIC_DIR, CLEAN_STATIC_FILE, PROCESSED_DIR, CLEAN_SESSIONS_FILE

COLUMN_RENAME = {
    "Unnamed: 0": "timestamp",
    "timestamp": "timestamp",
    "Charging Current (A)": "charging_current_a",
    "Actual Pilot (A)": "actual_pilot_a",
    "Voltage (V)": "voltage_v",
    "Charging State": "charging_state",
    "Energy Delivered (kWh)": "energy_delivered_kwh",
    "Power (kW)": "power_kw",
}

def is_non_charging_session(df: pd.DataFrame) -> bool:
    energy = pd.to_numeric(df.get("Energy Delivered (kWh)"), errors="coerce")
    current = pd.to_numeric(df.get("Charging Current (A)"), errors="coerce")
    no_energy = energy.notna().sum() == 0
    no_current = current.gt(0).sum() == 0
    return bool(no_energy and no_current)

def extract_station_id(filename: str) -> str:
    # ACN static file names start with four hyphen-separated station components.
    parts = filename.removesuffix(".csv.gz").split("-")
    if len(parts) < 5:
        raise ValueError(f"Unexpected JPL static filename: {filename}")
    return "-".join(parts[:4])

def transform_session(file: Path) -> pd.DataFrame:
    df = pd.read_csv(file, compression="gzip")
    if df.empty or is_non_charging_session(df):
        return pd.DataFrame()
    df = df.rename(columns=COLUMN_RENAME)
    if "timestamp" not in df.columns:
        raise ValueError(f"Missing timestamp column in {file.name}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"])
    df["site_id"] = SITE_ID
    df["station_id"] = extract_station_id(file.name)
    df["session_id"] = file.name.removesuffix(".csv.gz")
    for col in ["charging_current_a", "actual_pilot_a", "voltage_v", "energy_delivered_kwh", "power_kw"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = pd.NA
    if "charging_state" not in df.columns:
        df["charging_state"] = pd.NA
    columns = ["site_id", "station_id", "session_id", "timestamp", "charging_current_a", "actual_pilot_a", "voltage_v", "charging_state", "energy_delivered_kwh", "power_kw"]
    return df[columns]

def main() -> None:
    files = sorted(RAW_STATIC_DIR.glob("*.csv.gz"))
    if not files:
        raise FileNotFoundError(f"No JPL .csv.gz files in {RAW_STATIC_DIR}. Run extract first.")
    if not CLEAN_SESSIONS_FILE.exists():
        raise FileNotFoundError(
            f"Clean API sessions not found: {CLEAN_SESSIONS_FILE}. Run clean_api.py before clean_static.py."
        )
    api_site_codes = (
        pd.read_csv(CLEAN_SESSIONS_FILE, usecols=["site_id"], dtype=str)["site_id"]
        .dropna().unique().tolist()
    )
    if len(api_site_codes) != 1:
        raise ValueError(
            f"Expected exactly one internal API siteID for endpoint {SITE_ID}; found {api_site_codes}"
        )
    # The API endpoint alias (jpl) and payload siteID are different identifiers.
    api_site_code = api_site_codes[0]

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    temp_output = CLEAN_STATIC_FILE.with_suffix(CLEAN_STATIC_FILE.suffix + ".tmp")
    if temp_output.exists():
        temp_output.unlink()
    total_rows = retained = empty = 0
    first_write = True
    for index, file in enumerate(files, start=1):
        frame = transform_session(file)
        if frame.empty:
            empty += 1
            continue
        frame["site_id"] = api_site_code
        retained += 1
        total_rows += len(frame)
        frame.to_csv(temp_output, mode="w" if first_write else "a", header=first_write, index=False, compression="gzip")
        first_write = False
        if index % 500 == 0 or index == len(files):
            print(f"[{index:,}/{len(files):,}] retained_sessions={retained:,}; rows={total_rows:,}", flush=True)
    if first_write:
        if temp_output.exists():
            temp_output.unlink()
        raise RuntimeError("No valid measurement rows were produced from JPL static files.")
    temp_output.replace(CLEAN_STATIC_FILE)
    print("\n===== JPL STATIC CLEANING COMPLETED =====")
    print(f"Input files: {len(files):,}; retained sessions: {retained:,}; empty/non-charging: {empty:,}")
    print(f"Measurement rows: {total_rows:,}")
    print(f"API internal siteID applied to static rows: {api_site_code}")
    print(f"Output: {CLEAN_STATIC_FILE}")

if __name__ == "__main__":
    main()
