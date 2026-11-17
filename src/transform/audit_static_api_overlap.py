from pathlib import Path
from datetime import datetime
import csv

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import CLEAN_STATIC_FILE as STATIC_FILE, CLEAN_SESSIONS_FILE as API_FILE, SESSION_MAPPING_FILE as OUTPUT_FILE




def normalize_static_id(
    station_id: str,
    session_id: str,
) -> str | None:
    prefix = station_id + "-"

    if not session_id.startswith(prefix):
        return None

    timestamp_part = session_id[len(prefix):]

    try:
        session_time = datetime.strptime(
            timestamp_part,
            "%Y-%m-%dT%H-%M-%S-%f",
        )
    except ValueError:
        return None

    normalized_time = session_time.strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )

    normalized_station = station_id.replace("-", "_")

    return f"{normalized_station}_{normalized_time}"


def main() -> None:
    print("===== STATIC / API SESSION AUDIT =====")

    # Đọc static theo chunks để không nạp hàng triệu
    # measurement vào RAM cùng lúc.
    static_mapping = {}
    invalid_static_ids = 0

    for chunk in pd.read_csv(
        STATIC_FILE,
        usecols=["station_id", "session_id"],
        dtype=str,
        chunksize=500_000,
    ):
        pairs = chunk.drop_duplicates()

        for station_id, session_id in pairs.itertuples(
            index=False,
            name=None,
        ):
            normalized_id = normalize_static_id(
                station_id,
                session_id,
            )

            if normalized_id is None:
                invalid_static_ids += 1
                continue

            key = (station_id, normalized_id)

            if key in static_mapping:
                if static_mapping[key] != session_id:
                    raise ValueError(
                        f"Duplicate normalized static key: {key}"
                    )
            else:
                static_mapping[key] = session_id

    api = pd.read_csv(
        API_FILE,
        usecols=["station_id", "session_id"],
        dtype=str,
    )

    if api["session_id"].duplicated().any():
        raise ValueError("API contains duplicate session_id values.")

    api_mapping = {}

    for station_id, session_id in api[
        ["station_id", "session_id"]
    ].itertuples(index=False, name=None):
        key = (station_id, session_id)

        if key in api_mapping:
            raise ValueError(
                f"Duplicate API matching key: {key}"
            )

        api_mapping[key] = session_id

    static_keys = set(static_mapping)
    api_keys = set(api_mapping)

    matched = static_keys & api_keys
    static_only = static_keys - api_keys
    api_only = api_keys - static_keys

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as output:
        writer = csv.writer(output)

        writer.writerow([
            "station_id",
            "static_session_id",
            "api_session_id",
            "match_status",
        ])

        for key in sorted(matched):
            writer.writerow([
                key[0],
                static_mapping[key],
                api_mapping[key],
                "MATCHED",
            ])

        for key in sorted(static_only):
            writer.writerow([
                key[0],
                static_mapping[key],
                "",
                "STATIC_ONLY",
            ])

        for key in sorted(api_only):
            writer.writerow([
                key[0],
                "",
                api_mapping[key],
                "API_ONLY",
            ])

    print("Static sessions:", len(static_keys))
    print("API sessions:", len(api_keys))
    print("Matched sessions:", len(matched))
    print("Static only:", len(static_only))
    print("API only:", len(api_only))
    print("Invalid static IDs:", invalid_static_ids)
    if api_only:
        print("Sample API-only session IDs (first 5):")
        for _, session_id in sorted(api_only)[:5]:
            print("  ", session_id)
    if static_only:
        print("Sample Static-only session IDs (first 5):")
        for key in sorted(static_only)[:5]:
            print("  ", static_mapping[key])
    print("Mapping report:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
