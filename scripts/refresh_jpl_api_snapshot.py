"""Download the complete JPL ACN-Data session snapshot using official HATEOAS pagination.

- Uses the API-provided _links.next (does not calculate page numbers).
- Saves every page atomically, so Ctrl+C can be resumed without losing completed pages.
- Verifies unique sessionID count against _meta.total before replacing the current snapshot.
- Keeps a timestamped backup of the old snapshot.

Run from the project root:
    python scripts/refresh_jpl_api_snapshot.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from project_config import SITE_ID, RAW_API_DIR, RAW_API_FILE

BASE_URL = "https://ev.caltech.edu/api/v1"
START_URL = f"{BASE_URL}/sessions/{SITE_ID}"
PAGES_DIR = RAW_API_DIR / f"{SITE_ID}_api_refresh_pages"
MANIFEST_FILE = PAGES_DIR / "manifest.json"
PAGE_RE = re.compile(r"^page_(\d{6})\.json$")
MAX_RETRIES = 8


def atomic_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def resolve_next_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/api/v1/"):
        return "https://ev.caltech.edu" + href
    if href.startswith("/"):
        return BASE_URL + href
    return urljoin(BASE_URL + "/", href)


def get_next_href(payload: dict) -> str | None:
    links = payload.get("_links")
    if not isinstance(links, dict):
        return None
    nxt = links.get("next")
    if not isinstance(nxt, dict):
        return None
    href = nxt.get("href")
    return href if isinstance(href, str) and href.strip() else None


def request_json(session: requests.Session, url: str, token: str) -> dict:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, auth=(token, ""), timeout=(20, 120))
            if response.status_code in (401, 403):
                raise RuntimeError(
                    f"ACN-Data rejected the token (HTTP {response.status_code}). "
                    "Check ACN_API_TOKEN in .env; token value is never printed."
                )
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(15 * attempt, 120)
                print(f"Rate limited (429); waiting {wait}s before retry {attempt}/{MAX_RETRIES}.", flush=True)
                time.sleep(wait)
                continue
            if response.status_code in (500, 502, 503, 504):
                wait = min(10 * attempt, 90)
                print(f"Server error {response.status_code}; waiting {wait}s before retry {attempt}/{MAX_RETRIES}.", flush=True)
                time.sleep(wait)
                continue
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("_items"), list):
                raise RuntimeError("Unexpected ACN-Data page format: _items is not a list.")
            return payload
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise RuntimeError(f"API request failed after {MAX_RETRIES} attempts: {exc}") from exc
            wait = min(10 * attempt, 90)
            print(f"Network error; waiting {wait}s before retry {attempt}/{MAX_RETRIES}: {exc}", flush=True)
            time.sleep(wait)
    raise RuntimeError("Unreachable retry state")


def existing_page_files() -> list[Path]:
    files = []
    if PAGES_DIR.exists():
        for p in PAGES_DIR.iterdir():
            m = PAGE_RE.match(p.name)
            if m and p.is_file():
                files.append((int(m.group(1)), p))
    files.sort(key=lambda x: x[0])
    expected = list(range(1, len(files) + 1))
    actual = [n for n, _ in files]
    if actual != expected:
        raise RuntimeError(
            f"Refresh page files are not contiguous. Found page numbers {actual[:5]}...; "
            "inspect the refresh folder before continuing."
        )
    return [p for _, p in files]


def load_saved_pages() -> tuple[list[dict], str | None, int | None, int]:
    pages = existing_page_files()
    sessions: list[dict] = []
    seen: set[str] = set()
    next_url: str | None = None
    expected_total: int | None = None

    for idx, path in enumerate(pages, start=1):
        with path.open("r", encoding="utf-8") as f:
            page = json.load(f)
        items = page.get("items")
        if not isinstance(items, list):
            raise RuntimeError(f"Invalid saved page: {path}")
        if idx == 1:
            expected_total = page.get("total")
        elif page.get("total") != expected_total:
            raise RuntimeError("API _meta.total changed during the saved refresh; do not combine snapshots.")
        for item in items:
            sid = item.get("sessionID") if isinstance(item, dict) else None
            if not sid:
                raise RuntimeError(f"Saved page {path.name} contains a row without sessionID.")
            if sid in seen:
                raise RuntimeError(f"Duplicate sessionID across saved API pages: {sid}")
            seen.add(sid)
            sessions.append(item)
        next_url = page.get("next_url")
        if idx < len(pages) and not next_url:
            raise RuntimeError(f"Saved page {path.name} has no next link but later pages exist.")

    return sessions, next_url, expected_total, len(pages)


def main() -> None:
    load_dotenv(ROOT / ".env")
    token = os.getenv("ACN_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("ACN_API_TOKEN is missing from .env. Token will not be requested in chat or printed.")
    if SITE_ID != "jpl":
        raise RuntimeError(f"This refresh utility is JPL-only; SITE_ID={SITE_ID!r}.")

    RAW_API_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    if MANIFEST_FILE.exists():
        with MANIFEST_FILE.open("r", encoding="utf-8") as f:
            old_manifest = json.load(f)
        if old_manifest.get("complete") is True:
            print("A complete refresh already exists in:", PAGES_DIR)
            print("Current API snapshot:", RAW_API_FILE)
            print("To intentionally create another full refresh, archive/remove the refresh folder first.")
            return

    saved_sessions, url, saved_total, page_count = load_saved_pages()
    if page_count == 0:
        url = START_URL
    seen_ids = {row["sessionID"] for row in saved_sessions}
    print("===== JPL API FULL REFRESH (HATEOAS + CHECKPOINT) =====")
    print(f"Previously completed pages: {page_count:,}")
    print(f"Previously saved sessions: {len(saved_sessions):,}")

    visited_urls: set[str] = set()
    for page_path in existing_page_files():
        with page_path.open("r", encoding="utf-8") as f:
            saved_page = json.load(f)
        visited_urls.add(saved_page.get("request_url", ""))

    with requests.Session() as client:
        client.headers.update({
            "Accept": "application/json",
            "User-Agent": "EV-Charging-Analytics-JPL/1.1 (+checkpointed full snapshot refresh)",
        })
        while url:
            if url in visited_urls:
                raise RuntimeError(f"Pagination loop detected at {url}")
            visited_urls.add(url)
            payload = request_json(client, url, token)
            items = payload["_items"]
            meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
            total = meta.get("total")
            if not isinstance(total, int) or total <= 0:
                raise RuntimeError(f"Missing/invalid _meta.total in API page: {meta}")
            if saved_total is not None and total != saved_total:
                raise RuntimeError(
                    f"API total changed during resume: checkpoint={saved_total}, live={total}. "
                    "Start a fresh refresh directory rather than mixing snapshots."
                )
            saved_total = total

            new_items = []
            for item in items:
                if not isinstance(item, dict) or not item.get("sessionID"):
                    raise RuntimeError("API page contains a non-object or missing sessionID.")
                sid = item["sessionID"]
                if sid in seen_ids:
                    raise RuntimeError(
                        f"Duplicate sessionID across API pages: {sid}. "
                        "Stop rather than silently dropping records."
                    )
                seen_ids.add(sid)
                new_items.append(item)

            next_href = get_next_href(payload)
            next_url = resolve_next_url(next_href) if next_href else None
            page_count += 1
            page_path = PAGES_DIR / f"page_{page_count:06d}.json"
            atomic_json(page_path, {
                "request_url": url,
                "total": total,
                "items": new_items,
                "next_url": next_url,
            })
            atomic_json(MANIFEST_FILE, {
                "site_id": SITE_ID,
                "total_expected": total,
                "pages_saved": page_count,
                "unique_sessions_saved": len(seen_ids),
                "next_url": next_url,
                "updated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "complete": False,
            })
            print(
                f"Page {page_count:,}: +{len(new_items):,} sessions | "
                f"unique saved={len(seen_ids):,}/{total:,}",
                flush=True,
            )
            url = next_url
            time.sleep(0.15)

    # Rebuild the final snapshot from durable pages, then validate before replacement.
    final_sessions, _, final_total, final_pages = load_saved_pages()
    if final_total != saved_total:
        raise RuntimeError(f"Final total mismatch: page total={saved_total}, saved manifest={final_total}")
    unique_count = len({row["sessionID"] for row in final_sessions})
    if unique_count != saved_total:
        raise RuntimeError(
            f"Incomplete API snapshot: unique sessionIDs={unique_count:,}; API _meta.total={saved_total:,}. "
            "Current snapshot was not replaced. Rerun this script to resume."
        )

    # Ensure all rows are from the requested JPL endpoint's single internal site code.
    site_codes = sorted({str(x.get("siteID")) for x in final_sessions if x.get("siteID") is not None})
    if len(site_codes) != 1:
        raise RuntimeError(f"Expected one payload siteID; found {site_codes}. Current snapshot was not replaced.")

    temp_file = RAW_API_FILE.with_suffix(RAW_API_FILE.suffix + ".refresh.tmp")
    atomic_json(temp_file, final_sessions)
    if RAW_API_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = RAW_API_FILE.with_name(f"{RAW_API_FILE.stem}.before_refresh_{stamp}{RAW_API_FILE.suffix}")
        shutil.copy2(RAW_API_FILE, backup)
        print(f"Previous snapshot backup: {backup}")
    temp_file.replace(RAW_API_FILE)

    atomic_json(MANIFEST_FILE, {
        "site_id": SITE_ID,
        "payload_site_ids": site_codes,
        "total_expected": saved_total,
        "pages_saved": final_pages,
        "unique_sessions_saved": unique_count,
        "updated_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "complete": True,
        "output_file": str(RAW_API_FILE),
    })
    print("\n===== JPL API REFRESH COMPLETED =====")
    print(f"API _meta.total: {saved_total:,}")
    print(f"Unique sessionID: {unique_count:,}")
    print(f"Pages saved: {final_pages:,}")
    print(f"Payload siteID: {site_codes}")
    print(f"Output: {RAW_API_FILE}")
    print("The previous snapshot was backed up before replacement.")


if __name__ == "__main__":
    main()
