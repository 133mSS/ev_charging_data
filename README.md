# JPL EV Charging Analytics

**Đồ án môn Trực quan hóa dữ liệu** — phân tích dữ liệu sạc xe điện thực tế tại JPL Arroyo Garage 01 bằng Python, Pandas, SQL, Snowflake và Streamlit.

> **Trạng thái dự án (20/11/2026):** dữ liệu API và toàn bộ Static đã được nạp lên Snowflake; warehouse, Power marts, truy vấn Q1–Q5 và Streamlit app đã được tạo. Lần triển khai đầy đủ được ghi nhận ngày 18/11/2026. Nhánh hardening bổ sung kiểm soát chất lượng, tách SQL khỏi giao diện và chuẩn hóa tài liệu; cần chạy `-AppOnly` sau khi merge để cập nhật mã dashboard lên Snowflake.

## 1. Mục tiêu và phạm vi

Project phân tích:
1. Nhu cầu sạc thay đổi theo ngày trong tuần và giờ bắt đầu như thế nào?
2. Mức sử dụng ghi nhận khác nhau giữa các EVSE ra sao?
3. Xe kết nối trong bao lâu và còn kết nối bao lâu sau mẫu dòng điện dương cuối cùng?
4. Năng lượng thực nhận so với yêu cầu cuối cùng được ghi nhận như thế nào?
5. Power quan sát và độ bao phủ phép đo thay đổi theo thời gian ra sao?

**Phạm vi dữ liệu:** ACN-Data site alias `jpl`, khu vực Static `Arroyo_Garage_01`, múi giờ địa phương `America/Los_Angeles`.

Trang ACN-Data mô tả JPL có 50 EVSE. Snapshot Static được kiểm kê có 52 station ID lịch sử; đây là các mã xuất hiện trong archive theo thời gian, không phải 52 EVSE hoạt động đồng thời.

## 2. Nguồn dữ liệu và quy mô

Hai luồng dữ liệu thuộc cùng hệ sinh thái ACN-Data:

| Nguồn | Dữ liệu | Vai trò |
|---|---|---|
| ACN-Data REST API `/api/v1/sessions/jpl` | Session metadata, thời gian kết nối/ngắt kết nối, station, kWhDelivered và userInputs | Mô tả phiên sạc và lịch sử yêu cầu của người dùng |
| ACN-Data Static `time series data/jpl/Arroyo_Garage_01/` | Timestamp, charging current, pilot, voltage, charging state, cumulative energy và Power | Phép đo điện theo thời gian trong từng phiên |

### 2.1. Quy mô snapshot đã xử lý

| Chỉ tiêu | Giá trị |
|---|---:|
| API sessions | 33.638 |
| User input records | 41.207 |
| Static CSV.GZ files trong inventory | 27.723 |
| Historical station IDs trong tên file | 52 |
| Khoảng ngày Static theo tên file | 2018-10-08 đến 2020-12-02 |
| Cleaned Static measurements | 175.390.901 dòng |

Các con số API/Static là snapshot thực tế của project, không phải dữ liệu tổng hợp giả lập.

### 2.2. Kết quả ghép API–Static theo phiên

| Trạng thái mapping | Số phiên |
|---|---:|
| MATCHED | 25.647 |
| API_ONLY | 7.991 |
| STATIC_ONLY | 1.978 |
| Hợp của khóa phiên từ hai nguồn | 35.616 |

MATCHED + API_ONLY = 33.638 API sessions. MATCHED + STATIC_ONLY = 27.625 Static sessions. Các trạng thái STATIC_ONLY và API_ONLY thuộc hai tập nguồn khác nhau; không dùng chúng để suy ra tổng API sessions.

Ở Snowflake, đối soát được thực hiện thêm ở cấp measurement rows:

| Tập measurement | Số dòng |
|---|---:|
| STATIC_ALL | 175.390.901 |
| STATIC_MATCHED | 164.438.039 |
| STATIC_ONLY | 10.952.862 |
| Tổng MATCHED + STATIC_ONLY | 175.390.901 |

**Khác grain:** inventory 27.723 file đếm file nguồn; số Static sessions 27.625 trong mapping đếm các phiên được giữ lại sau bước transform. **Không nhầm grain:** 25.647 là số phiên được ghép; 164.438.039 là số dòng phép đo Static thuộc các phiên ghép.

## 3. Quy trình xử lý dữ liệu

### 3.1. Extract

- `src/ingestion/extract_api.py`: phân trang API, checkpoint, loại bỏ session ID trùng và lưu snapshot JSON.
- `src/ingestion/extract_static.py`: kiểm tra thư mục Static đã sparse-checkout.
- `scripts/clone_jpl_static_repo.ps1`: chỉ lấy thư mục JPL cần dùng từ repository ACN-Data Static.
- `scripts/audit_jpl_static_inventory.py`: kiểm kê file, ngày và station ID mà không cần giải nén toàn bộ nội dung.

### 3.2. Transform

- `src/transform/clean_api.py`: chuẩn hóa timestamp UTC, session metadata và tách từng lần userInputs thành bản ghi riêng.
- `src/transform/clean_static.py`: đọc CSV.GZ theo từng phiên, chuẩn hóa tên cột, timestamp và station ID; xử lý theo luồng để giảm RAM.
- `src/transform/audit_static_api_overlap.py`: chuẩn hóa khóa phiên và phân loại MATCHED/API_ONLY/STATIC_ONLY.
- `src/transform/audit_static_api_metrics.py`: đối chiếu năng lượng và gắn nhãn chất lượng.
- `src/transform/build_matched_static_measurements.py`: tạo dữ liệu Static có thông tin ánh xạ API cho phân tích cần kết hợp hai nguồn.

### 3.3. Load và triển khai cloud

Các file cleaned được upload trực tiếp từ máy local lên Snowflake Internal Stage bằng `PUT`, sau đó nạp bằng `COPY INTO`. Không tạo thêm bản sao local của file Static nén.

Quy trình cloud:
1. Tạo database, schemas, warehouse, file format và internal stage.
2. Tạo RAW landing tables cho sessions, userInputs, Static measurements và mapping.
3. Nạp dữ liệu RAW từ các file đã chuẩn hóa.
4. Tạo dimensions, facts và view Static đầy đủ.
5. Tạo các Power marts và view phân tích.
6. Chạy truy vấn đối soát Q1–Q5 và data-quality gate.
7. Upload Streamlit source và module SQL, sau đó publish live version.

## 4. Kiến trúc Snowflake

Database: `JPL_ANALYTICS` · Warehouse: `JPL_ETL_WH`.

| Lớp | Schema | Trách nhiệm |
|---|---|---|
| Landing/raw | RAW | Internal stage, dữ liệu API, userInputs, Static, mapping và load audit |
| Warehouse | WAREHOUSE | Dimensions, session facts, request facts, full-Static view |
| Analytics marts | MART | Last-positive-current, station-hour, station-month, site-hour và profile Power |
| Semantic/query | ANALYTICS | View truy vấn sẵn cho phân tích |

Warehouse được cấu hình X-Small, auto-resume và auto-suspend 60 giây để hạn chế tiêu thụ credit.

### 4.1. Mô hình dữ liệu

**Dimensions**
- `DIM_STATION`: thông tin EVSE/station.
- `DIM_USER`: người dùng nhận diện được trong dữ liệu.
- `DIM_DATE`: lịch ngày theo `America/Los_Angeles`.
- `DIM_TIME`: 1.440 mốc phút trong ngày.

**Facts**
- `FACT_CHARGING_SESSIONS`: grain = một dòng cho một API charging session.
- `FACT_USER_REQUESTS`: grain = một dòng cho một lần userInputs cập nhật.
- `FACT_STATIC_MEASUREMENTS`: view có grain = một dòng cho một phép đo Static.

**Chuẩn hóa định danh người dùng:** RAW và cột `USER_ID` trong hai Fact giữ nguyên giá trị nguồn. Warehouse bổ sung `USER_ID_KEY`, chuẩn hóa số 0 ở đầu đối với mã số và trim khoảng trắng. `DIM_USER.USER_ID_KEY`, `FACT_CHARGING_SESSIONS.USER_ID_KEY` và `FACT_USER_REQUESTS.USER_ID_KEY` là các khóa dùng để đối chiếu. Không dùng trực tiếp `USER_ID` nguồn để JOIN giữa hai API payload.

**Kiểm soát grain/fanout:** Session Fact có một dòng/session; Request Fact có một dòng/(session, input). Không JOIN toàn bộ Request Fact với Session Fact rồi SUM `ENERGY_KWH`. Q4 phải chọn một request mới nhất/session bằng `ROW_NUMBER` trước khi JOIN; kiểm tra Q4 báo số dòng trùng session bằng 0.

View `WAREHOUSE.FACT_STATIC_MEASUREMENTS` giữ toàn bộ Static rows và gắn trạng thái mapping bằng LEFT JOIN. Thiết kế này tránh tạo một bản sao vật lý thứ hai của 175 triệu dòng Static.

### 4.2. Power marts

| Object | Grain / nội dung |
|---|---|
| `MART.SESSION_LAST_CURRENT` | Session API × station; timestamp mẫu có current > 0 cuối cùng |
| `MART.SESSION_POST_CURRENT` | Session API; phút từ mẫu current dương cuối đến disconnect |
| `MART.POWER_STATION_HOUR` | EVSE × UTC hour |
| `MART.POWER_STATION_MONTH` | EVSE × tháng địa phương |
| `MART.POWER_SITE_HOUR` | Lưới đủ 3.673 UTC hours, kể cả giờ không quan sát |
| `MART.POWER_HOUR_OF_DAY_PROFILE` | Profile station-hour Power theo giờ địa phương |

Chỉ các bảng tổng hợp nhỏ được materialize phục vụ dashboard. Toàn bộ Static measurements vẫn nằm ở RAW; warehouse Static fact là view.

## 5. Phương pháp phân tích và kết quả

### Q1 — Nhu cầu sạc theo thứ và giờ

**Phép tính:** nhóm session theo ngày địa phương, thứ ISO và giờ bắt đầu phiên; đếm session và cộng `ENERGY_KWH`.

**Biểu đồ:** heatmap thứ × giờ; biểu đồ đường số phiên trung bình/ngày và kWh gắn với giờ bắt đầu trung bình/ngày giữa ngày thường và cuối tuần.

Số phiên và kWh được chuẩn hóa theo số ngày lịch trong từng nhóm. kWh được gắn theo giờ bắt đầu phiên, không phải điện năng đo riêng trong giờ đó.

### Q2 — Mức sử dụng theo EVSE

**Phép tính:** nhóm theo `STATION_ID`, tính số phiên, tổng kWh, kWh trung bình/phiên, thời lượng kết nối trung bình và tỷ trọng năng lượng.

Kết quả nổi bật trong dashboard:
- EVSE có tổng năng lượng cao nhất: `1-1-194-826`, khoảng 15.979,49 kWh.
- EVSE có nhiều phiên nhất: `1-1-178-823`, 1.449 phiên.

Hai vị trí dẫn đầu khác nhau cho thấy số phiên nhiều nhất không đồng nghĩa tổng điện năng cao nhất.

### Q3 — Thời lượng kết nối và khoảng sau mẫu dòng điện dương cuối

**Phần A – thời lượng kết nối API:** `disconnect_time - connection_time`, phân nhóm:

| Nhóm | Số phiên |
|---|---:|
| < 1 giờ | 753 |
| 1–3 giờ | 4.854 |
| 3–6 giờ | 8.344 |
| >= 6 giờ | 19.687 |

**Phần B – khoảng từ mẫu current dương cuối đến disconnect:** `disconnect_time - last_timestamp(charging_current_a > 0)`.

- Phiên đủ điều kiện: 25.647.
- Trung vị: 124,6 phút.
- P95: 479,0 phút.

Đây là khoảng từ phép đo current dương cuối cùng được ghi nhận đến thời điểm API disconnect. Nó không khẳng định thời điểm pin đầy hoặc thời điểm sạc kết thúc chính xác.

### Q4 — Năng lượng thực nhận so với yêu cầu

Chọn userInputs mới nhất theo `MODIFIED_AT` và `INPUT_ID` cho mỗi session, sau đó lọc `KWH_REQUESTED > 0`.

Tỷ lệ = ENERGY_KWH / KWH_REQUESTED × 100%.

Kết quả:
- Tổng API sessions trong phạm vi: 33.638.
- Phiên có yêu cầu kWh hợp lệ: 31.444.
- Request coverage: 93,48%.
- Trung vị thực nhận/yêu cầu: 60,1%.
- Phiên đạt từ 90%: 14,2%.

Scatter plot có đường tham chiếu y=x. Tỷ lệ thực nhận/yêu cầu là so sánh mô tả, không tự chứng minh nguyên nhân chênh lệch.

### Q5 — Power quan sát và temporal coverage

Cửa sổ Power: **07/2020–11/2020**. Lý do: các trường Power/Voltage không được lưu đồng đều trong phần lịch sử sớm; tháng 06/2020 là giai đoạn chuyển tiếp và tháng 12/2020 chỉ có đến ngày 02/12.

| Chỉ tiêu | Giá trị |
|---|---:|
| Static samples trong cửa sổ | 14.427.675 |
| Station-hour buckets | 18.218 |
| EVSE có ít nhất một quan sát | 50 |
| Power row coverage | 100,00% |
| UTC hours có quan sát từ ít nhất một EVSE | 2.240 |
| UTC hours không có quan sát | 1.433 |
| Tổng UTC hours trong cửa sổ | 3.673 |
| Site-hour observation coverage | 61,0% |

Ba khái niệm phải được phân biệt:

1. **Power row coverage:** Power non-null rows / tất cả Static measurement rows hiện có trong cửa sổ.
2. **Station-month calendar-hour observation coverage:** số giờ lịch một EVSE có ít nhất một quan sát / tổng số giờ lịch trong tháng.
3. **Site-hour observation coverage:** số UTC hours có ít nhất một EVSE quan sát / tổng 3.673 UTC hours.

100% row coverage không có nghĩa dữ liệu tồn tại liên tục 100% thời gian. Static là chuỗi phép đo theo phiên, không phải telemetry 24/7. Giờ không có bản ghi không đồng nghĩa EVSE hỏng hoặc có Power bằng 0.

Trung bình station-hour giữa các EVSE không bảo đảm đồng bộ timestamp; không cộng các giá trị này để kết luận tổng phụ tải đồng thời toàn site.

## 6. Kiểm soát chất lượng và kiểm thử

Các kiểm tra bao gồm:
- Đối soát tổng Static measurement rows với MATCHED + STATIC_ONLY.
- Kiểm tra uniqueness của session, request composite key và static-session mapping.
- Kiểm tra orphan station keys.
- Kiểm tra timestamp last-positive-current nằm trong khoảng kết nối API.
- Kiểm tra lưới Power site-hour đủ 3.673 UTC hours và không trùng UTC key.
- Kiểm tra dữ liệu fact không rỗng.

File kiểm tra:
- `snowflake/04_validation.sql`
- `snowflake/05_data_quality.sql`

Unit/regression tests nằm trong `tests/`. GitHub Actions thực hiện compile các entrypoint Python và chạy `python -m unittest discover -s tests -v`.

## 7. Cấu trúc repository

| Thư mục | Nội dung |
|---|---|
| `src/ingestion` | Extract API và Static |
| `src/transform` | Clean, matching và data-quality audit |
| `src/load` | Pipeline PostgreSQL tham chiếu/local |
| `scripts` | Audit, preflight, Snowflake deploy và kiểm tra |
| `sql/schema`, `sql/analytics` | SQL cho pipeline PostgreSQL tham chiếu và phân tích local |
| `snowflake` | Bootstrap, RAW, warehouse, marts, validation, dashboard và query module |
| `dashboard` | Dashboard local tham chiếu và Power audit CSV |
| `tests` | Unit/regression tests |
| `docs` | Runbook, methodology, inventory và implementation status |

**Kiến trúc triển khai cuối cùng:** Snowflake là nơi lưu trữ, truy vấn warehouse/marts và phục vụ dashboard Streamlit. Các script PostgreSQL cũ được giữ lại làm pipeline tham chiếu/local, không phải backend của Streamlit trên Snowflake.

## 8. Cài đặt và triển khai

### 8.1. Chuẩn bị local

Yêu cầu: Windows PowerShell, Git, Python 3.11+ và các biến cấu hình trong file `.env`. Không commit API token hay Snowflake credentials.

    Copy-Item .env.example .env
    # Điền ACN_API_TOKEN vào .env
    .\scripts\clone_jpl_static_repo.ps1
    python scripts/preflight_jpl.py
    python scripts/audit_jpl_static_inventory.py

Thu thập và transform dữ liệu nếu cần dựng lại nguồn local:

    python run_pipeline.py --stage extract
    python scripts/audit_jpl_api_snapshot.py
    python run_pipeline.py --stage transform

### 8.2. Triển khai Snowflake đầy đủ

Lệnh sau tải/nạp API và Static, sau đó tạo warehouse/marts, chạy validation, data-quality gate và publish Streamlit:

    .\scripts\run_snowflake_deploy.ps1 -IncludeStatic

Nếu API đã có trên Snowflake nhưng cần nạp Static riêng:

    .\scripts\run_snowflake_deploy.ps1 -IncludeStatic -SkipCoreLoad

**Lưu ý:** đây là thao tác nạp lại dữ liệu lớn 175M rows. Không chạy lại chỉ để cập nhật giao diện hoặc SQL dashboard.

### 8.3. Chuẩn hóa USER_ID trên Warehouse hiện có, không nạp lại dữ liệu

Lấy nhánh đã cập nhật:

    git switch chore/final-project-hardening
    git pull origin chore/final-project-hardening

Chạy migration có kiểm soát:

    .\scripts\run_snowflake_deploy.ps1 -WarehouseOnly

`-WarehouseOnly` bổ sung và cập nhật `USER_ID_KEY` trong `DIM_USER`, `FACT_CHARGING_SESSIONS` và `FACT_USER_REQUESTS`, sau đó chạy kiểm tra khóa, orphan và grain Q4. Lệnh này không tải lại RAW, không đọc/nạp lại 175M Static rows, không rebuild Power marts và không thay thế các bảng lớn. Giá trị `USER_ID` gốc được giữ nguyên.

Không kết hợp `-WarehouseOnly` với `-IncludeStatic`, `-SkipCoreLoad` hoặc `-AppOnly`.

### 8.4. Chỉ cập nhật Streamlit, không xử lý lại dữ liệu

    .\scripts\run_snowflake_deploy.ps1 -AppOnly

`-AppOnly` chỉ upload `streamlit_app.py`, `analytics_queries.py`, `environment.yml` và publish live version; không nạp lại Static, không rebuild 175M-row marts.

### 8.5. Kiểm tra thủ công trên Snowsight

Chạy `snowflake/04_validation.sql` để kiểm tra các truy vấn và `snowflake/05_data_quality.sql` để nhận kết quả PASS/FAIL. Xác minh dashboard tại:

`JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD`.

## 9. Tài liệu tham khảo

- ACN-Data dataset/API: https://ev.caltech.edu/dataset.html
- ACN-Data Static: https://github.com/tongxin-li/ACN-Data-Static
- Lee, Z. J., Li, T., & Low, S. H. (2019). *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19.
- Snowflake Streamlit dependency management: https://docs.snowflake.com/en/developer-guide/streamlit/app-development/dependency-management
