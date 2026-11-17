"""Resumable delta refresh for ACN-Data JPL session metadata.

The regular sessions endpoint is capped at 25 records/page. This script therefore
does not try to increase page size. It compares API totals by UTC month with the
existing local snapshot and downloads only changed months. Use --full to force a
complete re-download.

Usage:
    python scripts/refresh_jpl_api_snapshot_delta.py
    python scripts/refresh_jpl_api_snapshot_delta.py --workers 2
    python scripts/refresh_jpl_api_snapshot_delta.py --full --workers 2
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from project_config import SITE_ID, RAW_API_DIR, RAW_API_FILE

BASE_URL = "https://ev.caltech.edu/api/v1"
ENDPOINT = f"{BASE_URL}/sessions/{SITE_ID}"
CHECKPOINT_DIR = RAW_API_DIR / f"{SITE_ID}_delta_refresh_checkpoint"
MAX_RETRIES = 8
BACKOFF_BASE = 2.0
BACKOFF_CAP = 30.0
TIMEOUT = (15, 90)
PAGE_PAUSE = 0.08
_tls = threading.local()


def get_token() -> str:
    load_dotenv(ROOT / ".env")
    token = os.getenv("ACN_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ACN_API_TOKEN is missing from the local .env file.")
    return token


def http_session() -> requests.Session:
    session = getattr(_tls, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": "EV-Charging-Analytics-JPL/2.0",
        })
        _tls.session = session
    return session


def wait_seconds(response: requests.Response | None, attempt: int) -> float:
    if response is not None:
        value = response.headers.get("Retry-After")
        if value:
            try:
                return min(float(value), BACKOFF_CAP)
            except ValueError:
                try:
                    dt = parsedate_to_datetime(value)
                    return max(0.0, min(
                        (dt - datetime.now(timezone.utc)).total_seconds(),
                        BACKOFF_CAP,
                    ))
                except Exception:
                    pass
    base = min(BACKOFF_BASE * (2 ** (attempt - 1)), BACKOFF_CAP)
    return base + random.uniform(0, min(1.0, base * 0.2))


def get_json(url: str, token: str, params=None, label="request") -> dict:
    last_error = None
    session = http_session()
    for attempt in range(1, MAX_RETRIES + 1):
        response = None
        try:
            response = session.get(
                url, params=params, auth=(token, ""), timeout=TIMEOUT
            )
            if response.status_code in (429, 500, 502, 503, 504):
                if attempt == MAX_RETRIES:
                    response.raise_for_status()
                delay = wait_seconds(response, attempt)
                print(
                    f"[Retry {attempt}/{MAX_RETRIES}] {label}: "
                    f"HTTP {response.status_code}; wait {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
                continue
            if response.status_code in (401, 403):
                raise RuntimeError(
                    f"ACN-Data rejected the token (HTTP {response.status_code}). "
                    "Check .env and API access."
                )
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"{label}: unexpected API response type.")
            return data
        except RuntimeError:
            raise
        except requests.RequestException as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                break
            delay = wait_seconds(response, attempt)
            print(
                f"[Retry {attempt}/{MAX_RETRIES}] {label}: "
                f"{type(exc).__name__}; wait {delay:.1f}s",
                flush=True,
            )
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after {MAX_RETRIES} attempts: {last_error}")


def parse_dt(value) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def record_month(row: dict) -> str:
    dt = parse_dt(row.get("connectionTime"))
    if dt is None:
        raise ValueError(f"Invalid connectionTime for session {row.get('sessionID')!r}")
    return dt.strftime("%Y-%m")


def shift_month(year: int, month: int, offset: int) -> tuple[int, int]:
    serial = year * 12 + month - 1 + offset
    return serial // 12, serial % 12 + 1


def month_labels(start: tuple[int, int], end: tuple[int, int]) -> list[str]:
    out = []
    y, m = start
    while (y, m) <= end:
        out.append(f"{y:04d}-{m:02d}")
        y, m = shift_month(y, m, 1)
    return out


def month_where(label: str) -> str:
    year, month = map(int, label.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    ny, nm = shift_month(year, month, 1)
    end = datetime(ny, nm, 1, tzinfo=timezone.utc)
    return (
        f'connectionTime>="{format_datetime(start, usegmt=True)}" '
        f'and connectionTime<"{format_datetime(end, usegmt=True)}"'
    )


def next_url(href: str) -> str:
    if href.startswith(("http://", "https://")):
        return href
    if href.startswith("/api/v1/"):
        return urljoin("https://ev.caltech.edu/", href)
    return urljoin(BASE_URL.rstrip("/") + "/", href.lstrip("/"))


def atomic_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, separators=(",", ":"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def global_total(token: str) -> int:
    data = get_json(ENDPOINT, token, label="global total")
    total = data.get("_meta", {}).get("total")
    if not isinstance(total, int):
        raise RuntimeError("Global API response has no integer _meta.total.")
    return total


def count_month(label: str, token: str) -> tuple[str, int]:
    data = get_json(
        ENDPOINT,
        token,
        params={"where": month_where(label), "sort": "-connectionTime"},
        label=f"count {label}",
    )
    total = data.get("_meta", {}).get("total")
    if not isinstance(total, int):
        raise RuntimeError(f"API has no integer _meta.total for {label}.")
    return label, total


def read_local() -> tuple[list[dict], dict[str, int]]:
    if not RAW_API_FILE.exists():
        raise FileNotFoundError(
            f"Snapshot not found: {RAW_API_FILE}. "
            "This script is a delta refresh and needs an existing JSON snapshot."
        )
    with RAW_API_FILE.open("r", encoding="utf-8") as stream:
        rows = json.load(stream)
    if not isinstance(rows, list):
        raise RuntimeError("Local snapshot must be a JSON list.")
    ids, counts = set(), {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise RuntimeError(f"Snapshot row {index} is not an object.")
        sid = row.get("sessionID")
        if not isinstance(sid, str) or not sid:
            raise RuntimeError(f"Snapshot row {index} has no sessionID.")
        if sid in ids:
            raise RuntimeError(f"Duplicate local sessionID: {sid}")
        ids.add(sid)
        key = record_month(row)
        counts[key] = counts.get(key, 0) + 1
    return rows, counts


def get_monthly_api_counts(
    token: str, total: int, local_counts: dict[str, int], workers: int
) -> dict[str, int]:
    existing_months = sorted(local_counts)
    if not existing_months:
        raise RuntimeError("Cannot determine month range from local snapshot.")
    first = tuple(map(int, existing_months[0].split("-")))
    last = tuple(map(int, existing_months[-1].split("-")))
    start = shift_month(first[0], first[1], -1)
    end = shift_month(last[0], last[1], 1)
    known: dict[str, int] = {}

    # Expand the date range if the sum of monthly counts does not cover _meta.total.
    for _ in range(5):
        labels = month_labels(start, end)
        missing = [m for m in labels if m not in known]
        if missing:
            print(
                f"Checking {len(missing)} monthly API counts with {workers} workers...",
                flush=True,
            )
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(count_month, m, token) for m in missing]
                for future in as_completed(futures):
                    label, count = future.result()
                    known[label] = count
                    print(f"  {label}: {count:,}", flush=True)

        summed = sum(known[m] for m in labels)
        print(f"Monthly totals sum={summed:,}; global total={total:,}", flush=True)
        if summed == total:
            return {m: known[m] for m in labels}
        if summed > total:
            raise RuntimeError(
                "Monthly totals exceed global total; date-filter windows may overlap. "
                "Snapshot was not changed."
            )
        start = shift_month(start[0], start[1], -12)
        end = shift_month(end[0], end[1], 12)

    raise RuntimeError(
        "Monthly count windows do not sum to global API total. Snapshot was not changed."
    )


def load_checkpoint_pages(folder: Path):
    rows, ids, last_page, last_next = [], set(), 0, None
    for path in sorted(folder.glob("page-*.json")):
        with path.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise RuntimeError(f"Invalid page checkpoint: {path}")
        page_no = int(path.stem.split("-")[1])
        last_page = max(last_page, page_no)
        last_next = payload.get("next_url")
        for row in payload["items"]:
            sid = row.get("sessionID") if isinstance(row, dict) else None
            if not sid or sid in ids:
                raise RuntimeError(f"Missing/duplicate ID in checkpoint page {path}")
            ids.add(sid)
            rows.append(row)
    return rows, ids, last_page, last_next


def fetch_month(label: str, expected: int, token: str):
    folder = CHECKPOINT_DIR / label
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / "state.json"
    query = month_where(label)
    state = {}
    if state_path.exists():
        with state_path.open("r", encoding="utf-8") as stream:
            state = json.load(stream)
        if state.get("expected") != expected or state.get("where") != query:
            raise RuntimeError(
                f"Checkpoint for {label} has a different API count/query. "
                f"Inspect or remove {folder} before retrying."
            )

    rows, ids, saved_page, saved_next = load_checkpoint_pages(folder)
    state_page = int(state.get("page", 0))
    if state_page > saved_page:
        raise RuntimeError(f"Checkpoint for {label} is ahead of saved page files.")
    # Recover if Ctrl+C happened after the page file write but before state.json.
    if saved_page > state_page:
        state = {
            "where": query, "expected": expected, "page": saved_page,
            "next_url": saved_next, "complete": saved_next is None,
        }
        atomic_json(state_path, state)

    if state.get("complete"):
        if len(rows) != expected:
            raise RuntimeError(f"Completed checkpoint {label}: {len(rows)} != {expected}")
        return label, rows

    page = saved_page
    if page == 0:
        url, params = ENDPOINT, {
            "where": query, "sort": "-connectionTime"
        }
    else:
        url, params = state.get("next_url") or saved_next, None
        if not url:
            raise RuntimeError(f"Checkpoint for {label} has no next URL.")

    while True:
        data = get_json(url, token, params=params, label=f"{label} page {page + 1}")
        params = None
        page_total = data.get("_meta", {}).get("total")
        if isinstance(page_total, int) and page_total != expected:
            raise RuntimeError(
                f"Monthly total changed for {label}: expected {expected}, got {page_total}"
            )

        items = data.get("_items", [])
        if not isinstance(items, list):
            raise RuntimeError(f"Invalid _items for {label}.")
        if not items:
            if expected == 0 and page == 0:
                atomic_json(state_path, {
                    "where": query, "expected": expected, "page": 0,
                    "next_url": None, "complete": True,
                })
                return label, []
            raise RuntimeError(f"Empty page before expected end for {label}.")

        page_ids = set()
        for row in items:
            sid = row.get("sessionID") if isinstance(row, dict) else None
            if not sid or sid in ids or sid in page_ids:
                raise RuntimeError(f"Missing/duplicate sessionID in {label} page.")
            page_ids.add(sid)

        links = data.get("_links", {})
        next_link = links.get("next") if isinstance(links, dict) else None
        href = next_link.get("href") if isinstance(next_link, dict) else None
        following = next_url(href) if href else None

        page += 1
        atomic_json(folder / f"page-{page:05d}.json", {
            "items": items, "next_url": following
        })
        rows.extend(items)
        ids.update(page_ids)

        complete = following is None
        atomic_json(state_path, {
            "where": query, "expected": expected, "page": page,
            "next_url": following, "complete": complete,
        })
        print(f"  [{label}] page={page} saved={len(rows):,}/{expected:,}", flush=True)

        if len(rows) > expected:
            raise RuntimeError(f"Downloaded more rows than expected for {label}.")
        if complete:
            break
        url = following
        time.sleep(PAGE_PAUSE)

    if len(rows) != expected:
        raise RuntimeError(
            f"{label} ended with {len(rows):,} sessions; API count is {expected:,}. "
            "Checkpoint is preserved."
        )
    return label, rows


def atomic_replace_snapshot(
    local_rows, new_by_month, changed_months, api_month_counts, api_total
):
    combined = [
        row for row in local_rows
        if record_month(row) not in changed_months
    ]
    for month in sorted(new_by_month):
        combined.extend(new_by_month[month])

    ids, counts = set(), {}
    for row in combined:
        sid = row.get("sessionID")
        if not sid or sid in ids:
            raise RuntimeError(f"Missing or duplicate sessionID in final result: {sid!r}")
        ids.add(sid)
        m = record_month(row)
        counts[m] = counts.get(m, 0) + 1

    if len(combined) != api_total:
        raise RuntimeError(
            f"Final total {len(combined):,} does not equal API total {api_total:,}. "
            "Existing snapshot was preserved."
        )

    all_months = set(api_month_counts) | set(counts)
    differences = {
        m: (api_month_counts.get(m, 0), counts.get(m, 0))
        for m in all_months
        if api_month_counts.get(m, 0) != counts.get(m, 0)
    }
    if differences:
        raise RuntimeError(
            f"Final monthly counts differ from API: {differences}. "
            "Existing snapshot was preserved."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = RAW_API_FILE.with_name(
        f"{RAW_API_FILE.stem}.backup_{stamp}{RAW_API_FILE.suffix}"
    )
    shutil.copy2(RAW_API_FILE, backup)
    atomic_json(RAW_API_FILE, combined)

    print("\n===== DELTA REFRESH COMPLETED =====")
    print(f"Final sessions: {len(combined):,}")
    print(f"Unique sessionIDs: {len(ids):,}")
    print(f"Months re-downloaded: {len(new_by_month):,}")
    print(f"Sessions re-downloaded: {sum(len(v) for v in new_by_month.values()):,}")
    print(f"Backup: {backup}")
    print(f"Snapshot: {RAW_API_FILE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=2, choices=(1, 2, 3, 4),
        help="Concurrent month workers. Default 2; use 1 if 502s increase.",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Re-download every month; slower, but checks all records.",
    )
    args = parser.parse_args()

    if SITE_ID != "jpl":
        raise RuntimeError(f"Expected SITE_ID=jpl, got {SITE_ID!r}")

    token = get_token()
    RAW_API_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

    print("===== JPL API DELTA REFRESH =====")
    print(f"Workers: {args.workers}")
    print("The existing JSON file will not be replaced until validation passes.")

    total = global_total(token)
    print(f"Live API total: {total:,}")
    local_rows, local_counts = read_local()
    print(f"Local snapshot: {len(local_rows):,} unique sessions")

    api_month_counts = get_monthly_api_counts(
        token, total, local_counts, args.workers
    )
    changed = {
        month for month, api_count in api_month_counts.items()
        if args.full or local_counts.get(month, 0) != api_count
    }

    if not changed:
        if len(local_rows) != total:
            raise RuntimeError(
                "Monthly counts match but global count differs. "
                "Try --full to perform a complete reconciliation."
            )
        print("Snapshot already matches API monthly/global counts. Nothing to download.")
        return

    print("\n===== DELTA PLAN =====")
    print(f"Months to refresh: {len(changed)}")
    for month in sorted(changed):
        print(
            f"  {month}: local={local_counts.get(month, 0):,}; "
            f"API={api_month_counts[month]:,}"
        )
    print(
        "Records to download: "
        f"{sum(api_month_counts[m] for m in changed):,}"
    )

    new_by_month = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(fetch_month, m, api_month_counts[m], token): m
            for m in sorted(changed)
        }
        for future in as_completed(futures):
            month, rows = future.result()
            new_by_month[month] = rows
            print(f"[DONE] {month}: {len(rows):,} sessions", flush=True)

    atomic_replace_snapshot(
        local_rows, new_by_month, changed, api_month_counts, total
    )


if __name__ == "__main__":
    main()
