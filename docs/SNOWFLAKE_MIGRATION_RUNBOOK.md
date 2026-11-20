# Snowflake migration runbook — JPL EV Charging Analytics

**Cập nhật:** 20/11/2026  
**Database:** `JPL_ANALYTICS` · **Warehouse:** `JPL_ETL_WH`  
**Streamlit app:** `JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD`

## 1. Trạng thái triển khai

Lần triển khai đầy đủ ngày 18/11/2026 đã hoàn thành các bước:
- Tạo database, năm schemas, X-Small warehouse, file format và internal stage.
- Tạo RAW landing tables.
- Nạp API sessions, userInputs, mapping và toàn bộ Static.
- Xây dựng dimensions, facts, full-Static view và Power marts.
- Chạy SQL validation Q1–Q5.
- Tạo Streamlit app và publish live version.

Các kết quả đã xác nhận từ log triển khai và ảnh Snowsight:

| Hạng mục | Giá trị |
|---|---:|
| API sessions | 33.638 |
| User input records | 41.207 |
| Full Static measurement rows | 175.390.901 |
| Static rows mapped to API | 164.438.039 |
| Static rows not mapped to API (STATIC_ONLY) | 10.952.862 |
| Q3 valid sessions | 25.647 |
| Q3 median / P95 post-last-current | 124,6167 / 478,995 phút |
| Q4 latest valid request sessions | 31.444 |
| Q4 median delivered/requested | 60,08875% |
| Q5 UTC hours with observation | 2.240 / 3.673 |
| Streamlit live version | Published |

**Grain cần phân biệt:** 164.438.039 và 10.952.862 là measurement rows; 25.647 là số phiên MATCHED.

Nhánh hardening hiện tại bổ sung code kiểm soát chất lượng, tách SQL và cải thiện giao diện. Những sửa đổi này chưa tự động được áp dụng vào app đang chạy trên Snowflake cho đến khi merge và thực hiện bước app-only deployment.

## 2. Kiến trúc

| Layer | Object | Grain / mục đích |
|---|---|---|
| Stage | `RAW.JPL_RAW_STAGE` | Landing files CSV/CSV.GZ |
| RAW | `STG_CHARGING_SESSIONS` | API session |
| RAW | `STG_USER_INPUTS` | Mỗi lần userInputs cập nhật |
| RAW | `STG_STATIC_MEASUREMENTS` | Mỗi phép đo Static |
| RAW | `STG_SESSION_MAPPING` | Mapping giữa Static/API sessions |
| RAW | `LOAD_AUDIT` | File, row count và lineage của từng lần nạp |
| WAREHOUSE | `DIM_STATION`, `DIM_USER`, `DIM_DATE`, `DIM_TIME` | Dimensions |
| WAREHOUSE | `FACT_CHARGING_SESSIONS` | Một dòng/session |
| WAREHOUSE | `FACT_USER_REQUESTS` | Một dòng/input event |
| WAREHOUSE | `FACT_STATIC_MEASUREMENTS` | View full Static, gồm cả unmatched rows |
| MART | `SESSION_LAST_CURRENT`, `SESSION_POST_CURRENT` | Mốc current dương cuối và thời gian đến disconnect |
| MART | `POWER_STATION_HOUR`, `POWER_STATION_MONTH` | EVSE-hour / EVSE-month |
| MART | `POWER_SITE_HOUR` | Complete UTC-hour grid |
| MART | `POWER_HOUR_OF_DAY_PROFILE` | Profile Power theo giờ |
| ANALYTICS | `JPL_EV_CHARGING_DASHBOARD` | Streamlit Q1–Q5 |

Full Static chỉ được lưu một lần ở RAW; WAREHOUSE Static object là view. Các bảng tổng hợp được materialize để phục vụ dashboard.

## 3. Nguồn dữ liệu và phạm vi

- ACN-Data API site alias: `jpl`.
- Static folder: `time series data/jpl/Arroyo_Garage_01`.
- Local timezone: `America/Los_Angeles`.
- Static snapshot inventory: 27.723 file, 52 historical station IDs, khoảng ngày 2018-10-08 đến 2020-12-02.
- Power analysis window: 2020-07-01 đến trước 2020-12-01.

Power được giới hạn ở tháng 07–11/2020 vì các trường Power/Voltage không được lưu đồng đều trong lịch sử sớm; tháng 06/2020 là giai đoạn chuyển tiếp và tháng 12 chỉ có dữ liệu đến ngày 02/12.

Static là dữ liệu đo theo phiên, không phải telemetry 24/7. Thiếu quan sát không có nghĩa EVSE hỏng hoặc Power = 0. Station-hour averages giữa các EVSE không bảo đảm đồng bộ timestamp; không cộng chúng thành tổng phụ tải đồng thời của toàn site.

## 4. Kiểm soát chi phí

Warehouse `JPL_ETL_WH` được cấu hình:
- Size: X-SMALL.
- AUTO_RESUME: TRUE.
- AUTO_SUSPEND: 60 giây.
- INITIALLY_SUSPENDED: TRUE.

Không chạy full Static load chỉ để sửa UI/SQL dashboard. File Static nén có dung lượng lớn; mỗi lần chạy lại `-IncludeStatic` sẽ upload và COPY lại file đó.

## 5. Credentials và môi trường

Credentials chỉ lưu trong file local `.env`, không đưa lên GitHub hoặc ảnh chụp màn hình.

Biến cần thiết tùy cơ chế xác thực:
- `SNOWFLAKE_ACCOUNT`
- `SNOWFLAKE_USER` (không cần truyền riêng khi dùng OAuth Authorization Code)
- `SNOWFLAKE_PASSWORD` (chỉ cho password authentication)
- `SNOWFLAKE_ROLE` (tùy chọn)
- `SNOWFLAKE_WAREHOUSE=JPL_ETL_WH`
- `SNOWFLAKE_AUTHENTICATOR` (nếu dùng SSO)

`snowflake/environment.yml` dùng Conda/Snowflake Anaconda Channel để khai báo các package ứng dụng. Warehouse Runtime hiện mặc định cung cấp Python 3.11; vì vậy file không liệt kê `python=3.11` như một package. Runtime được chỉ định rõ là `SYSTEM$WAREHOUSE_RUNTIME` trong lệnh tạo Streamlit. Python version có thể xác nhận/chọn trong Packages → Python Version ở Snowsight.

## 6. Vận hành

### 6.1. Cập nhật riêng dashboard (khuyến nghị khi sửa UI/SQL)

Sau khi merge nhánh hardening và pull code mới:

```powershell
git pull
.\scripts\run_snowflake_deploy.ps1 -AppOnly
```

Lệnh `-AppOnly` chỉ:
- Upload `streamlit_app.py`.
- Upload `analytics_queries.py`.
- Upload `environment.yml`.
- Tạo lại Streamlit object và publish live version.

Lệnh này không nạp dữ liệu, không chạy các SQL build warehouse/marts và không quét lại 175M Static rows.

### 6.2. Áp dụng thay đổi schema audit mà không nạp lại dữ liệu

Nhánh hardening bổ sung các cột `RUN_ID`, `FILE_SIZE_BYTES`, `SOURCE_SHA256`, `COPY_QUERY_ID` cho `RAW.LOAD_AUDIT`.

Có thể chạy `snowflake/01_raw_staging.sql` trong Snowsight để áp dụng các lệnh `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Các lệnh này không tải lại dữ liệu.

Sau đó chạy `snowflake/05_data_quality.sql` trong Snowsight để kiểm tra uniqueness, mapping, reconciliation và complete site-hour grid.

### 6.3. Full data deployment

Chỉ chạy khi thực sự muốn nạp lại toàn bộ nguồn đã xử lý:

```powershell
.\scripts\run_snowflake_deploy.ps1 -IncludeStatic
```

Nếu API tables đã đúng và chỉ muốn nạp lại Static:

```powershell
.\scripts\run_snowflake_deploy.ps1 -IncludeStatic -SkipCoreLoad
```

Script nạp file qua PUT/COPY INTO, dùng temporary table và chỉ thay thế bảng RAW sau khi COPY thành công. Mỗi lần chạy tạo một `RUN_ID`; file audit lưu size, SHA-256 và COPY query ID.

## 7. Validation

Chạy trong Snowsight theo thứ tự:

1. `snowflake/04_validation.sql` — row counts và kết quả Q1–Q5.
2. `snowflake/05_data_quality.sql` — bảng check_name, observed_value, expected_value, status và details.

Các check mới gồm:
- Duplicate session key.
- Duplicate (session_id, input_id) request key.
- Duplicate non-null Static mapping key (API_ONLY rows have no Static key and are excluded).
- Duplicate non-null API mapping key.
- Duplicate station/date/time dimension keys.
- Orphan DATE_KEY/TIME_KEY trong charging-session fact.
- Static row reconciliation.
- Unmapped Static rows.
- Orphan station keys.
- Invalid post-last-current intervals.
- Đủ 3.673 UTC hours và không trùng UTC hour key.
- Session/Static facts không rỗng.

Data-quality gate đầy đủ chỉ áp dụng khi Static đã được nạp. API-first deployment có thể chạy trước; khi Static chưa có dữ liệu, các check phụ thuộc Static được trì hoãn.

### Diễn giải coverage

- Power row coverage = non-null Power measurement rows / all Static rows trong cửa sổ.
- Site-hour observation coverage = UTC hours có ít nhất một quan sát / 3.673 UTC hours.
- 100% Power row coverage không đồng nghĩa 100% temporal coverage.
- 2.240 / 3.673 = khoảng 61,0% site-hour observation coverage.

Truy vấn tổng hợp station-month trong `04_validation.sql` sử dụng fixed 50-station population. Station-month không có row quan sát được đưa vào mẫu số với coverage 0%, giúp kết quả tương thích với heatmap dashboard.

## 8. Kiểm thử repository

Từ repository root:

```powershell
python -m unittest discover -s tests -v
python -m py_compile scripts/deploy_snowflake.py snowflake/streamlit_app.py snowflake/analytics_queries.py
```

GitHub Actions chạy compile và unit/regression tests trên push/PR. CI không thay thế SQL smoke test trên account Snowflake.

## 9. Bằng chứng triển khai

Nên lưu trong thư mục `docs/evidence/snowflake/`:
1. Snowsight database/schema và object list.
2. Query result đối soát 33.638 sessions, 41.207 userInputs, 175.390.901 Static rows.
3. Query result Q3, Q4, Q5.
4. Kết quả toàn bộ `05_data_quality.sql`.
5. Streamlit dashboard Q1–Q5.
6. GitHub Actions run cuối cùng.
7. Load audit thể hiện RUN_ID, source file, row count, SHA-256 và COPY query ID.

Không chụp credentials, token hoặc thông tin đăng nhập trong ảnh minh chứng.
