from datetime import datetime
from pathlib import Path
import os
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

st.set_page_config(
    page_title="JPL EV Charging Analytics",
    page_icon="⚡",
    layout="wide",
)


@st.cache_resource
def get_engine():
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(
            "Thiếu cấu hình DB trong .env: " + ", ".join(missing)
        )

    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url, pool_pre_ping=True)


@st.cache_data(ttl=240, show_spinner=False)
def read_query(sql: str, params: dict | None = None) -> pd.DataFrame:
    with get_engine().connect() as connection:
        return pd.read_sql_query(text(sql), connection, params=params or {})


MONTHLY_SQL = """
SELECT
    d.year,
    d.month,
    TO_CHAR(MAKE_DATE(d.year, d.month, 1), 'YYYY-MM') AS month_label,
    COUNT(*) AS session_count,
    SUM(f.energy_kwh) AS total_energy_kwh,
    AVG(f.energy_kwh) AS avg_energy_per_session_kwh
FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
GROUP BY d.year, d.month
ORDER BY d.year, d.month;
"""

STATIONS_SQL = """
SELECT DISTINCT station_id
FROM warehouse.dim_station
ORDER BY station_id;
"""

START_HOUR_SQL = """
WITH hours AS (
    SELECT generate_series(0, 23)::INTEGER AS local_hour
),
hourly_agg AS (
    SELECT
        t.hour AS local_hour,
        COUNT(*) AS session_count,
        SUM(f.energy_kwh) AS energy_kwh_by_start_hour
    FROM warehouse.fact_charging_sessions f
    JOIN warehouse.dim_time t ON t.time_key = f.time_key
    JOIN warehouse.dim_date d ON d.date_key = f.date_key
    WHERE d.full_date >= CAST(:start_date AS DATE)
      AND d.full_date < CAST(:end_date_exclusive AS DATE)
    GROUP BY t.hour
)
SELECT
    h.local_hour,
    COALESCE(a.session_count, 0) AS session_count,
    COALESCE(a.energy_kwh_by_start_hour, 0) AS energy_kwh_by_start_hour
FROM hours h
LEFT JOIN hourly_agg a ON a.local_hour = h.local_hour
ORDER BY h.local_hour;
"""

POWER_SQL = """
WITH expected AS (
    SELECT COUNT(DISTINCT station_id) AS total_stations
    FROM warehouse.dim_station
),
station_minute AS (
    SELECT
        station_id,
        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        ) AS local_minute,
        AVG(power_kw) AS avg_station_power_kw
    FROM warehouse.fact_static_measurements
    WHERE power_kw IS NOT NULL
      AND (timestamp_utc AT TIME ZONE 'America/Los_Angeles')
            >= CAST(:start_date AS DATE)
      AND (timestamp_utc AT TIME ZONE 'America/Los_Angeles')
            < CAST(:end_date_exclusive AS DATE)
    GROUP BY
        station_id,
        DATE_TRUNC(
            'minute',
            timestamp_utc AT TIME ZONE 'America/Los_Angeles'
        )
),
site_minute AS (
    SELECT
        local_minute,
        SUM(avg_station_power_kw) AS observed_power_kw,
        COUNT(DISTINCT station_id) AS stations_observed
    FROM station_minute
    GROUP BY local_minute
),
power_minute AS (
    SELECT
        local_minute,
        SUM(avg_station_power_kw) AS observed_power_kw
    FROM station_minute
    WHERE (:station_id IS NULL OR station_id = :station_id)
    GROUP BY local_minute
),
hours AS (
    SELECT generate_series(0, 23)::INTEGER AS local_hour
),
hourly_power AS (
    SELECT
        EXTRACT(HOUR FROM local_minute)::INTEGER AS local_hour,
        COUNT(*) AS power_minute_buckets,
        AVG(observed_power_kw) AS avg_observed_power_kw,
        PERCENTILE_CONT(0.95) WITHIN GROUP (
            ORDER BY observed_power_kw
        ) AS p95_observed_power_kw
    FROM power_minute
    GROUP BY EXTRACT(HOUR FROM local_minute)::INTEGER
),
hourly_coverage AS (
    SELECT
        EXTRACT(HOUR FROM s.local_minute)::INTEGER AS local_hour,
        COUNT(*) AS observed_minute_buckets,
        AVG(s.stations_observed) AS avg_stations_observed,
        100.0 * AVG(s.stations_observed) / NULLIF(MAX(e.total_stations), 0)
            AS avg_station_coverage_pct,
        COUNT(*) FILTER (
            WHERE s.stations_observed = e.total_stations
        ) AS full_coverage_minutes
    FROM site_minute s
    CROSS JOIN expected e
    GROUP BY EXTRACT(HOUR FROM s.local_minute)::INTEGER
)
SELECT
    h.local_hour,
    COALESCE(hc.observed_minute_buckets, 0) AS observed_minute_buckets,
    COALESCE(hp.power_minute_buckets, 0) AS power_minute_buckets,
    hp.avg_observed_power_kw,
    hp.p95_observed_power_kw,
    hc.avg_stations_observed,
    hc.avg_station_coverage_pct,
    COALESCE(hc.full_coverage_minutes, 0) AS full_coverage_minutes
FROM hours h
LEFT JOIN hourly_power hp ON hp.local_hour = h.local_hour
LEFT JOIN hourly_coverage hc ON hc.local_hour = h.local_hour
ORDER BY h.local_hour;
"""

DURATION_SQL = """
SELECT
    CASE
        WHEN f.connection_duration_minutes < 60
            THEN '< 1 giờ'
        WHEN f.connection_duration_minutes < 180
            THEN '1–3 giờ'
        WHEN f.connection_duration_minutes < 360
            THEN '3–6 giờ'
        ELSE '>= 6 giờ'
    END AS duration_group,

    CASE
        WHEN f.connection_duration_minutes < 60 THEN 1
        WHEN f.connection_duration_minutes < 180 THEN 2
        WHEN f.connection_duration_minutes < 360 THEN 3
        ELSE 4
    END AS group_order,

    COUNT(*) AS session_count,
    AVG(f.connection_duration_minutes)
        AS avg_connection_duration_minutes,
    AVG(f.energy_kwh) AS avg_energy_per_session_kwh,
    SUM(f.energy_kwh) AS total_energy_kwh,

    SUM(f.energy_kwh) /
        NULLIF(SUM(f.connection_duration_minutes) / 60.0, 0)
        AS energy_per_connection_hour

FROM warehouse.fact_charging_sessions f
JOIN warehouse.dim_date d
    ON d.date_key = f.date_key

WHERE d.full_date >= CAST(:start_date AS DATE)
  AND d.full_date < CAST(:end_date_exclusive AS DATE)
  AND f.connection_duration_minutes IS NOT NULL
  AND f.connection_duration_minutes >= 0

GROUP BY duration_group, group_order
ORDER BY group_order;
"""


def read_sql_file(filename: str) -> str:
    return (
        PROJECT_ROOT / "sql" / "analytics" / filename
    ).read_text(encoding="utf-8")


MONTHLY_STATION_SQL = read_sql_file("21_monthly_station_trend.sql")
WEEKDAY_HEATMAP_SQL = read_sql_file("25_weekday_hour_heatmap.sql")
STATION_RANKING_SQL = read_sql_file("22_station_usage_ranking.sql")
POST_CHARGE_SQL = read_sql_file("23_post_charge_connection_time.sql")
REQUEST_COMPARISON_SQL = read_sql_file("24_requested_vs_delivered.sql")


@st.fragment(run_every="5m", key="ev_charging_dashboard")
def render_dashboard() -> None:
    st.title("⚡ JPL EV Charging Analytics")
    st.caption(
        "Nguồn dữ liệu: ACN-Data (site JPL, Arroyo Garage 01). Phân tích theo thời gian: "
        "xu hướng tiêu thụ điện, thời điểm bắt đầu sạc, công suất quan sát được, "
        "thời lượng kết nối, mức sử dụng theo trạm và chênh lệch giữa yêu cầu với điện năng thực nhận."
    )

    st.info(
        "**Đây là dashboard phân tích chính, được tổ chức theo 5 câu hỏi nghiên cứu.** "
        "Q1: thời điểm/ngày bắt đầu sạc (mục 02); "
        "Q2: khác biệt mức sử dụng giữa EVSE (mục 05); "
        "Q3: thời lượng kết nối và khoảng thời gian sau mốc dòng sạc cuối (mục 04 và 06); "
        "Q4: năng lượng yêu cầu so với thực nhận (mục 07); "
        "Q5: Power và độ bao phủ (mục 03; xem dashboard Power bổ trợ để kiểm toán toàn bộ Static)."
    )

    try:
        monthly_all = read_query(MONTHLY_SQL)
        stations_df = read_query(STATIONS_SQL)
        monthly_station_all = read_query(MONTHLY_STATION_SQL)
    except Exception as exc:  # Show a clear message instead of a stack trace.
        st.error(f"Không thể tải dữ liệu từ PostgreSQL: {exc}")
        st.info("Kiểm tra Docker/PostgreSQL, file .env và các bảng warehouse.")
        return

    if monthly_all.empty:
        st.warning("Chưa có dữ liệu session trong warehouse.fact_charging_sessions.")
        return

    month_options = monthly_all["month_label"].astype(str).tolist()
    station_options = stations_df["station_id"].dropna().astype(str).tolist()

    with st.sidebar:
        st.header("Bộ lọc")
        st.caption("Khoảng thời gian áp dụng cho tất cả phần phân tích.")
        selected_months = st.select_slider(
            "Khoảng tháng",
            options=month_options,
            value=(month_options[0], month_options[-1]),
            help="Chọn tháng bắt đầu và kết thúc; hai tháng biên đều được tính.",
        )
        selected_station_label = st.selectbox(
            "Trạm cho biểu đồ công suất",
            options=["Tất cả trạm"] + station_options,
            index=0,
            help="Lọc đường công suất ở mục 03. Độ bao phủ vẫn tính trên tất cả trạm.",
        )
        if st.button("Làm mới dữ liệu ngay", width="stretch"):
            st.cache_data.clear()
            st.rerun(scope="fragment")
        st.caption("Dữ liệu truy vấn được cache tối đa 4 phút; trang tự làm mới mỗi 5 phút khi đang mở.")

    start_month, end_month = selected_months
    start_date = pd.Period(start_month, freq="M").start_time.date().isoformat()
    end_date_exclusive = (
        (pd.Period(end_month, freq="M") + 1).start_time.date().isoformat()
    )
    query_params = {
        "start_date": start_date,
        "end_date_exclusive": end_date_exclusive,
    }

    monthly = monthly_all[
        monthly_all["month_label"].between(start_month, end_month)
    ].copy()
    selected_station = (
        None if selected_station_label == "Tất cả trạm"
        else selected_station_label
    )

    try:
        hourly = read_query(START_HOUR_SQL, query_params)
        weekday_heatmap = read_query(WEEKDAY_HEATMAP_SQL, query_params)

        power_params = {
            **query_params,
            "station_id": selected_station,
        }
        power = read_query(POWER_SQL, power_params)

        duration = read_query(DURATION_SQL, query_params)
        station_ranking = read_query(STATION_RANKING_SQL, query_params)
        post_charge = read_query(POST_CHARGE_SQL, query_params)
        request_comparison = read_query(REQUEST_COMPARISON_SQL, query_params)
    except Exception as exc:
        st.error(f"Không thể tải dữ liệu phân tích: {exc}")
        return

    # PostgreSQL NUMERIC may arrive as Decimal/object; normalize chart fields.
    numeric_columns = {
        "station_ranking": [
            "session_count", "total_energy_kwh", "avg_energy_per_session_kwh",
            "avg_connection_minutes", "energy_share_pct",
        ],
        "post_charge": ["post_charge_connection_minutes", "energy_kwh"],
        "request_comparison": [
            "delivered_kwh", "kwh_requested", "delivered_vs_requested_pct",
            "energy_gap_kwh", "minutes_available", "connection_duration_minutes",
        ],
    }
    numeric_frames = (
        (station_ranking, numeric_columns["station_ranking"]),
        (post_charge, numeric_columns["post_charge"]),
        (request_comparison, numeric_columns["request_comparison"]),
    )
    for frame, columns in numeric_frames:
        for column in columns:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

    now_local = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    st.caption(
        f"Khoảng đang xem: {start_month} đến {end_month} | "
        f"Lần tải/kiểm tra gần nhất: {now_local:%d/%m/%Y %H:%M:%S} (giờ Việt Nam)"
    )

    total_sessions = int(monthly["session_count"].sum()) if not monthly.empty else 0
    total_energy = float(monthly["total_energy_kwh"].sum()) if not monthly.empty else 0.0
    avg_energy = total_energy / total_sessions if total_sessions else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Tổng phiên sạc", f"{total_sessions:,}")
    col2.metric("Tổng năng lượng theo API", f"{total_energy:,.1f} kWh")
    col3.metric("Năng lượng trung bình/phiên", f"{avg_energy:,.2f} kWh")

    # Storytelling: translate the selected period into operational observations.
    st.subheader("Câu chuyện dữ liệu trong khoảng đang chọn")
    story_left, story_right = st.columns(2)

    if total_sessions and not hourly.empty:
        peak_hour_row = hourly.loc[hourly["session_count"].idxmax()]
        peak_hour = int(peak_hour_row["local_hour"])
        peak_hour_count = int(peak_hour_row["session_count"])
        peak_hour_share = 100.0 * peak_hour_count / total_sessions
    else:
        peak_hour, peak_hour_count, peak_hour_share = None, 0, 0.0

    if not station_ranking.empty:
        top_energy_station = station_ranking.iloc[0]
        top_session_station = station_ranking.loc[
            station_ranking["session_count"].idxmax()
        ]
    else:
        top_energy_station = top_session_station = None

    with story_left:
        with st.container(border=True):
            st.markdown("**1. Nhu cầu sạc tập trung vào khung giờ nào?**")
            if peak_hour is not None:
                st.write(
                    f"Khung bắt đầu sạc phổ biến nhất là **{peak_hour:02d}:00**, "
                    f"với **{peak_hour_count:,} phiên** ({peak_hour_share:.1f}% "
                    "số phiên trong khoảng đang xem). Đây là thời điểm nên chú ý "
                    "khi bố trí khả năng phục vụ của bãi sạc."
                )
            else:
                st.write("Chưa có đủ dữ liệu để xác định giờ bắt đầu phổ biến nhất.")

        with st.container(border=True):
            st.markdown("**2. Nhiều phiên nhất có phải trạm tiêu thụ nhiều điện nhất?**")
            if top_energy_station is not None and top_session_station is not None:
                st.write(
                    f"Trạm **{top_energy_station['station_id']}** đứng đầu về điện năng "
                    f"({top_energy_station['energy_share_pct']:.1f}% tổng kWh), trong khi "
                    f"trạm **{top_session_station['station_id']}** có nhiều phiên nhất "
                    f"({int(top_session_station['session_count']):,} phiên). "
                    "Hai chỉ số phản ánh hai khía cạnh sử dụng khác nhau."
                )
            else:
                st.write("Chưa có dữ liệu trạm trong khoảng đang xem.")

    with story_right:
        with st.container(border=True):
            st.markdown("**3. Xe còn kết nối bao lâu sau lần cuối ghi nhận dòng sạc?**")
            if not post_charge.empty:
                post_median = post_charge["post_charge_connection_minutes"].median()
                post_over_60 = 100.0 * (
                    post_charge["post_charge_connection_minutes"] > 60
                ).mean()
                st.write(
                    f"Trung vị là **{post_median:.1f} phút**; **{post_over_60:.1f}%** "
                    "phiên hợp lệ còn kết nối trên 60 phút sau mốc này. Đây là tín hiệu "
                    "đáng xem xét về khả năng chiếm dụng chỗ sạc sau khi ngừng ghi nhận dòng điện."
                )
            else:
                st.write("Khoảng thời gian đang chọn chưa có bản ghi hợp lệ cho chỉ số này.")

        with st.container(border=True):
            st.markdown("**4. Nhu cầu nhập qua ứng dụng có khớp với điện năng thực nhận?**")
            if not request_comparison.empty:
                request_coverage = 100.0 * len(request_comparison) / total_sessions if total_sessions else 0
                request_median = request_comparison["delivered_vs_requested_pct"].median()
                request_90 = 100.0 * (
                    request_comparison["delivered_vs_requested_pct"] >= 90
                ).mean()
                st.write(
                    f"Có **{len(request_comparison):,}/{total_sessions:,} phiên** có yêu cầu "
                    f"({request_coverage:.1f}%). Tỷ lệ thực nhận/yêu cầu ở mức trung vị "
                    f"**{request_median:.1f}%**; **{request_90:.1f}%** phiên đạt từ 90% trở lên. "
                    "Đây là so sánh mô tả trên nhóm có userInputs, không phải KPI đáp ứng dịch vụ."
                )
            else:
                st.write("Không có dữ liệu userInputs trong khoảng đang chọn.")

    st.caption(
        "Các nhận định tự tính theo bộ lọc hiện tại. Giờ được hiểu theo America/Los_Angeles; "
        "không suy diễn nguyên nhân khi dữ liệu chỉ thể hiện mối liên hệ mô tả."
    )

    # 01. Monthly consumption
    st.header("Bổ sung. Xu hướng tiêu thụ điện theo tháng")
    left, right = st.columns(2)

    with left:
        fig = px.bar(
            monthly,
            x="month_label",
            y="total_energy_kwh",
            title="Tổng năng lượng theo tháng",
            labels={"month_label": "Tháng", "total_energy_kwh": "Năng lượng (kWh)"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, width="stretch")

    with right:
        fig = px.line(
            monthly,
            x="month_label",
            y="session_count",
            markers=True,
            title="Số phiên sạc theo tháng",
            labels={"month_label": "Tháng", "session_count": "Số phiên"},
        )
        fig.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig, width="stretch")

    if not monthly.empty:
        peak = monthly.loc[monthly["total_energy_kwh"].idxmax()]
        st.info(
            f"Tháng có tổng năng lượng cao nhất trong khoảng đang lọc: "
            f"{peak['month_label']} — {peak['total_energy_kwh']:,.3f} kWh."
        )
    st.caption(
        "Năng lượng lấy từ metadata API ở cấp session. Tháng đầu/cuối kỳ có thể không đầy đủ."
    )

    # 02. Session start time
    st.header("Q1. Nhu cầu sạc tập trung vào ngày nào và khung giờ nào?")
    left, right = st.columns(2)
    hour_ticks = list(range(24))
    hour_text = [f"{hour:02d}:00" for hour in hour_ticks]

    with left:
        fig = px.bar(
            hourly,
            x="local_hour",
            y="session_count",
            title="Số phiên theo giờ bắt đầu",
            labels={"local_hour": "Giờ bắt đầu (Los Angeles)", "session_count": "Số phiên sạc"},
        )
        fig.update_xaxes(range=[-0.5, 23.5], tickmode="array", tickvals=hour_ticks, ticktext=hour_text)
        st.plotly_chart(fig, width="stretch")

    with right:
        fig = px.bar(
            hourly,
            x="local_hour",
            y="energy_kwh_by_start_hour",
            title="Năng lượng của các phiên theo giờ bắt đầu",
            labels={"local_hour": "Giờ bắt đầu (Los Angeles)", "energy_kwh_by_start_hour": "Năng lượng (kWh)"},
        )
        fig.update_xaxes(range=[-0.5, 23.5], tickmode="array", tickvals=hour_ticks, ticktext=hour_text)
        st.plotly_chart(fig, width="stretch")

    st.caption(
        "Năng lượng được nhóm theo giờ bắt đầu của phiên, không phải công suất tiêu thụ thực tế trong giờ đó."
    )

    st.subheader("Heatmap: nhu cầu bắt đầu sạc theo thứ trong tuần và giờ")
    heatmap_pivot = weekday_heatmap.pivot(
        index="weekday_name", columns="local_hour", values="session_count"
    )
    # Keep calendar order instead of alphabetic weekday sorting.
    weekday_order = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    heatmap_pivot = heatmap_pivot.reindex(weekday_order)
    heatmap_pivot = heatmap_pivot.reindex(columns=list(range(24)), fill_value=0)
    fig = px.imshow(
        heatmap_pivot,
        aspect="auto",
        labels={"x": "Giờ bắt đầu (Los Angeles)", "y": "Ngày trong tuần", "color": "Số phiên"},
        title="Mật độ phiên sạc theo ngày và giờ bắt đầu",
    )
    fig.update_xaxes(tickmode="linear", dtick=1)
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Mỗi ô là số phiên bắt đầu trong một thứ/giờ. Heatmap cho biết thời điểm nhu cầu tập trung; "
        "nó không đo số cổng đang bận đồng thời."
    )

    # 03. Power + coverage
    st.header("Q5. Công suất quan sát và số EVSE có dữ liệu thay đổi thế nào trong ngày?")
    left, right = st.columns(2)

    if selected_station is None:
        power_title = "Tổng các trung bình station-minute có quan sát theo giờ"
        power_caption = "Chỉ số này cộng trung bình theo trạm trong từng phút có dữ liệu; không phải phụ tải đồng thời/toàn cơ sở vì mẫu giữa các EVSE không được chứng minh là đồng bộ."
    else:
        power_title = f"Trung bình công suất station-minute tại trạm {selected_station} theo giờ"
        power_caption = f"Công suất chỉ hiển thị các phút có bản ghi của trạm {selected_station}; đây là trung bình mẫu, không phải đường công suất liên tục."

    power_plot = power[
        ["local_hour", "avg_observed_power_kw", "p95_observed_power_kw"]
    ].rename(
        columns={
            "avg_observed_power_kw": "Trung bình",
            "p95_observed_power_kw": "P95",
        }
    )

    with left:
        fig = px.line(
            power_plot,
            x="local_hour",
            y=["Trung bình", "P95"],
            markers=True,
            title=power_title,
            labels={"local_hour": "Giờ địa phương (Los Angeles)", "value": "Công suất (kW)", "variable": "Chỉ số"},
        )
        fig.update_xaxes(range=[-0.5, 23.5], tickmode="array", tickvals=hour_ticks, ticktext=hour_text)
        st.plotly_chart(fig, width="stretch")

    with right:
        fig = px.line(
            power,
            x="local_hour",
            y="avg_station_coverage_pct",
            markers=True,
            title="Tỷ lệ trạm có dữ liệu trung bình theo giờ",
            labels={"local_hour": "Giờ địa phương (Los Angeles)", "avg_station_coverage_pct": "Tỷ lệ trạm có dữ liệu (%)"},
        )
        fig.update_xaxes(range=[-0.5, 23.5], tickmode="array", tickvals=hour_ticks, ticktext=hour_text)
        fig.update_yaxes(range=[0, 100])
        st.plotly_chart(fig, width="stretch")

    st.caption(power_caption)
    st.info(
        "Power trong trang này được lấy từ fact_static_measurements đã ghép API–Static. "
        "Để xem audit trên toàn bộ Static (bao gồm STATIC_ONLY), độ bao phủ đầy đủ 50 EVSE "
        "và các giờ không có quan sát, chạy riêng: streamlit run dashboard/power_analytics.py."
    )
    st.subheader("Bảng kiểm tra độ bao phủ")
    coverage_display = power[
        [
            "local_hour",
            "observed_minute_buckets",
            "avg_stations_observed",
            "avg_station_coverage_pct",
            "full_coverage_minutes",
        ]
    ].rename(
        columns={
            "local_hour": "Giờ",
            "observed_minute_buckets": "Số phút có dữ liệu từ ít nhất một trạm",
            "avg_stations_observed": "Số trạm quan sát trung bình",
            "avg_station_coverage_pct": "Độ bao phủ trung bình (%)",
            "full_coverage_minutes": "Số phút đủ tất cả EVSE có trong snapshot",
        }
    )
    st.dataframe(coverage_display, width="stretch", hide_index=True)
    st.warning(
        f"Phần công suất dùng dữ liệu static thuộc các phiên đã ghép API–Static. "
        f"Mẫu số coverage là {len(station_options)} mã EVSE xuất hiện trong snapshot API đã nạp, "
        "không mặc định là số EVSE được lắp đặt đồng thời trong mọi thời điểm lịch sử. "
        "Độ bao phủ thay đổi theo thời gian nên đây là công suất quan sát, không phải phụ tải đầy đủ của toàn cơ sở."
    )

    # 04. Connection duration analysis
    st.header("Q3a. Thời lượng kết nối liên quan thế nào đến điện năng nhận được?")

    if duration.empty:
        st.info("Không có dữ liệu thời lượng kết nối trong khoảng đã chọn.")
    else:
        left, right = st.columns(2)

        with left:
            fig = px.bar(
                duration,
                x="duration_group",
                y="session_count",
                title="Số phiên theo thời lượng kết nối",
                labels={
                    "duration_group": "Thời lượng kết nối",
                    "session_count": "Số phiên",
                },
                category_orders={
                    "duration_group": [
                        "< 1 giờ",
                        "1–3 giờ",
                        "3–6 giờ",
                        ">= 6 giờ",
                    ]
                },
            )
            st.plotly_chart(fig, width="stretch")

        with right:
            fig = px.bar(
                duration,
                x="duration_group",
                y="avg_energy_per_session_kwh",
                title="Năng lượng trung bình mỗi phiên",
                labels={
                    "duration_group": "Thời lượng kết nối",
                    "avg_energy_per_session_kwh": "Năng lượng trung bình (kWh)",
                },
                category_orders={
                    "duration_group": [
                        "< 1 giờ",
                        "1–3 giờ",
                        "3–6 giờ",
                        ">= 6 giờ",
                    ]
                },
            )
            st.plotly_chart(fig, width="stretch")

        duration_display = duration[
            [
                "duration_group",
                "session_count",
                "avg_connection_duration_minutes",
                "avg_energy_per_session_kwh",
                "total_energy_kwh",
                "energy_per_connection_hour",
            ]
        ].rename(
            columns={
                "duration_group": "Thời lượng kết nối",
                "session_count": "Số phiên",
                "avg_connection_duration_minutes": "Thời lượng TB (phút)",
                "avg_energy_per_session_kwh": "Năng lượng TB/phiên (kWh)",
                "total_energy_kwh": "Tổng năng lượng (kWh)",
                "energy_per_connection_hour": "Năng lượng/giờ kết nối (kWh)",
            }
        )

        st.dataframe(
            duration_display.round(2),
            width="stretch",
            hide_index=True,
        )

        st.caption(
            "Thời lượng kết nối tính từ lúc xe kết nối đến lúc ngắt kết nối, "
            "không đồng nghĩa với thời gian xe thực sự nhận điện. "
            "Chỉ số năng lượng/giờ kết nối là năng lượng chia cho thời gian "
            "kết nối, không phải công suất sạc thực đo."
        )
    # 05. Station-level ranking and monthly trend.
    st.header("Q2. Mức độ sử dụng ghi nhận khác nhau thế nào giữa các EVSE?")
    st.caption(
        "So sánh cả số phiên và tổng điện năng. Không dùng các chỉ số này để gọi là "
        "tỷ lệ khai thác công suất trạm, vì bộ dữ liệu không cung cấp mẫu số về thời gian "
        "trạm sẵn sàng phục vụ hoặc thời gian bị chiếm dụng của toàn bộ từng trạm."
    )

    if station_ranking.empty:
        st.info("Không có dữ liệu xếp hạng trạm trong khoảng đã chọn.")
    else:
        rank_left, rank_right = st.columns(2)
        rank_plot = station_ranking.sort_values("total_energy_kwh", ascending=True)

        with rank_left:
            fig = px.bar(
                rank_plot,
                x="total_energy_kwh",
                y="station_id",
                orientation="h",
                text="energy_share_pct",
                title="Điện năng ghi nhận theo trạm",
                labels={
                    "station_id": "Mã trạm",
                    "total_energy_kwh": "Tổng điện năng (kWh)",
                    "energy_share_pct": "Tỷ trọng điện năng (%)",
                },
                hover_data={
                    "session_count": True,
                    "avg_energy_per_session_kwh": ":.2f",
                    "energy_share_pct": ":.1f",
                },
            )
            fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig.update_layout(yaxis_title="Mã trạm")
            st.plotly_chart(fig, width="stretch")

        with rank_right:
            session_plot = station_ranking.sort_values("session_count", ascending=True)
            fig = px.bar(
                session_plot,
                x="session_count",
                y="station_id",
                orientation="h",
                title="Số phiên sạc ghi nhận theo trạm",
                labels={
                    "station_id": "Mã trạm",
                    "session_count": "Số phiên",
                },
                hover_data={
                    "total_energy_kwh": ":.1f",
                    "avg_energy_per_session_kwh": ":.2f",
                    "energy_share_pct": ":.1f",
                },
            )
            st.plotly_chart(fig, width="stretch")

        rank_display = station_ranking.rename(
            columns={
                "station_id": "Mã trạm",
                "session_count": "Số phiên",
                "total_energy_kwh": "Tổng điện năng (kWh)",
                "avg_energy_per_session_kwh": "kWh trung bình/phiên",
                "avg_connection_minutes": "Thời lượng kết nối TB (phút)",
                "energy_share_pct": "Tỷ trọng điện năng (%)",
            }
        )
        st.dataframe(rank_display.round(2), width="stretch", hide_index=True)

        top_energy = station_ranking.iloc[0]
        top_sessions = station_ranking.loc[station_ranking["session_count"].idxmax()]
        st.info(
            f"Điểm đáng chú ý: trạm **{top_energy['station_id']}** dẫn đầu về tổng điện năng "
            f"({top_energy['total_energy_kwh']:,.1f} kWh; {top_energy['energy_share_pct']:.1f}%), "
            f"nhưng trạm **{top_sessions['station_id']}** mới là trạm có nhiều phiên nhất "
            f"({int(top_sessions['session_count']):,} phiên)."
        )

    st.subheader("Biến động đóng góp theo tháng")
    st.caption(
        "Chọn “Tất cả trạm” để so sánh xu hướng chung. Để phân tích chi tiết, "
        "hãy chọn một trạm nhằm giúp biểu đồ dễ đọc và hạn chế các đường dữ liệu chồng chéo."
    )
    monthly_station = monthly_station_all[
        monthly_station_all["month_label"].between(
            start_month, end_month
        )
    ].copy()

    if monthly_station.empty:
        st.info("Không có dữ liệu đóng góp theo trạm trong khoảng đã chọn.")
    else:
        station_filter = st.selectbox(
            "Chọn trạm cần phân tích",
            options=["Tất cả trạm"] + station_options,
            index=0,
            key="monthly_station_filter",
        )

        if station_filter != "Tất cả trạm":
            station_view = monthly_station[
                monthly_station["station_id"].astype(str) == station_filter
            ].copy()
        else:
            station_view = monthly_station.copy()

        left, right = st.columns(2)

        with left:
            fig = px.line(
                station_view,
                x="month_label",
                y="total_energy_kwh",
                color="station_id",
                markers=True,
                title="Tổng năng lượng theo tháng và trạm",
                labels={
                    "month_label": "Tháng",
                    "total_energy_kwh": "Năng lượng (kWh)",
                    "station_id": "Mã trạm",
                },
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, width="stretch")

        with right:
            fig = px.line(
                station_view,
                x="month_label",
                y="monthly_energy_share_pct",
                color="station_id",
                markers=True,
                title="Tỷ trọng năng lượng của trạm theo tháng",
                labels={
                    "month_label": "Tháng",
                    "monthly_energy_share_pct": "Tỷ trọng (%)",
                    "station_id": "Mã trạm",
                },
            )
            fig.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig, width="stretch")

        display_columns = [
            "month_label",
            "station_id",
            "session_count",
            "total_energy_kwh",
            "monthly_energy_share_pct",
            "session_change",
            "energy_change_kwh",
            "energy_change_pct",
        ]

        station_display = station_view[display_columns].rename(
            columns={
                "month_label": "Tháng",
                "station_id": "Mã trạm",
                "session_count": "Số phiên",
                "total_energy_kwh": "Năng lượng (kWh)",
                "monthly_energy_share_pct": "Tỷ trọng năng lượng (%)",
                "session_change": "Chênh lệch số phiên",
                "energy_change_kwh": "Chênh lệch năng lượng (kWh)",
                "energy_change_pct": "Thay đổi năng lượng (%)",
            }
        )

        st.dataframe(
            station_display.round(2),
            width="stretch",
            hide_index=True,
        )

        st.caption(
            "Tỷ trọng năng lượng được tính trên tổng năng lượng của tất cả các trạm trong cùng tháng. "
            "Giá trị 0 kWh nghĩa là không ghi nhận phiên sạc của trạm trong tháng đó, không đủ để "
            "kết luận trạm đã ngừng hoạt động. Tháng đầu/cuối có thể chưa đầy đủ. Tỷ lệ thay đổi "
            "có thể rất lớn khi năng lượng tháng trước gần bằng 0; nên xem đồng thời mức thay đổi tuyệt đối."
        )

    # 06. Connection retained after the last non-zero current measurement.
    st.header("Q3b. Xe còn kết nối bao lâu sau lần cuối ghi nhận dòng sạc khác 0?")
    st.write(
        "Chỉ số này được tính bằng thời điểm ngắt kết nối trừ thời điểm cuối cùng ghi nhận "
        "dòng điện khác 0 (`doneChargingTime`). Nó giúp nhận diện những phiên mà xe vẫn "
        "cắm tại trạm khá lâu sau mốc sạc cuối cùng, qua đó gợi ý vấn đề quay vòng chỗ sạc."
    )

    if post_charge.empty:
        st.info("Không có phiên đủ mốc thời gian hợp lệ trong khoảng đang chọn.")
    else:
        post_values = post_charge["post_charge_connection_minutes"].astype(float)
        post_median = float(post_values.median())
        post_over_30 = 100.0 * float((post_values > 30).mean())
        post_over_60 = 100.0 * float((post_values > 60).mean())
        valid_coverage = 100.0 * len(post_charge) / total_sessions if total_sessions else 0.0

        post_kpis = st.columns(4)
        post_kpis[0].metric("Phiên đủ mốc thời gian", f"{len(post_charge):,}")
        post_kpis[1].metric("Trung vị thời gian sau sạc", f"{post_median:.1f} phút")
        post_kpis[2].metric("Còn kết nối > 30 phút", f"{post_over_30:.1f}%")
        post_kpis[3].metric("Còn kết nối > 60 phút", f"{post_over_60:.1f}%")

        post_left, post_right = st.columns(2)
        with post_left:
            post_bins = pd.cut(
                post_values,
                bins=[-0.001, 15, 60, 120, 240, 480, float("inf")],
                labels=["≤ 15 phút", "15–60 phút", "1–2 giờ", "2–4 giờ", "4–8 giờ", "> 8 giờ"],
                include_lowest=True,
            )
            post_distribution = (
                post_bins.value_counts(sort=False)
                .rename_axis("Khoảng thời gian")
                .reset_index(name="Số phiên")
            )
            post_distribution["Tỷ lệ (%)"] = (
                100.0 * post_distribution["Số phiên"] / len(post_charge)
            )
            fig = px.bar(
                post_distribution,
                x="Khoảng thời gian",
                y="Tỷ lệ (%)",
                text="Số phiên",
                title="Phân bố thời gian còn kết nối sau mốc dòng sạc cuối",
                labels={"Tỷ lệ (%)": "Tỷ lệ phiên (%)"},
            )
            fig.update_traces(textposition="outside")
            fig.update_yaxes(rangemode="tozero")
            st.plotly_chart(fig, width="stretch")

        with post_right:
            station_post = (
                post_charge.groupby("station_id")
                .agg(
                    session_count=("session_id", "count"),
                    median_post_minutes=("post_charge_connection_minutes", "median"),
                    p75_post_minutes=("post_charge_connection_minutes", lambda x: x.quantile(0.75)),
                )
                .reset_index()
                .sort_values("median_post_minutes", ascending=True)
            )
            fig = px.bar(
                station_post,
                x="median_post_minutes",
                y="station_id",
                orientation="h",
                title="Trung vị thời gian còn kết nối theo trạm",
                labels={
                    "station_id": "Mã trạm",
                    "median_post_minutes": "Trung vị (phút)",
                    "session_count": "Số phiên hợp lệ",
                    "p75_post_minutes": "P75 (phút)",
                },
                hover_data={"session_count": True, "p75_post_minutes": ":.1f"},
            )
            st.plotly_chart(fig, width="stretch")

        st.dataframe(
            station_post.rename(
                columns={
                    "station_id": "Mã trạm",
                    "session_count": "Số phiên hợp lệ",
                    "median_post_minutes": "Trung vị (phút)",
                    "p75_post_minutes": "Phân vị 75% (phút)",
                }
            ).round(2),
            width="stretch",
            hide_index=True,
        )
        st.info(
            f"Trong {len(post_charge):,} phiên có mốc hợp lệ ({valid_coverage:.1f}% số phiên), "
            f"một nửa số phiên có khoảng thời gian sau mốc dòng sạc cuối không quá {post_median:.1f} phút. "
            f"Có {post_over_60:.1f}% phiên vượt 60 phút. Đây là khoảng thời gian suy ra từ hai mốc "
            "API, không chứng minh xe đã đầy pin hoặc toàn bộ thời gian đó là thời gian chỗ đỗ bị lãng phí."
        )

    # 07. User request compared with session energy delivered.
    st.header("Q4. Năng lượng thực nhận so với yêu cầu cuối cùng được ghi nhận ra sao?")
    st.write(
        "Mỗi phiên có thể có nhiều lần cập nhật `userInputs`. Phân tích chọn bản ghi có "
        "`modified_at` mới nhất cho từng phiên, sau đó so sánh `kWhRequested` với `kWhDelivered` "
        "ở cấp phiên. Nhờ vậy mỗi phiên chỉ xuất hiện một lần trong phân tích."
    )

    if request_comparison.empty:
        st.info("Không có phiên nào có userInputs hợp lệ trong khoảng đang chọn.")
    else:
        request_coverage = 100.0 * len(request_comparison) / total_sessions if total_sessions else 0.0
        request_ratio_median = float(
            request_comparison["delivered_vs_requested_pct"].median()
        )
        request_ratio_mean = float(
            request_comparison["delivered_vs_requested_pct"].mean()
        )
        request_90_share = 100.0 * float(
            (request_comparison["delivered_vs_requested_pct"] >= 90).mean()
        )

        request_kpis = st.columns(4)
        request_kpis[0].metric("Phiên có yêu cầu", f"{len(request_comparison):,}")
        request_kpis[1].metric("Độ bao phủ userInputs", f"{request_coverage:.1f}%")
        request_kpis[2].metric("Trung vị thực nhận/yêu cầu", f"{request_ratio_median:.1f}%")
        request_kpis[3].metric("Phiên đạt ≥ 90% yêu cầu", f"{request_90_share:.1f}%")

        req_left, req_right = st.columns(2)
        with req_left:
            max_axis = max(
                float(request_comparison["kwh_requested"].max()),
                float(request_comparison["delivered_kwh"].max()),
            ) * 1.05
            fig = px.scatter(
                request_comparison,
                x="kwh_requested",
                y="delivered_kwh",
                color="station_id",
                hover_data={
                    "session_id": True,
                    "delivered_vs_requested_pct": ":.1f",
                    "minutes_available": True,
                    "connection_duration_minutes": ":.1f",
                },
                title="kWh yêu cầu và kWh thực nhận theo phiên",
                labels={
                    "kwh_requested": "Năng lượng yêu cầu cuối cùng (kWh)",
                    "delivered_kwh": "Năng lượng thực nhận (kWh)",
                    "station_id": "Mã trạm",
                },
                opacity=0.72,
            )
            fig.add_shape(
                type="line",
                x0=0,
                y0=0,
                x1=max_axis,
                y1=max_axis,
                line={"dash": "dash", "width": 2},
            )
            fig.update_xaxes(range=[0, max_axis])
            fig.update_yaxes(range=[0, max_axis])
            fig.add_annotation(
                x=max_axis * 0.75,
                y=max_axis * 0.82,
                text="Đường y = x: thực nhận bằng yêu cầu",
                showarrow=False,
                textangle=-35,
            )
            st.plotly_chart(fig, width="stretch")

        with req_right:
            request_station = (
                request_comparison.groupby("station_id")
                .agg(
                    session_count=("session_id", "count"),
                    median_realized_pct=("delivered_vs_requested_pct", "median"),
                    mean_requested_kwh=("kwh_requested", "mean"),
                )
                .reset_index()
                .sort_values("median_realized_pct", ascending=True)
            )
            fig = px.bar(
                request_station,
                x="median_realized_pct",
                y="station_id",
                orientation="h",
                title="Trung vị thực nhận/yêu cầu theo trạm",
                labels={
                    "station_id": "Mã trạm",
                    "median_realized_pct": "Trung vị thực nhận/yêu cầu (%)",
                    "session_count": "Số phiên có yêu cầu",
                },
                hover_data={"session_count": True, "mean_requested_kwh": ":.1f"},
            )
            fig.add_vline(x=90, line_dash="dash", annotation_text="Mốc 90%")
            st.plotly_chart(fig, width="stretch")

        request_distribution = request_comparison.copy()
        request_distribution["Nhóm thực nhận/yêu cầu"] = pd.cut(
            request_distribution["delivered_vs_requested_pct"],
            bins=[-float("inf"), 50, 90, float("inf")],
            labels=["< 50%", "50% đến dưới 90%", "≥ 90%"],
            right=False,
        )
        request_distribution = (
            request_distribution.groupby("Nhóm thực nhận/yêu cầu", observed=False)
            .agg(session_count=("session_id", "count"))
            .reset_index()
        )
        request_distribution["share_pct"] = (
            100.0 * request_distribution["session_count"] / len(request_comparison)
        )
        st.dataframe(
            request_distribution.rename(
                columns={
                    "Nhóm thực nhận/yêu cầu": "Nhóm tỷ lệ thực nhận/yêu cầu",
                    "session_count": "Số phiên",
                    "share_pct": "Tỷ trọng (%)",
                }
            ).round(2),
            width="stretch",
            hide_index=True,
        )
        st.info(
            f"Trong nhóm có dữ liệu yêu cầu, trung vị tỷ lệ thực nhận/yêu cầu là "
            f"{request_ratio_median:.1f}% (trung bình {request_ratio_mean:.1f}%); "
            f"{request_90_share:.1f}% phiên đạt ít nhất 90%. Khoảng cách này có thể liên quan "
            "đến thời gian sẵn sàng, việc người dùng thay đổi yêu cầu hoặc điều kiện sạc; "
            "bản dữ liệu hiện tại không đủ để kết luận nguyên nhân."
        )
        st.warning(
            f"Giới hạn: chỉ {len(request_comparison):,}/{total_sessions:,} phiên ({request_coverage:.1f}%) "
            "có userInputs. API cho phép người dùng cập nhật yêu cầu trong phiên; dữ liệu hiện tại "
            "không có trường năng lượng đã cấp tại đúng thời điểm mỗi lần cập nhật. Vì vậy, đây là "
            "so sánh giữa yêu cầu cuối cùng được ghi nhận và tổng điện năng cuối phiên, không phải "
            "tỷ lệ đáp ứng dịch vụ hoặc đánh giá hiệu suất thiết bị."
        )


render_dashboard()
