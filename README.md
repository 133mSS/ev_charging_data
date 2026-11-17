# JPL EV Charging Analytics

Bài tập lớn môn **Trực quan hóa dữ liệu** · Python / Pandas / PostgreSQL / SQL / Plotly / Streamlit.

## 1. Phạm vi đề tài

**Mục tiêu:** phân tích nhu cầu sạc, hành vi sử dụng và đặc điểm phụ tải quan sát của các trạm sạc xe điện tại JPL (Jet Propulsion Laboratory), sử dụng dữ liệu thực ACN-Data.

**Site ID:** `jpl` · **Khu vực static:** `Arroyo_Garage_01` · **Múi giờ:** `America/Los_Angeles`.

Trang ACN-Data mô tả JPL có 50 EVSE và chỉ phục vụ nhân viên. Đây là thông tin mô tả hạ tầng trên trang dataset, không phải cam kết rằng mỗi snapshot lịch sử sẽ chứa đúng 50 station ID. Snapshot Static đã kiểm kê có 27.723 file CSV.GZ, 52 mã station ID xuất hiện trong tên file, từ 2018-10-08 đến 2020-12-02; 52 mã lịch sử không được diễn giải thành 52 EVSE lắp đặt đồng thời.

## 2. Câu hỏi phân tích dự kiến

| # | Câu hỏi | Trực quan hóa |
|---|---|---|
| 1 | Nhu cầu sạc thay đổi theo giờ và ngày trong tuần như thế nào? | Heatmap giờ × thứ; số phiên theo giờ; ngày thường/cuối tuần |
| 2 | Các EVSE được sử dụng không đồng đều ra sao? | Xếp hạng số phiên/kWh; heatmap EVSE × giờ |
| 3 | Xe kết nối bao lâu và còn kết nối bao lâu sau lần cuối ghi nhận dòng sạc khác 0? | Phân phối duration; box plot theo EVSE |
| 4 | Năng lượng thực nhận so với yêu cầu cuối cùng được ghi nhận ra sao? | Scatter requested vs delivered; tỷ lệ thực nhận/yêu cầu |
| 5 | Công suất quan sát và số EVSE có dữ liệu thay đổi thế nào trong ngày? | Load profile trung bình/P95; concurrency; coverage |

Mỗi kết luận phải đi kèm số phiên hoặc số mẫu hỗ trợ. Không biến công suất quan sát thành phụ tải toàn site nếu độ bao phủ không đầy đủ.

### Ánh xạ câu hỏi vào dashboard

| Câu hỏi | Phần trả lời trong dashboard chính |
|---|---|
| Q1 — Nhu cầu sạc theo giờ và ngày trong tuần | Mục Q1: số phiên theo giờ bắt đầu, heatmap thứ × giờ và so sánh số phiên/kWh trung bình mỗi ngày thường với cuối tuần |
| Q2 — Khác biệt mức sử dụng giữa EVSE | Mục Q2: xếp hạng số phiên, kWh, tỷ trọng năng lượng và xu hướng theo tháng |
| Q3 — Thời lượng kết nối và thời gian sau mốc dòng sạc cuối | Mục Q3a và Q3b: phân nhóm thời lượng, phân bố khoảng kết nối sau doneChargingTime |
| Q4 — Năng lượng yêu cầu và thực nhận | Mục Q4: scatter kWhRequested–kWhDelivered, tỷ lệ và độ bao phủ userInputs |
| Q5 — Power và độ bao phủ | Mục Q5 trong dashboard chính (Static đã ghép); dashboard Power bổ trợ kiểm toán toàn bộ Static, kể cả STATIC_ONLY |

Xu hướng tiêu thụ theo tháng là phần bối cảnh bổ sung. **Dashboard phân tích chính là dashboard/app.py; dashboard/power_analytics.py chỉ là trang kiểm toán chuyên sâu cho Q5.**

## 3. Nguồn dữ liệu thật

| Nguồn | Nội dung | Trạng thái |
|---|---|---|
| ACN-Data REST API `/api/v1/sessions/jpl` | Metadata phiên, thời gian, stationID, kWhDelivered, userInputs | Cần API token; số phiên thực tế được chốt sau khi tải API |
| ACN-Data-Static `time series data/jpl/Arroyo_Garage_01/` | CSV.GZ theo phiên: current, pilot, voltage, state, cumulative energy, power | Repository công bố 27.723 file; snapshot 2018–2020 |

Hai luồng là hai cách truy cập/biểu diễn trong cùng hệ sinh thái ACN-Data, không phải hai nhà cung cấp dữ liệu độc lập. Nếu giảng viên yêu cầu nhiều tổ chức cung cấp dữ liệu, cần bổ sung một nguồn độc lập như CAISO và ghi rõ đó là dữ liệu bối cảnh cấp lưới điện.

## 4. Bắt đầu trên Windows PowerShell

1. Giải nén project và cài Git for Windows, Python 3.11+ và Docker Desktop.
2. Tạo môi trường Python và cài thư viện:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. Tạo file `.env` từ mẫu; điền API token của ACN-Data. Không đưa `.env` lên GitHub:

```powershell
Copy-Item .env.example .env
```

4. Tải riêng thư mục Static JPL (sparse checkout, không tải các site khác):

```powershell
.\scripts\clone_jpl_static_repo.ps1
```

5. Kiểm tra môi trường và kiểm kê metadata Static mà chưa cần giải nén từng CSV.GZ:

```powershell
python scripts/preflight_jpl.py
python scripts/audit_jpl_static_inventory.py
```

6. Thu thập metadata API và kiểm tra thư mục Static (Static được đọc trực tiếp từ sparse checkout, không tạo bản sao thứ hai):

```powershell
python run_pipeline.py --stage extract
python scripts/audit_jpl_api_snapshot.py
```

7. Chạy kiểm thử logic ghép ID, transform và ngưỡng kiểm tra chất lượng:

```powershell
python -m unittest discover -s tests -v
```

8. Transform và ghép hai nguồn:

```powershell
python run_pipeline.py --stage transform
```

9. Tạo database JPL riêng và nạp warehouse:

```powershell
docker compose up -d
python run_pipeline.py --stage load
```

10. Chạy dashboard:

```powershell
streamlit run dashboard/app.py
```


Đây là dashboard chính trả lời Q1–Q5. Trang kiểm toán Power/coverage bổ trợ chạy riêng sau khi audit CSV đã được tạo:

```powershell
streamlit run dashboard/power_analytics.py
```

## 5. Kiểm soát dữ liệu và diễn giải

- Không dùng dữ liệu Office 001 trong phân tích JPL. Folder `data/processed/jpl/` tách riêng mọi đầu ra.
- Database JPL dùng cổng 5436 và volume riêng, tránh trộn với database Office cũ ở cổng 5435.
- API endpoint được gọi bằng alias `jpl`. Pipeline đọc giá trị `siteID` thực tế trong payload, yêu cầu snapshot chỉ có đúng một giá trị không rỗng, sau đó dùng chính giá trị đó để gắn nhãn bản ghi Static. Không tự giả định giá trị trường payload phải bằng alias endpoint.
- Matching API–Static phải dựa trên station/session identifiers; chỉ dùng dữ liệu `MATCHED` cho phân tích chuỗi đo ghép.
- Số filename station IDs là số mã xuất hiện trong snapshot lịch sử, không đồng nghĩa số EVSE hiện hữu đồng thời.
- `doneChargingTime` là thời điểm dòng điện khác 0 cuối cùng được ghi nhận, không khẳng định pin đã đầy.
- `kWhDelivered` là năng lượng cấp trong phiên; `Power (kW)` là công suất tức thời theo mẫu đo. Không cộng mẫu khác timestamp hoặc điền thiếu công suất bằng 0.
- Tỷ lệ coverage phải hiển thị cùng load profile; chỉ diễn giải như công suất quan sát.
- Không đưa dữ liệu từ site khác vào warehouse JPL.

## 6. Trạng thái triển khai

- [x] Xác nhận site ID JPL và endpoint ACN-Data API.
- [x] Tải/refresh API snapshot: 33.638 session IDs duy nhất.
- [x] Kiểm kê Static JPL: 27.723 file CSV.GZ; 52 station IDs lịch sử; 2018-10-08 đến 2020-12-02.
- [x] Transform toàn bộ Static: 175.390.901 measurement rows.
- [x] Đối chiếu API–Static: 25.647 MATCHED, 1.978 STATIC_ONLY, 7.991 API_ONLY.
- [x] Audit Power trên toàn bộ Static cho Jul–Nov 2020: 14.427.675 rows, 50 station IDs có quan sát, row-level Power coverage 100%.
- [x] Phân loại 32 station IDs có quan sát đủ 5 tháng, 18 trạm có dữ liệu gián đoạn và 2 trạm không có quan sát trong cửa sổ.
- [x] Thêm temporal audit có full UTC-hour grid, kể cả giờ không có quan sát.
- [x] Thêm script đối chiếu API–Static theo station-hour và dashboard Power đọc từ full-Static outputs.
- [x] Thêm unit tests và GitHub Actions.
- [ ] Chạy API–Static hourly alignment trên bộ dữ liệu local sau khi pull nhánh mới.
- [ ] Rerun temporal audit để tái tạo site-hour CSV theo full-grid mới.
- [ ] Xác minh dashboard Power trong môi trường Windows và chụp ảnh minh chứng.
- [ ] Hoàn thiện/kiểm tra phần load aggregate Power vào PostgreSQL nếu cần dùng cho bản dashboard database.

## 7. Tham khảo

- ACN-Data dataset/API: https://ev.caltech.edu/dataset.html
- ACN-Data Static: https://github.com/tongxin-li/ACN-Data-Static
- Lee, Z. J., Li, T., & Low, S. H. (2019). *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19.


## 8. Power analytics and temporal coverage

Power is analyzed separately from the broader API session-history questions because the Static archive has a source retention limitation. The source documentation records that before 2020-06-17, only Charging Current was retained for JPL Arroyo Garage 01; Voltage and Power are not uniformly available in that earlier period. The full-Static audit found 40.44% row-level Power coverage in June 2020 and 100% in the available Static rows from July through November 2020. The Static archive ends on 2020-12-02, so December is partial.

Use July–November 2020 as the Power comparison window. This does not limit API session, energy, connection-duration, or demand analyses to those five months.

### Full-Static temporal audit

Run against all 50 station IDs with observations in the selected window, not only the 32-station balanced comparison cohort:

~~~powershell
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --all-stations --chunksize 500000
~~~

The audit scans the full cleaned Static dataset. It writes station-hour, station-month, hour-of-day, site-hour and summary outputs under data/analytics/jpl_power_temporal/.

Important: the site-hour output is a complete UTC-hour grid (3,673 hours for July–November 2020), including hours with no observations. This prevents coverage percentages from using only hours where some EVSE happened to report. Missing Power remains missing and is never filled with 0.

### API–Static hourly alignment

After the API/Static transform has generated the session mapping, run:

~~~powershell
python scripts/audit_jpl_api_static_hourly_alignment.py --start-month 2020-07 --end-month 2020-11 --chunksize 500000
~~~

This expands API connection intervals into UTC-hour buckets and compares them with Static samples from the full cleaned Static file. Outputs are written under data/analytics/jpl_api_static_alignment/.

### One-command run

After the API/Static transforms are complete, this PowerShell command runs unit tests, the full-Static temporal audit and API–Static hourly alignment in order:

~~~powershell
.\scripts\run_jpl_power_analytics.ps1
~~~

Add -LaunchDashboard to launch the CSV-driven Power dashboard after the analytics steps finish. Use -ChunkSize 250000 on a lower-memory machine.

### Power dashboard

~~~powershell
streamlit run dashboard/power_analytics.py
~~~

The Power dashboard reads the full-Static CSV audit outputs. The primary dashboard remains available with streamlit run dashboard/app.py.

### Balanced comparison cohort

To regenerate the 32-station subset with observations in all five months and a minimum monthly row-level Power coverage:

~~~powershell
python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 99
~~~

Use this cohort for like-for-like month comparisons only. Do not discard the other 18 stations with intermittent observations from descriptive analysis. Two additional historical station IDs have no observation in the selected five-month window.

### Interpretation

- Calendar-hour observation presence is not EVSE uptime. Static records are per-session traces, not continuous 24/7 telemetry.
- Power row coverage measures non-null Power among records that exist; it does not prove continuous temporal coverage.
- A station-hour mean is an average of samples within one station-hour.
- The sum of station-hour means is not a synchronized facility load because observations from different EVSEs do not necessarily share timestamps.
- API session minutes are session-minutes and can overlap; they are not unique occupied wall-clock minutes.
- For definitions, results, evidence screenshots and the full runbook, see docs/JPL_POWER_ANALYTICS_FINAL.md.


## 9. Snowflake cloud deployment (new)

The repository now includes a Snowflake-first deployment package. It retains the local PostgreSQL implementation as a reference/fallback and does not delete or overwrite local source data.

### Target architecture

- **Snowflake RAW:** internal stage plus typed landing tables for API sessions, userInputs, Static measurements and session mapping.
- **Snowflake WAREHOUSE:** station/date/time dimensions, API session facts, user-request facts and a view over all Static measurements. The Static object is a view over the RAW table to avoid a second physical copy of the 175M-row dataset.
- **Snowflake MART:** last-positive-current timing, station-hour Power, station-month coverage, full UTC site-hour calendar and hour-of-day profile.
- **Snowflake Streamlit:** one dashboard using the active Snowpark session, with Q1–Q5 analysis.
- **GitHub:** remains the source-code/version-control system.

### Deployment assets

- snowflake/00_bootstrap.sql
- snowflake/01_raw_staging.sql
- snowflake/02_warehouse.sql
- snowflake/03_power_marts.sql
- snowflake/04_validation.sql
- snowflake/streamlit_app.py
- snowflake/environment.yml
- scripts/deploy_snowflake.py
- requirements-snowflake.txt
- docs/SNOWFLAKE_MIGRATION_RUNBOOK.md
- docs/SNOWFLAKE_MIGRATION_REPORT_DRAFT.md

### Credentials

Install the optional Snowflake connector:

~~~powershell
.\scripts\run_snowflake_deploy.ps1
~~~

Add these values to a local .env file (never commit the real .env):

~~~dotenv
SNOWFLAKE_ACCOUNT=<organization-account_name>
SNOWFLAKE_USER=<snowflake-login-username>
SNOWFLAKE_PASSWORD=<your-password>
SNOWFLAKE_ROLE=<optional-role>
SNOWFLAKE_WAREHOUSE=JPL_ETL_WH
# For Sign in with Google (managed OIDC), comment out password and set:
# SNOWFLAKE_AUTHENTICATOR=OAUTH_AUTHORIZATION_CODE
# For Google Workspace SAML instead, use externalbrowser.
~~~

Use the account identifier from Snowsight > account selector > View account details (do not include https://, URL path or .snowflakecomputing.com). For organization/account names, use organization-account_name. The exact Snowflake login username is required. The connector reads the project-root .env in preference to stale inherited environment variables. If the account only supports browser-based SSO, use SNOWFLAKE_AUTHENTICATOR=externalbrowser and omit the password. The account role must have privileges to create the database, warehouse, schemas, stages, tables, views and Streamlit app. The deployment code uses credentials from environment variables; no credential is embedded in repository source. The Windows wrapper installs the Snowflake client in %LOCALAPPDATA% and directs temporary files to the system drive, not the nearly-full project drive.

### Two-step deployment

Before creating cloud objects, verify login with a read-only connection test:

~~~powershell
$py = "$env:LOCALAPPDATA\\JPL-Snowflake-Client\\venv\\Scripts\\python.exe"
& $py .\\scripts\\test_snowflake_connection.py
~~~

For a managed Google OIDC login, set `SNOWFLAKE_AUTHENTICATOR=OAUTH_AUTHORIZATION_CODE` in `.env`. Use `externalbrowser` only for a SAML 2.0 IdP.

First deploy the smaller API inputs, create the warehouse objects and publish the dashboard shell:

~~~powershell
.\scripts\run_snowflake_deploy.ps1
~~~

This does **not** load the 175M-row Static file. Q1–Q4 can be validated after the API data loads; Q5 remains unpopulated until Static is loaded.

Before using the remaining Snowflake trial credits, check the current Snowsight credit balance. Then opt in to the large Static upload and Power marts without reloading the API tables:

~~~powershell
.\scripts\run_snowflake_deploy.ps1 -IncludeStatic -SkipCoreLoad
~~~

The loader uploads the existing processed files directly to the Snowflake internal stage (PUT) and loads them with COPY INTO; it does not create an additional local data copy. It checks that the single compressed Static file is within the configured per-file load limit. If the check stops, split the compressed input safely before retrying; do not bypass the guard.

The bootstrap creates an X-Small warehouse with 60-second auto-suspend. Monitor trial credit consumption and stop the warehouse when not in use. A Snowflake trial is time-limited and is not a permanent free hosting plan.

### Validation

Run snowflake/04_validation.sql in Snowsight or inspect its output from the deployment script. Confirm API/userInputs/Static row counts, MATCHED vs STATIC_ONLY session counts and the Q5 site-hour calendar. The July–November Power window should contain 3,673 elapsed UTC hours, but actual row counts/observation presence must be read from the live Snowflake load, not copied from local logs.

### Launch and account-side status

The deploy script creates JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD and publishes a live Streamlit version. Open the Streamlit object from Snowsight.

**Implementation status:** deployment SQL, loader, app and report/runbook assets are committed to this branch. The user's Snowflake account has not yet been connected or loaded by this repository change. Do not report the Snowflake warehouse/dashboard as operational until the account-side deployment, row-count reconciliation and dashboard screenshots have been completed.
