"""CSV-driven Power analytics page for the JPL full-Static temporal audit.

Generate the source files first:
    python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --all-stations
Optional API/Static alignment:
    python scripts/audit_jpl_api_static_hourly_alignment.py
Then run:
    streamlit run dashboard/power_analytics.py
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]
POWER_DIR = ROOT / "data" / "analytics" / "jpl_power_temporal"
ALIGNMENT_DIR = ROOT / "data" / "analytics" / "jpl_api_static_alignment"


st.set_page_config(
    page_title="JPL Power & Coverage Analytics",
    page_icon="⚡",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def load_power_outputs():
    required = {
        "summary": POWER_DIR / "jpl_temporal_coverage_summary.json",
        "station_hour": POWER_DIR / "jpl_station_hourly_temporal_coverage.csv",
        "station_month": POWER_DIR / "jpl_station_month_temporal_coverage.csv",
        "site_hour": POWER_DIR / "jpl_site_hourly_observed_load.csv",
        "hour_profile": POWER_DIR / "jpl_station_hour_of_day_profile.csv",
    }
    missing = [str(path) for path in required.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Thiếu file audit. Hãy chạy scripts/audit_jpl_temporal_coverage.py trước:\n"
            + "\n".join(missing)
        )

    summary = json.loads(required["summary"].read_text(encoding="utf-8"))
    station_hour = pd.read_csv(required["station_hour"])
    station_month = pd.read_csv(required["station_month"])
    site_hour = pd.read_csv(required["site_hour"])
    hour_profile = pd.read_csv(required["hour_profile"])

    if "site_hour_has_any_observation" not in site_hour.columns:
        site_hour["site_hour_has_any_observation"] = (
            pd.to_numeric(site_hour["stations_with_any_samples"], errors="coerce").fillna(0) > 0
        )
        st.warning(
            "File site-hour được tạo bởi phiên bản audit cũ, chưa có đủ giờ không quan sát. "
            "Chạy lại audit bằng phiên bản mới để tính đúng mẫu số thời gian."
        )

    numeric = {
        "station_hour": [
            "local_hour", "total_samples", "power_samples", "avg_power_kw",
            "p95_observed_hour_power_kw", "power_sample_coverage_pct",
        ],
        "station_month": [
            "observed_calendar_hours", "expected_calendar_hours",
            "calendar_hour_observation_pct", "hours_with_power",
            "power_sample_coverage_pct", "avg_observed_hour_power_kw",
            "p95_observed_hour_power_kw",
        ],
        "site_hour": [
            "local_hour", "stations_with_any_samples", "stations_with_power",
            "selected_station_count", "selected_station_power_coverage_pct",
            "power_samples", "total_samples",
        ],
        "hour_profile": [
            "local_hour", "observed_calendar_hours", "total_samples",
            "power_samples", "avg_observed_hour_power_kw",
            "p95_observed_hour_power_kw",
        ],
    }
    frames = {
        "station_hour": station_hour,
        "station_month": station_month,
        "site_hour": site_hour,
        "hour_profile": hour_profile,
    }
    for key, columns in numeric.items():
        for column in columns:
            if column in frames[key].columns:
                frames[key][column] = pd.to_numeric(
                    frames[key][column], errors="coerce"
                )
    station_hour["local_date"] = station_hour["local_date"].astype(str)
    station_hour["local_month"] = station_hour["local_date"].str[:7]
    station_month["month"] = station_month["month"].astype(str)
    site_hour["local_date"] = site_hour["local_date"].astype(str)
    site_hour["local_month"] = site_hour["local_date"].str[:7]

    return summary, station_hour, station_month, site_hour, hour_profile


@st.cache_data(show_spinner=False)
def load_alignment():
    path = ALIGNMENT_DIR / "jpl_api_static_station_hour_alignment.csv"
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    frame["local_date"] = frame["local_date"].astype(str)
    frame["local_month"] = frame["local_date"].str[:7]
    for column in [
        "local_hour", "api_sessions_overlapping_hour",
        "api_sessions_matched_to_static", "api_sessions_api_only",
        "static_sessions_with_samples", "static_matched_api_sessions_with_samples",
        "static_only_sessions_with_samples", "static_power_samples",
        "static_mean_sample_power_kw",
    ]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


st.title("JPL EV Charging — Power & Data Coverage")
st.caption(
    "Phân tích các phép đo điện trong ACN-Data Static, kết hợp kiểm soát độ bao phủ "
    "và đối chiếu phiên sạc từ ACN-Data API."
)

try:
    summary, station_hour, station_month, site_hour, hour_profile = load_power_outputs()
except Exception as exc:
    st.error(str(exc))
    st.stop()

month_options = sorted(station_month["month"].dropna().unique().tolist())
if not month_options:
    st.error("Không tìm thấy tháng phân tích trong kết quả audit.")
    st.stop()

station_options = sorted(station_hour["station_id"].dropna().astype(str).unique().tolist())

with st.sidebar:
    st.header("Bộ lọc")
    selected_months = st.select_slider(
        "Khoảng tháng",
        options=month_options,
        value=(month_options[0], month_options[-1]),
    )
    selected_station_label = st.selectbox(
        "EVSE",
        options=["Tất cả EVSE"] + station_options,
        index=0,
    )
    if st.button("Làm mới dữ liệu"):
        st.cache_data.clear()
        st.rerun()

start_month, end_month = selected_months
selected_station = (
    None if selected_station_label == "Tất cả EVSE" else selected_station_label
)

sh = station_hour[
    station_hour["local_month"].between(start_month, end_month)
].copy()
sm_scope = station_month[
    station_month["month"].between(start_month, end_month)
].copy()
sm = sm_scope.copy()
site = site_hour[
    site_hour["local_month"].between(start_month, end_month)
].copy()

if selected_station is not None:
    sh = sh[sh["station_id"].astype(str).eq(selected_station)].copy()
    sm = sm[sm["station_id"].astype(str).eq(selected_station)].copy()

observed_hours = int(site["site_hour_has_any_observation"].sum())
expected_hours = len(site)
no_observation_hours = expected_hours - observed_hours
total_samples = int(site["total_samples"].sum())
power_samples = int(site["power_samples"].sum())
power_coverage = 100.0 * power_samples / total_samples if total_samples else 0.0
station_count = int(summary.get("selected_station_count", len(station_options)))

st.caption(
    f"Phạm vi: {start_month} đến {end_month} · "
    f"Múi giờ phân tích: America/Los_Angeles · "
    f"Nguồn Static: {station_count} EVSE có quan sát trong cửa sổ audit."
)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Số mẫu Static", f"{total_samples:,}")
k2.metric("Power sample coverage", f"{power_coverage:.2f}%")
k3.metric("Giờ có ít nhất một quan sát", f"{observed_hours:,}/{expected_hours:,}")
k4.metric("Giờ không có quan sát", f"{no_observation_hours:,}")

st.warning(
    "Đây là dữ liệu đo theo phiên sạc, không phải telemetry liên tục 24/7. "
    "Giờ không có mẫu không đồng nghĩa EVSE hỏng hoặc mất kết nối. "
    "Không cộng công suất trung bình theo station-hour để gọi là tổng phụ tải thực tế của toàn JPL."
)

st.header("01. Độ bao phủ dữ liệu theo tháng")
# Monthly coverage uses all stations in the current audit scope; missing station-month
# combinations are explicitly represented as 0 for a fair common denominator.
all_stations = sorted(station_hour["station_id"].dropna().astype(str).unique())
coverage_rows = []
for month in month_options:
    if not (start_month <= month <= end_month):
        continue
    month_data = sm_scope[sm_scope["month"].eq(month)].set_index("station_id")
    values = [
        float(month_data.loc[sid, "calendar_hour_observation_pct"])
        if sid in month_data.index
        and pd.notna(month_data.loc[sid, "calendar_hour_observation_pct"])
        else 0.0
        for sid in all_stations
    ]
    coverage_rows.append({
        "month": month,
        "mean_coverage_pct": sum(values) / len(values) if values else 0.0,
        "median_coverage_pct": float(pd.Series(values).median()) if values else 0.0,
        "stations_with_observation": int(
            month_data["calendar_hour_observation_pct"].notna().sum()
        ),
    })
coverage = pd.DataFrame(coverage_rows)

left, right = st.columns(2)
with left:
    fig = px.line(
        coverage,
        x="month",
        y=["mean_coverage_pct", "median_coverage_pct"],
        markers=True,
        title="Tỷ lệ giờ có quan sát trung bình và trung vị",
        labels={
            "month": "Tháng",
            "value": "Tỷ lệ giờ có quan sát (%)",
            "variable": "Chỉ số",
        },
    )
    fig.update_yaxes(range=[0, 100])
    st.plotly_chart(fig, width="stretch")
with right:
    fig = px.bar(
        coverage,
        x="month",
        y="stations_with_observation",
        title="Số EVSE có ít nhất một quan sát trong tháng",
        labels={"month": "Tháng", "stations_with_observation": "Số EVSE"},
    )
    fig.update_yaxes(range=[0, max(50, int(coverage["stations_with_observation"].max()) + 2)])
    st.plotly_chart(fig, width="stretch")

st.subheader("Coverage theo từng EVSE và tháng")
heatmap = sm_scope.pivot_table(
    index="station_id",
    columns="month",
    values="calendar_hour_observation_pct",
    aggfunc="first",
)
heatmap = heatmap.reindex(index=all_stations)
heatmap = heatmap.reindex(columns=[m for m in month_options if start_month <= m <= end_month])
heatmap = heatmap.fillna(0)
fig = px.imshow(
    heatmap,
    aspect="auto",
    labels={"x": "Tháng", "y": "EVSE", "color": "Giờ có quan sát (%)"},
    title="Mức độ hiện diện của phép đo theo EVSE × tháng",
)
st.plotly_chart(fig, width="stretch")

st.header("02. Số EVSE có Power đồng thời theo giờ")
distribution = (
    site.groupby("stations_with_power", dropna=False)
    .size()
    .reset_index(name="hours")
    .sort_values("stations_with_power")
)
fig = px.bar(
    distribution,
    x="stations_with_power",
    y="hours",
    title="Phân bố số EVSE có Power trong cùng một giờ UTC",
    labels={"stations_with_power": "Số EVSE có Power", "hours": "Số giờ"},
)
st.plotly_chart(fig, width="stretch")

daily_presence = (
    site.groupby("local_date", as_index=False)
    .agg(
        avg_evse_with_power=("stations_with_power", "mean"),
        max_evse_with_power=("stations_with_power", "max"),
        hours_with_any_observation=("site_hour_has_any_observation", "sum"),
    )
)
fig = px.line(
    daily_presence,
    x="local_date",
    y=["avg_evse_with_power", "max_evse_with_power"],
    markers=True,
    title="Số EVSE có Power trung bình/tối đa mỗi giờ trong ngày",
    labels={
        "local_date": "Ngày địa phương",
        "value": "Số EVSE",
        "variable": "Chỉ số",
    },
)
st.plotly_chart(fig, width="stretch")

st.header("03. Power profile theo giờ địa phương")
if sh.empty:
    st.info("Không có bản ghi Static trong bộ lọc hiện tại.")
else:
    profile = (
        sh.groupby("local_hour", as_index=False)
        .agg(
            mean_station_hour_power_kw=("avg_power_kw", "mean"),
            p95_station_hour_power_kw=("avg_power_kw", lambda x: x.quantile(0.95)),
            station_hour_observations=("avg_power_kw", "count"),
            stations_observed=("station_id", "nunique"),
            power_samples=("power_samples", "sum"),
        )
        .sort_values("local_hour")
    )
    fig = px.line(
        profile,
        x="local_hour",
        y=["mean_station_hour_power_kw", "p95_station_hour_power_kw"],
        markers=True,
        title=(
            f"Power theo giờ trong ngày — {selected_station}"
            if selected_station else "Phân bố Power trung bình theo station-hour"
        ),
        labels={
            "local_hour": "Giờ địa phương (Los Angeles)",
            "value": "Power (kW)",
            "variable": "Chỉ số",
        },
    )
    fig.update_xaxes(
        tickmode="array",
        tickvals=list(range(24)),
        ticktext=[f"{h:02d}:00" for h in range(24)],
        range=[-0.5, 23.5],
    )
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Mỗi điểm là trung bình các mẫu Power trong một station-hour. "
        "Với lựa chọn tất cả EVSE, đường trung bình/P95 mô tả phân bố station-hour, "
        "không phải tổng công suất đồng thời của site."
    )
    st.dataframe(profile, width="stretch", hide_index=True)

st.header("04. Kiểm tra đối chiếu API – Static")
alignment = load_alignment()
if alignment is None:
    st.info(
        "Chưa có kết quả API–Static hourly alignment. Chạy "
        "python scripts/audit_jpl_api_static_hourly_alignment.py để tạo."
    )
else:
    alignment = alignment[
        alignment["local_month"].between(start_month, end_month)
    ].copy()
    if selected_station:
        alignment = alignment[alignment["station_id"].astype(str).eq(selected_station)]
    if alignment.empty:
        st.info("Không có dữ liệu đối chiếu trong phạm vi đang chọn.")
    else:
        api_hourly = (
            alignment.groupby("local_hour", as_index=False)
            .agg(
                api_sessions_overlapping_hour=("api_sessions_overlapping_hour", "sum"),
                api_matched_sessions=("api_sessions_matched_to_static", "sum"),
                api_only_sessions=("api_sessions_api_only", "sum"),
                static_matched_sessions_with_samples=(
                    "static_matched_api_sessions_with_samples", "sum"
                ),
                static_only_sessions_with_samples=(
                    "static_only_sessions_with_samples", "sum"
                ),
            )
        )
        fig = px.line(
            api_hourly,
            x="local_hour",
            y=[
                "api_sessions_overlapping_hour",
                "static_matched_sessions_with_samples",
                "static_only_sessions_with_samples",
            ],
            markers=True,
            title="Đối chiếu phiên API và phiên Static có mẫu theo giờ địa phương",
            labels={
                "local_hour": "Giờ địa phương (Los Angeles)",
                "value": "Số phiên-hour",
                "variable": "Chỉ số",
            },
        )
        fig.update_xaxes(
            tickmode="array",
            tickvals=list(range(24)),
            ticktext=[f"{h:02d}:00" for h in range(24)],
            range=[-0.5, 23.5],
        )
        st.plotly_chart(fig, width="stretch")
        st.caption(
            "API session counts are session-hour pairs. API connected minutes are summed "
            "session-minutes and may include overlap; they are not unique occupied minutes."
        )
        st.dataframe(
            alignment[
                [
                    "station_id", "local_date", "local_hour",
                    "api_sessions_overlapping_hour",
                    "api_sessions_matched_to_static",
                    "api_sessions_api_only",
                    "static_matched_api_sessions_with_samples",
                    "static_only_sessions_with_samples",
                    "static_total_samples", "static_power_samples",
                    "static_power_sample_coverage_pct",
                    "static_mean_sample_power_kw",
                ]
            ].sort_values(["local_date", "local_hour", "station_id"]),
            width="stretch",
            hide_index=True,
        )

st.header("05. Kết luận và giới hạn diễn giải")
st.markdown(
    """
- Power được phân tích trên các bản ghi Static có giá trị đo thực tế.
- Các ô thiếu quan sát được giữ là thiếu; không chuyển thành Power = 0.
- Bản ghi Static thuộc phiên sạc, không phải chuỗi giám sát liên tục của mọi EVSE.
- Các phép đo khác EVSE không nhất thiết đồng thời; không gọi tổng station-hour mean là tổng phụ tải JPL.
- Dùng API để mô tả phiên/khoảng kết nối; dùng Static để mô tả các mẫu điện đo được; đối chiếu hai nguồn bằng station ID, session ID và thời gian UTC.
"""
)
