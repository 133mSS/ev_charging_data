from pathlib import Path
import gzip

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import CLEAN_STATIC_FILE as STATIC_FILE, SESSION_MAPPING_FILE as MAPPING_FILE, SESSION_QUALITY_FILE as QUALITY_FILE, MATCHED_STATIC_FILE as OUTPUT_FILE



STATIC_COLUMNS = [
    "site_id",
    "station_id",
    "session_id",
    "timestamp",
    "charging_current_a",
    "actual_pilot_a",
    "voltage_v",
    "charging_state",
    "energy_delivered_kwh",
    "power_kw",
]

OUTPUT_COLUMNS = [
    "site_id",
    "station_id",
    "static_session_id",
    "api_session_id",
    "timestamp",
    "charging_current_a",
    "actual_pilot_a",
    "voltage_v",
    "charging_state",
    "energy_delivered_kwh",
    "power_kw",
    "energy_quality",
    "measurement_source",
]


def main() -> None:
    print("===== BUILD MATCHED STATIC MEASUREMENTS =====")

    mapping = pd.read_csv(
        MAPPING_FILE,
        dtype=str,
    )

    matched = mapping.loc[
        mapping["match_status"].eq("MATCHED"),
        [
            "station_id",
            "static_session_id",
            "api_session_id",
        ],
    ].copy()

    if matched["static_session_id"].duplicated().any():
        raise ValueError("Static session IDs are not unique in mapping.")

    if matched["api_session_id"].duplicated().any():
        raise ValueError("API session IDs are not unique in mapping.")

    quality = pd.read_csv(
        QUALITY_FILE,
        usecols=[
            "static_session_id",
            "energy_quality",
        ],
        dtype=str,
    )

    matched = matched.merge(
        quality,
        on="static_session_id",
        how="left",
        validate="one_to_one",
    )

    if matched["energy_quality"].isna().any():
        raise ValueError(
            "Some matched sessions have no energy quality label."
        )

    api_id_lookup = matched.set_index(
        "static_session_id"
    )["api_session_id"].to_dict()

    quality_lookup = matched.set_index(
        "static_session_id"
    )["energy_quality"].to_dict()

    matched_ids = set(api_id_lookup)

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows_written = 0
    sessions_found = set()
    header_written = False

    with gzip.open(
        OUTPUT_FILE,
        "wt",
        encoding="utf-8",
        newline="",
    ) as output:

        for chunk in pd.read_csv(
            STATIC_FILE,
            usecols=STATIC_COLUMNS,
            dtype={
                "station_id": str,
                "session_id": str,
            },
            chunksize=500_000,
        ):
            chunk = chunk[
                chunk["session_id"].isin(matched_ids)
            ].copy()

            if chunk.empty:
                continue

            chunk = chunk.rename(
                columns={
                    "session_id": "static_session_id",
                }
            )

            chunk["api_session_id"] = (
                chunk["static_session_id"].map(api_id_lookup)
            )

            chunk["energy_quality"] = (
                chunk["static_session_id"].map(quality_lookup)
            )

            if chunk[
                ["api_session_id", "energy_quality"]
            ].isna().any().any():
                raise ValueError(
                    "Found a measurement without API mapping "
                    "or energy quality label."
                )

            chunk["measurement_source"] = "ACN_STATIC"

            sessions_found.update(
                chunk["static_session_id"].unique()
            )

            chunk = chunk[OUTPUT_COLUMNS]

            chunk.to_csv(
                output,
                index=False,
                header=not header_written,
            )

            header_written = True
            rows_written += len(chunk)

    if rows_written == 0:
        raise RuntimeError(
            "No measurements matched. Check the mapping and input files."
        )

    print("Mapped sessions:", len(matched_ids))
    print("Sessions with static measurements:", len(sessions_found))
    print("Measurement rows written:", f"{rows_written:,}")

    print("\nEnergy quality by matched session:")
    print(
        matched["energy_quality"]
        .value_counts()
        .to_string()
    )

    print("\nOutput:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
