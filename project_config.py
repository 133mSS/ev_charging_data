"""Central configuration for the JPL ACN-Data project."""
from pathlib import Path
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

SITE_ID = os.getenv("ACN_SITE_ID", "jpl").strip().lower()
if SITE_ID != "jpl":
    raise ValueError(
        f"This migration build is scoped to JPL. ACN_SITE_ID={SITE_ID!r} is not supported."
    )

STATIC_REPO = Path(
    os.getenv("ACN_STATIC_REPO", str(PROJECT_ROOT / "external" / "ACN-Data-Static"))
).expanduser()
STATIC_SITE_RELATIVE = Path("time series data") / "jpl" / "Arroyo_Garage_01"
STATIC_SOURCE_DIR = Path(
    os.getenv("ACN_STATIC_DATA_DIR", str(STATIC_REPO / STATIC_SITE_RELATIVE))
).expanduser()

RAW_API_DIR = PROJECT_ROOT / "data" / "raw" / "api"
RAW_STATIC_DIR = STATIC_SOURCE_DIR
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed" / "jpl"

RAW_API_FILE = RAW_API_DIR / f"{SITE_ID}_sessions.json"
CLEAN_SESSIONS_FILE = PROCESSED_DIR / f"{SITE_ID}_sessions_cleaned.csv"
CLEAN_USER_INPUTS_FILE = PROCESSED_DIR / f"{SITE_ID}_user_inputs_cleaned.csv"
CLEAN_STATIC_FILE = PROCESSED_DIR / f"{SITE_ID}_measurements_cleaned.csv.gz"
SESSION_MAPPING_FILE = PROCESSED_DIR / f"{SITE_ID}_static_api_session_mapping.csv"
SESSION_QUALITY_FILE = PROCESSED_DIR / f"{SITE_ID}_static_api_session_quality.csv"
MATCHED_STATIC_FILE = PROCESSED_DIR / f"{SITE_ID}_static_measurements_matched.csv.gz"
