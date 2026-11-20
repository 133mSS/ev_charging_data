# Báo cáo triển khai Snowflake — JPL EV Charging Analytics

**Ngày cập nhật:** 20/11/2026  
**Phạm vi:** chuyển nền tảng lưu trữ, warehouse, phân tích và dashboard của JPL EV Charging Analytics sang Snowflake.

## 1. Tóm tắt

Project sử dụng dữ liệu thực từ ACN-Data JPL, gồm API session/userInputs và Static electrical measurements theo từng phiên. Snapshot đã xử lý gồm 33.638 sessions, 41.207 userInputs và 175.390.901 Static measurement rows.

Snowflake được sử dụng làm cloud data platform cho landing, warehouse, analytical marts và Streamlit dashboard. Local Python/Pandas thực hiện ingest/clean/matching; các file cleaned được upload bằng PUT và nạp bằng COPY INTO; các phép biến đổi warehouse/mart và truy vấn phân tích được thực hiện bằng Snowflake SQL.

Lần triển khai đầy đủ ngày 18/11/2026 đã hoàn tất. Log triển khai xác nhận số dòng nạp, đối soát Static, truy vấn Q1–Q5 và publish Streamlit live version. Ảnh Snowsight do chủ project cung cấp xác nhận dashboard hiển thị các phần tổng quan và Q1–Q5.

## 2. Nguồn dữ liệu

| Nguồn | Nội dung | Phạm vi |
|---|---|---|
| ACN-Data API | Charging session metadata, connection/disconnect times, kWhDelivered, userInputs | Site alias jpl |
| ACN-Data Static | Charging current, pilot, voltage, charging state, cumulative energy, Power | JPL Arroyo Garage 01 |

Hai nguồn thuộc cùng hệ sinh thái ACN-Data và có vai trò bổ sung cho nhau. API mô tả session và yêu cầu người dùng; Static lưu phép đo điện theo thời gian trong từng session.

Inventory Static: 27.723 file CSV.GZ, 52 historical station IDs trong tên file, khoảng ngày 2018-10-08 đến 2020-12-02. Số station ID lịch sử không được diễn giải là số EVSE được lắp đặt đồng thời.

## 3. Quy trình ETL

### 3.1. Extract

- API được trích xuất bằng pagination và checkpoint, lưu thành snapshot JSON.
- Static được lấy qua sparse checkout chỉ cho JPL Arroyo Garage 01.
- Inventory script thống kê file, station ID và thời gian từ Git metadata trước khi đọc payload.

### 3.2. Transform

Python/Pandas chuẩn hóa session metadata, userInputs, timestamp UTC, station ID và các cột phép đo. Static được xử lý theo từng file/chunk nhằm hạn chế RAM.

Session matching sử dụng station/session identifiers, sau đó phân loại MATCHED, API_ONLY và STATIC_ONLY. Dữ liệu không ghép được vẫn được giữ lại để kiểm toán; không ép quan hệ một-một giả tạo.

### 3.3. Load

Các file cleaned hiện có được upload trực tiếp lên Snowflake internal stage bằng PUT và nạp bằng COPY INTO. Loader sử dụng temporary table trước khi thay thế dữ liệu trong RAW table bằng transaction.

Static là bước nạp lớn riêng biệt; local file nén không được nhân bản thêm trong quá trình upload.

## 4. Kiến trúc Snowflake

Database: `JPL_ANALYTICS`  
Warehouse: `JPL_ETL_WH` — X-SMALL, AUTO_RESUME và AUTO_SUSPEND 60 giây.

| Layer | Nội dung |
|---|---|
| RAW | Internal stage, sessions, userInputs, Static, mapping và load audit |
| WAREHOUSE | DIM_STATION, DIM_USER, DIM_DATE, DIM_TIME, FACT_CHARGING_SESSIONS, FACT_USER_REQUESTS và full-Static view |
| MART | SESSION_LAST_CURRENT, SESSION_POST_CURRENT, POWER_STATION_HOUR, POWER_STATION_MONTH, POWER_SITE_HOUR, POWER_HOUR_OF_DAY_PROFILE |
| ANALYTICS | Các view phục vụ câu hỏi nghiên cứu và Streamlit |

### 4.1. Grain của các fact

- FACT_CHARGING_SESSIONS: một dòng cho một API session.
- FACT_USER_REQUESTS: một dòng cho một input event.
- FACT_STATIC_MEASUREMENTS: một dòng cho một Static measurement; triển khai dưới dạng view trên RAW Static, có thêm mapping status.

Việc dùng view cho full Static tránh tạo bản sao vật lý thứ hai của tập 175 triệu dòng. Các aggregate station-hour/month/site-hour được materialize nhằm giảm lượng dữ liệu phải xử lý khi hiển thị dashboard.

## 5. Đối soát dữ liệu

### 5.1. Session mapping

| Trạng thái | Số phiên |
|---|---:|
| MATCHED | 25.647 |
| API_ONLY | 7.991 |
| STATIC_ONLY | 1.978 |

API sessions = MATCHED + API_ONLY = 33.638. Static sessions = MATCHED + STATIC_ONLY = 27.625.

### 5.2. Measurement rows trên Snowflake

| Trạng thái | Số dòng |
|---|---:|
| STATIC_ALL | 175.390.901 |
| STATIC_MATCHED | 164.438.039 |
| STATIC_ONLY | 10.952.862 |

164.438.039 + 10.952.862 = 175.390.901. Các số trong bảng này là measurement rows, không phải số phiên.

## 6. Phân tích Q1–Q5

### Q1 — Nhu cầu sạc theo thứ và giờ

Session được nhóm theo ngày địa phương, thứ ISO và giờ bắt đầu. Dashboard dùng heatmap thứ × giờ và biểu đồ đường so sánh số phiên/kWh gắn với giờ bắt đầu trung bình mỗi ngày giữa ngày thường và cuối tuần. Số liệu được chuẩn hóa theo số ngày lịch của từng nhóm.

### Q2 — Mức sử dụng theo EVSE

Các chỉ số gồm session count, total delivered energy, average energy/session, average connection duration và energy share. EVSE có tổng năng lượng cao nhất là 1-1-194-826 với khoảng 15.979,49 kWh; EVSE có nhiều phiên nhất là 1-1-178-823 với 1.449 phiên.

### Q3 — Thời lượng kết nối và khoảng từ mẫu dòng điện dương cuối

Thời lượng kết nối được tính từ API disconnect_time trừ connection_time và phân thành bốn nhóm. Kết quả: 753 phiên dưới 1 giờ; 4.854 phiên từ 1–3 giờ; 8.344 phiên từ 3–6 giờ; 19.687 phiên từ 6 giờ trở lên.

Phân tích bổ sung tìm timestamp cuối cùng trong Static có charging_current_a > 0, sau đó tính khoảng thời gian đến API disconnect_time. Kết quả có 25.647 phiên hợp lệ, median 124,6167 phút và P95 478,995 phút. Chỉ số này không phải thời điểm pin đầy hoặc thời điểm kết thúc sạc chính xác.

### Q4 — Năng lượng thực nhận so với yêu cầu

Với mỗi session, chọn userInputs mới nhất theo modified_at và input_id, sau đó so sánh kWhRequested dương với kWhDelivered.

- API sessions trong toàn phạm vi: 33.638.
- Sessions có latest valid kWh request: 31.444.
- Request coverage: 93,48%.
- Median delivered/requested: 60,08875%.
- Tỷ lệ session có delivered/requested >= 90%: 14,2%.

Scatter plot sử dụng đường tham chiếu y=x. Đây là so sánh mô tả, không xác định nguyên nhân của chênh lệch.

### Q5 — Power và độ bao phủ theo thời gian

Power được phân tích trong cửa sổ 07/2020–11/2020. Lịch sử Static không lưu đều các trường Power/Voltage ở giai đoạn sớm; tháng 06/2020 là tháng chuyển tiếp và tháng 12/2020 chỉ có dữ liệu đến ngày 02/12.

| Chỉ tiêu | Giá trị |
|---|---:|
| Static samples trong cửa sổ | 14.427.675 |
| Station-hour buckets | 18.218 |
| EVSE có quan sát | 50 |
| Power row coverage | 100,00% |
| UTC hours có ít nhất một quan sát | 2.240 |
| UTC hours không có quan sát | 1.433 |
| Tổng UTC hours | 3.673 |
| Site-hour observation coverage | 61,0% |

Power row coverage là tỷ lệ hàng Static hiện có có Power non-null. Site-hour observation coverage là tỷ lệ giờ UTC có ít nhất một EVSE ghi nhận trên tổng 3.673 giờ. 100% row coverage không có nghĩa quan sát liên tục 100% thời gian.

Dashboard sử dụng fixed 50-station population khi dựng station × month grid; station-month không có quan sát được giữ lại với 0% calendar-hour coverage. Validation SQL cũng sử dụng cùng population để thống nhất mẫu số.

Static là dữ liệu theo phiên, không phải telemetry 24/7. Missing observations không được đổi thành 0 kW hoặc diễn giải là EVSE downtime. Station-hour means giữa các EVSE không bảo đảm đồng bộ timestamp; không cộng chúng thành tổng phụ tải đồng thời toàn site.

## 7. Streamlit dashboard

Streamlit chạy trực tiếp trên Snowflake qua active Snowpark session, không kết nối PostgreSQL local. Giao diện gồm bộ lọc tháng, KPI tổng quan và năm phần Q1–Q5. SQL phân tích được tách thành module riêng `snowflake/analytics_queries.py`; phần Streamlit chịu trách nhiệm trình bày, định dạng bảng và biểu đồ.

Object được publish: `JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD`.

Lần triển khai 18/11 xác nhận Streamlit live version đã publish. Ảnh Snowsight được cung cấp cho thấy giao diện tổng quan và các biểu đồ Q1–Q5 hiển thị.

## 8. Validation và kiểm thử

Baseline deployment output xác nhận:
- API sessions: 33.638.
- User inputs: 41.207.
- Static all: 175.390.901.
- MATCHED + STATIC_ONLY measurement reconciliation khớp.
- Q3, Q4 và Q5 có kết quả như các bảng trên.
- Streamlit live version publish thành công.

GitHub Actions trên baseline commit `294d471d36ba58a08c103608834d69a408f51525` có trạng thái success (workflow run 44208261833), kiểm tra compile và unit/regression tests.

Nhánh hardening cuối cùng bổ sung thêm:
- `snowflake/05_data_quality.sql`: duplicate keys, mapping, reconciliation, orphan station, Q3 interval và complete site-hour checks.
- Regression tests cho các SQL assets.
- `LOAD_AUDIT` bổ sung RUN_ID, file size, SHA-256 và COPY query ID.
- `-AppOnly` cho phép publish dashboard mà không rebuild marts.
- SQL Q1–Q5 được tách sang `analytics_queries.py`.

Các check và thay đổi mới trong nhánh hardening cần được thực thi trên Snowflake account sau khi merge; không xem là kết quả đã chạy cloud chỉ dựa trên việc code đã được commit.

## 9. Hạn chế và phạm vi kết luận

1. Static là session-based sampled measurements, không phải 24/7 telemetry.
2. Missing hour/station-month không chứng minh thiết bị dừng hoạt động.
3. 52 historical station IDs không bằng số EVSE đồng thời.
4. Q3 post-last-current là khoảng từ sample current dương cuối đến API disconnect, không phải thời điểm kết thúc sạc thực.
5. Q4 chỉ bao phủ các session có latest valid positive kWh request.
6. Trung bình station-hour không được xem là tổng phụ tải đồng bộ của toàn JPL.

## 10. Tài liệu tham khảo

- ACN-Data dataset/API: https://ev.caltech.edu/dataset.html
- ACN-Data Static: https://github.com/tongxin-li/ACN-Data-Static
- Lee, Z. J., Li, T., & Low, S. H. (2019). *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19.
- Snowflake Streamlit dependency management: https://docs.snowflake.com/en/developer-guide/streamlit/app-development/dependency-management
