# JPL EV Charging Analytics — Implementation Status

**Cập nhật:** 20/11/2026  
**Repository:** https://github.com/133mSS/ev_charging_data  
**Nhánh triển khai baseline:** main  
**Trạng thái baseline:** đã hoàn thành full Static load, Snowflake warehouse/marts, Q1–Q5 validation và Streamlit live publication ngày 18/11/2026.

## 1. Trạng thái tổng quan

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| ACN-Data API extraction | Hoàn thành | 33.638 sessions |
| ACN-Data Static inventory | Hoàn thành | 27.723 files, 52 historical station IDs |
| Python/Pandas transform | Hoàn thành | 175.390.901 cleaned measurements |
| API–Static session mapping | Hoàn thành | 25.647 MATCHED, 7.991 API_ONLY, 1.978 STATIC_ONLY |
| Snowflake RAW load | Hoàn thành | 33.638 sessions, 41.207 userInputs, 175.390.901 Static rows |
| Star-schema warehouse | Hoàn thành | 4 dimensions, 2 facts và full-Static view |
| Analytics marts | Hoàn thành | Q3 post-current và Q5 Power marts |
| Q1–Q5 SQL validation | Hoàn thành | Query results ghi nhận trong deployment output |
| Streamlit app | Hoàn thành | Live version published và dashboard hiển thị trong Snowsight |
| GitHub Actions | Hoàn thành | CI success trên baseline commit |
| Data-quality gate mở rộng | Đã bổ sung trong nhánh hardening | Cần chạy sau khi merge trên account |
| ETL run lineage | Đã bổ sung trong nhánh hardening | RUN_ID, file size, SHA-256, COPY query ID |
| Dashboard SQL modularization | Đã bổ sung trong nhánh hardening | analytics_queries.py |
| App-only deployment | Đã bổ sung trong nhánh hardening | -AppOnly |

## 2. Kết quả dữ liệu và phân tích

### Dữ liệu Snowflake

| Dataset | Rows |
|---|---:|
| API sessions | 33.638 |
| User inputs | 41.207 |
| Static all | 175.390.901 |
| Static matched rows | 164.438.039 |
| Static-only rows | 10.952.862 |

Static reconciliation: 164.438.039 + 10.952.862 = 175.390.901.

### Q1–Q5

| Câu hỏi | Kết quả chính |
|---|---|
| Q1 | Dashboard có heatmap thứ × giờ và profile ngày thường/cuối tuần |
| Q2 | EVSE dẫn đầu về năng lượng: 1-1-194-826 (15.979,49 kWh); nhiều phiên nhất: 1-1-178-823 (1.449 phiên) |
| Q3 | 25.647 phiên hợp lệ; median 124,6167 phút; P95 478,995 phút |
| Q4 | 31.444 latest valid requests; median delivered/requested 60,08875%; đạt ≥90% là 14,2% |
| Q5 | 14.427.675 Static rows trong cửa sổ; 50 EVSE; 18.218 station-hour buckets; 2.240/3.673 UTC hours có quan sát |

Q4 request coverage trên toàn bộ 33.638 sessions là 93,48%.

Q5 Power row coverage 100% là tỷ lệ dòng Static đã có có giá trị Power. Site-hour observation coverage là 2.240/3.673 = 61,0%. Hai chỉ số có mẫu số khác nhau.

## 3. Các giới hạn diễn giải

- JPL Static là phép đo theo phiên, không phải telemetry 24/7.
- Missing Static/Power observation không được điền thành 0 và không được xem là bằng chứng EVSE hỏng.
- Historical station IDs không đại diện cho số EVSE hoạt động cùng lúc.
- Q3 đo khoảng từ timestamp cuối cùng có charging_current_a > 0 đến API disconnect; không khẳng định thời điểm pin đầy.
- Q4 là so sánh mô tả với userInputs mới nhất, không tự xác định nguyên nhân chênh lệch.
- Station-hour averages không được cộng để kết luận tổng phụ tải đồng thời của toàn site.

## 4. Nhánh hardening cuối cùng

Nhánh `chore/final-project-hardening` thực hiện các thay đổi bổ sung:
- Đồng bộ README, Runbook, Migration Report và Implementation Status.
- Chuyển SQL Q1–Q5 sang `snowflake/analytics_queries.py`.
- Chỉnh Q3 labels, thêm Q4 request coverage, giới hạn Q5 trong cửa sổ 07–11/2020.
- Giữ cố định population 50 EVSE khi dựng heatmap EVSE × month.
- Sửa monthly validation SQL để dùng complete station-month grid và mẫu số cố định 50 EVSE.
- Thêm `snowflake/05_data_quality.sql` và regression tests.
- Mở rộng `LOAD_AUDIT` với RUN_ID, file size, SHA-256 và COPY query ID.
- Thêm `-AppOnly` để publish dashboard mà không nạp dữ liệu hoặc rebuild marts.
- Bổ sung nhánh CI `chore/**`.

Các thay đổi ở nhánh hardening chưa được tính là đã áp dụng vào Snowflake account cho tới khi merge và deploy app/schema tương ứng.

## 5. Việc cần hoàn tất khi merge nhánh hardening

1. Merge PR của `chore/final-project-hardening` vào `main`.
2. Chạy `snowflake/01_raw_staging.sql` trên Snowsight để bổ sung các cột lineage cho LOAD_AUDIT (các ALTER là idempotent).
3. Chạy `snowflake/04_validation.sql` và `snowflake/05_data_quality.sql`; tất cả data-quality checks phải là PASS.
4. Chạy `.scriptsun_snowflake_deploy.ps1 -AppOnly` để publish dashboard code mới mà không nạp lại 175M Static rows.
5. Chạy GitHub Actions và chụp ảnh Snowsight Q1–Q5 sau khi publish.

Chi tiết vận hành nằm tại `docs/SNOWFLAKE_MIGRATION_RUNBOOK.md`.
