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

- [x] Xác nhận site ID và endpoint API chính thức.
- [x] Kiểm kê Git tree JPL Static: 27.723 file; 52 filename station IDs; 2018-10-08–2020-12-02; 616,187,585 bytes nén.
- [x] Thay các đường dẫn và kiểm tra số lượng cố định của Office bằng cấu hình JPL.
- [ ] Tải API bằng API token trên máy chạy project.
- [ ] Tải 27.723 file static JPL và chạy transform/matching.
- [ ] Chốt số phiên API, tỷ lệ ghép, số mẫu, coverage và quality sau khi có dữ liệu thực.
- [x] Thêm truy vấn và biểu đồ heatmap nhu cầu theo thứ × giờ (chờ dữ liệu JPL để kiểm chứng đầu ra).
- [ ] Hoàn thiện load profile, mức đồng thời và nhận định dashboard theo kết quả JPL đã xác minh.

## 7. Tham khảo

- ACN-Data dataset/API: https://ev.caltech.edu/dataset.html
- ACN-Data Static: https://github.com/tongxin-li/ACN-Data-Static
- Lee, Z. J., Li, T., & Low, S. H. (2019). *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19.


## 8. Power analysis scope and temporal coverage

The first full-Static audit identified 32 first-pass EVSE candidates with Static samples and non-null Power measurements in each month from July through November 2020. This first-pass criterion does not establish continuous hourly observation.

Rebuild the reproducible scope using the full-Static station/month coverage output:

\`\`\`powershell
python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 99
\`\`\`

The default 99% threshold is evaluated separately in each month. The selected list may therefore contain fewer than the 32 first-pass candidates.

Then audit actual calendar-hour observation and sample density using the full cleaned Static dataset (not the API-matched-only measurements):

\`\`\`powershell
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11
\`\`\`

For a lower-memory run:

\`\`\`powershell
python scripts/audit_jpl_temporal_coverage.py --chunksize 250000
\`\`\`

Outputs are written to the folder **data/analytics/jpl_power_temporal/**:
- jpl_station_hourly_temporal_coverage.csv
- jpl_station_month_temporal_coverage.csv
- jpl_station_hour_of_day_profile.csv
- jpl_site_hourly_observed_load.csv
- jpl_temporal_coverage_summary.json

**Interpretation:** calendar-hour observation coverage is not EVSE uptime. Site Power is summed only across stations with Power observations in that hour; missing stations are never filled with zero. The current fact_static_measurements table uses API-matched rows only and must not be the sole source for Power analysis because it excludes STATIC_ONLY measurements. See docs/JPL_POWER_TEMPORAL_AUDIT.md for definitions and the Warehouse design decision.
