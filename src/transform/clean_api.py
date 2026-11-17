from pathlib import Path
import json

import pandas as pd


# =========================
# PATHS
# =========================

PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import RAW_API_FILE as INPUT_FILE, CLEAN_SESSIONS_FILE as SESSIONS_OUTPUT, CLEAN_USER_INPUTS_FILE as USER_INPUTS_OUTPUT, PROCESSED_DIR as OUTPUT_DIR




# =========================
# LOAD
# =========================

def load_raw_data() -> list[dict]:
    with INPUT_FILE.open(encoding="utf-8") as f:
        return json.load(f)


# =========================
# SESSION TRANSFORMATION
# =========================

def transform_sessions(data: list[dict]) -> pd.DataFrame:
    rows = []

    for session in data:
        rows.append(
            {
                "record_id": session.get("_id"),
                "session_id": session.get("sessionID"),
                "user_id": session.get("userID"),
                "station_id": session.get("stationID"),
                "space_id": session.get("spaceID"),
                "site_id": session.get("siteID"),
                "cluster_id": session.get("clusterID"),
                "connection_time": session.get("connectionTime"),
                "disconnect_time": session.get("disconnectTime"),
                "done_charging_time": session.get("doneChargingTime"),
                "energy_kwh": session.get("kWhDelivered"),
                "timezone": session.get("timezone"),
                "has_user_metadata": (
                    isinstance(session.get("userInputs"), list)
                    and len(session.get("userInputs")) > 0
                ),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["session_id", "input_id", "user_id", "miles_requested", "wh_per_mile", "minutes_available", "modified_at", "payment_required", "requested_departure", "kwh_requested", "departure_before_modified"])

    # Parse timestamps
    timestamp_columns = [
        "connection_time",
        "disconnect_time",
        "done_charging_time",
    ]

    for col in timestamp_columns:
        df[col] = pd.to_datetime(
            df[col],
            errors="coerce",
            utc=True,
        )

    # Derived connection duration
    df["connection_duration_minutes"] = (
        df["disconnect_time"] - df["connection_time"]
    ).dt.total_seconds() / 60

    # Data-quality flags
    df["done_after_disconnect"] = (
        df["done_charging_time"].notna()
        & (
            df["done_charging_time"]
            > df["disconnect_time"]
        )
    )

    return df


# =========================
# USER INPUT TRANSFORMATION
# =========================

def transform_user_inputs(data: list[dict]) -> pd.DataFrame:
    rows = []

    for session in data:
        session_id = session.get("sessionID")
        user_inputs = session.get("userInputs")

        if not isinstance(user_inputs, list):
            continue
        input_id = 1
        for item in user_inputs:
            rows.append(
                {
                
                    "session_id": session_id,
                    "input_id": input_id,
                    "user_id": item.get("userID"),
                    "miles_requested": item.get("milesRequested"),
                    "wh_per_mile": item.get("WhPerMile"),
                    "minutes_available": item.get("minutesAvailable"),
                    "modified_at": item.get("modifiedAt"),
                    "payment_required": item.get("paymentRequired"),
                    "requested_departure": item.get(
                        "requestedDeparture"
                    ),
                    "kwh_requested": item.get("kWhRequested"),
                }
            )
            input_id += 1

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["session_id", "input_id", "user_id", "miles_requested", "wh_per_mile", "minutes_available", "modified_at", "payment_required", "requested_departure", "kwh_requested", "departure_before_modified"])

    # Parse timestamps
    df["modified_at"] = pd.to_datetime(
        df["modified_at"],
        errors="coerce",
        utc=True,
    )

    df["requested_departure"] = pd.to_datetime(
        df["requested_departure"],
        errors="coerce",
        utc=True,
    )

    # Data-quality flag
    df["departure_before_modified"] = (
        df["requested_departure"]
        < df["modified_at"]
    )

    return df


# =========================
# MAIN
# =========================

def main() -> None:
    print("===== JPL API CLEANING STARTED =====")

    data = load_raw_data()

    print("Raw sessions:", len(data))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sessions_df = transform_sessions(data)
    user_inputs_df = transform_user_inputs(data)

    sessions_df.to_csv(
        SESSIONS_OUTPUT,
        index=False,
    )

    user_inputs_df.to_csv(
        USER_INPUTS_OUTPUT,
        index=False,
    )

    print("\n===== CLEANING COMPLETED =====")

    print("Sessions cleaned:", len(sessions_df))
    print("User inputs cleaned:", len(user_inputs_df))

    print("\nOutput files:")
    print(SESSIONS_OUTPUT)
    print(USER_INPUTS_OUTPUT)


if __name__ == "__main__":
    main()
