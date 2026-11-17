from pathlib import Path
from urllib.parse import quote
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from project_config import SITE_ID, RAW_API_DIR, RAW_API_FILE

load_dotenv(PROJECT_ROOT / ".env")
BASE_URL = "https://ev.caltech.edu/api/v1"
CHECKPOINT_FILE = RAW_API_DIR / f"{SITE_ID}_checkpoint.json"

PAGE_SIZE = 50  # Size 50 nhẹ hơn 100 rất nhiều, tránh làm treo worker của Caltech
WINDOW_RESET_PAGES = 20  # Cứ mỗi 20 trang (1.000 bản ghi) thì trượt mốc thời gian 1 lần để page luôn nhỏ


def get_token() -> str:
    token = os.getenv("ACN_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ACN_API_TOKEN is missing. Register at https://ev.caltech.edu and put the key in .env."
        )
    return token


def load_checkpoint() -> list[dict]:
    if CHECKPOINT_FILE.exists():
        try:
            with CHECKPOINT_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "sessions" in data:
                return data["sessions"]
            if isinstance(data, list):
                return data
        except Exception as e:
            print(f"[Cảnh báo] Không đọc được checkpoint cũ ({e}), sẽ tải mới.")
    return []


def save_checkpoint(sessions: list[dict]) -> None:
    temp_cp = CHECKPOINT_FILE.with_suffix(".tmp")
    with temp_cp.open("w", encoding="utf-8") as f:
        json.dump({"last_page": len(sessions) // PAGE_SIZE, "sessions": sessions}, f, ensure_ascii=False)
    temp_cp.replace(CHECKPOINT_FILE)


def fetch_with_cooldown(client: requests.Session, url: str, token: str) -> dict:
    """Gọi API kiên trì với thời gian nghỉ (cooldown) dài khi server Caltech bị treo 502."""
    attempt = 0
    while True:
        attempt += 1
        try:
            response = client.get(url, auth=(token, ""), timeout=(15, 60))
            if response.status_code in (401, 403):
                raise RuntimeError(f"Token bị từ chối (HTTP {response.status_code}).")
            if response.status_code == 404:
                return {"_items": [], "_meta": {}}
            if response.status_code in (500, 502, 503, 504):
                # Nghỉ dài (10s, 20s, 30s...) để worker của Caltech kịp khởi động lại
                wait = min(10 * attempt, 60)
                print(f"  [!] Server Caltech quá tải (HTTP {response.status_code}). Đợi {wait}s cho server hồi phục (lần thử {attempt})...", flush=True)
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            wait = min(10 * attempt, 60)
            print(f"  [!] Mạng/Server timeout ({e}). Đợi {wait}s rồi thử lại (lần {attempt})...", flush=True)
            time.sleep(wait)


def build_url(cursor_time: str | None, page: int) -> str:
    base = f"{BASE_URL}/sessions/{SITE_ID}?max_results={PAGE_SIZE}&sort=connectionTime&page={page}"
    if cursor_time:
        # Lọc lấy các phiên có connectionTime >= mốc cuối cùng vừa tải
        where_clause = quote(f'connectionTime>="{cursor_time}"')
        return f"{base}&where={where_clause}"
    return base


def extract_sessions() -> list[dict]:
    token = get_token()
    sessions = load_checkpoint()
    seen_ids = {s.get("sessionID") for s in sessions if isinstance(s, dict) and s.get("sessionID")}

    # Nếu đã có dữ liệu trong checkpoint, lấy connectionTime của bản ghi cuối cùng làm mốc trượt
    cursor_time: str | None = None
    if sessions:
        cursor_time = sessions[-1].get("connectionTime")
        print(
            f"==> Khôi phục từ Checkpoint: Đã có {len(sessions):,} sessions.\n"
            f"==> Bắt đầu trượt mốc thời gian từ: {cursor_time} (giúp page luôn bắt đầu lại từ 1!)",
            flush=True,
        )

    with requests.Session() as client:
        client.headers.update({"Accept": "application/json", "User-Agent": "EV-Charging-Analytics-JPL/1.0"})

        # Lấy tổng số bản ghi thực tế trên toàn site để đối chiếu
        meta_payload = fetch_with_cooldown(client, f"{BASE_URL}/sessions/{SITE_ID}?max_results=1", token)
        total_api_records = meta_payload.get("_meta", {}).get("total", 33638)

        page_in_window = 1
        batch_num = 0

        while True:
            batch_num += 1
            url = build_url(cursor_time, page_in_window)
            payload = fetch_with_cooldown(client, url, token)
            items = payload.get("_items", [])

            if not items:
                print("==> Đã tải hết toàn bộ dữ liệu từ API!", flush=True)
                break

            new_items = []
            for item in items:
                if isinstance(item, dict):
                    sid = item.get("sessionID")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        new_items.append(item)

            sessions.extend(new_items)
            save_checkpoint(sessions)

            last_item_time = items[-1].get("connectionTime", "")
            print(
                f"[Batch {batch_num} | Window Page {page_in_window}] +{len(new_items):,} mới "
                f"| Tổng đã lưu={len(sessions):,}/{total_api_records:,} | Mốc: {last_item_time}",
                flush=True,
            )

            # Nếu số lượng trả về ít hơn PAGE_SIZE thì đã tới trang cuối cùng của toàn bộ dữ liệu
            if len(items) < PAGE_SIZE:
                print("==> Đã chạm tới trang cuối cùng của dữ liệu JPL!", flush=True)
                break

            # Cứ sau 20 trang (1.000 bản ghi), cập nhật lại mốc cursor_time và reset page về 1
            # để MongoDB phía Caltech không bao giờ phải chạy lệnh skip() quá sâu!
            if page_in_window >= WINDOW_RESET_PAGES and last_item_time and last_item_time != cursor_time:
                cursor_time = last_item_time
                page_in_window = 1
                print(f"  --> [Tối ưu] Trượt mốc thời gian sang '{cursor_time}', reset về Page 1 để tăng tốc!", flush=True)
            else:
                page_in_window += 1

            time.sleep(0.25)

    if not sessions:
        raise RuntimeError("Không thu thập được phiên sạc nào.")
    return sessions


def main() -> None:
    RAW_API_DIR.mkdir(parents=True, exist_ok=True)
    sessions = extract_sessions()

    temp_file = RAW_API_FILE.with_suffix(RAW_API_FILE.suffix + ".tmp")
    with temp_file.open("w", encoding="utf-8") as f:
        json.dump(sessions, f, ensure_ascii=False)
    temp_file.replace(RAW_API_FILE)

    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()

    station_ids = {s.get("stationID") for s in sessions if s.get("stationID")}
    starts = [s.get("connectionTime") for s in sessions if s.get("connectionTime")]
    print("\n===== JPL API EXTRACTION COMPLETED =====")
    print(f"Site: {SITE_ID}")
    print(f"Sessions collected: {len(sessions):,}")
    print(f"Unique station IDs in API: {len(station_ids):,}")
    print(f"Connection-time values: {len(starts):,}")
    print(f"Output: {RAW_API_FILE}")


if __name__ == "__main__":
    main()