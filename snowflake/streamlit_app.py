"""JPL EV Charging Analytics dashboard for Streamlit in Snowflake.

Create a Streamlit app in Snowsight and select this file as the app entry point.
The app uses the active Snowpark session; no local PostgreSQL/psycopg2 is needed.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from snowflake.snowpark.context import get_active_session

from analytics_queries import (
    Q1_WEEKDAY_HOUR_SQL,
    Q1_WEEKDAY_WEEKEND_SQL,
    Q2_STATION_USAGE_SQL,
    Q3_CONNECTION_DURATION_SQL,
    Q3_POST_LAST_CURRENT_SQL,
    Q4_LATEST_REQUESTS_SQL,
    Q4_TOTAL_SESSIONS_SQL,
    Q5_POWER_SUMMARY_SQL,
    Q5_MONTHLY_POWER_SQL,
    Q5_STATION_SCOPE_SQL,
    Q5_SITE_HOUR_SUMMARY_SQL,
    Q5_SITE_HOUR_PROFILE_SQL,
    Q5_HOUR_OF_DAY_POWER_SQL,
)


st.set_page_config(
    page_title="JPL EV Charging Analytics",
    page_icon="⚡",
    layout="wide",
)

session = get_active_session()


def query(sql: str, params: list | None = None) -> pd.DataFrame:
    return session.sql(sql, params=params or []).to_pandas()


def show_query_error(title: str, error: Exception) -> None:
    st.error(f"{title}: {error}")


def numeric_or_zero(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    return float(value)


st.title("⚡ JPL EV Charging Analytics")
st.caption(
    "ACN-Data — JPL Arroyo Garage 01 | Snowflake Data Warehouse | "
    "Phân tích nhu cầu sạc, mức sử dụng EVSE, thời gian kết nối, năng lượng yêu cầu "
    "và công suất quan sát."
)
st.info(
    "Dashboard chính trả lời năm câu hỏi nghiên cứu. Số liệu sử dụng API sessions, "
    "userInputs và Static measurements gốc. Các mẫu Static không được tự điền thành 0; "
    "các trung bình station-hour không được diễn giải thành phụ tải đồng thời toàn site."
)

try:
    bounds = query("""
        SELECT MIN(LOCAL_DATE) AS MIN_DATE, MAX(LOCAL_DATE) AS MAX_DATE
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS
    """)
    min_date = pd.to_datetime(bounds.loc[0, "MIN_DATE"]).date()
    max_date = pd.to_datetime(bounds.loc[0, "MAX_DATE"]).date()
except Exception as exc:
    st.error(
        "Chưa truy cập được warehouse JPL. Hãy chạy snowflake/00_bootstrap.sql, "
        "nạp dữ liệu RAW và chạy snowflake/02_warehouse.sql trước."
    )
    st.exception(exc)
    st.stop()

month_values = pd.period_range(
    pd.Timestamp(min_date).to_period("M"),
    pd.Timestamp(max_date).to_period("M"),
    freq="M",
).astype(str).tolist()

with st.sidebar:
    st.header("Bộ lọc")
    selected = st.select_slider(
        "Khoảng tháng",
        options=month_values,
        value=(month_values[0], month_values[-1]),
    )
    start_month, end_month = selected
    start_date = f"{start_month}-01"
    end_date_exclusive = str((pd.Period(end_month, freq="M") + 1).start_time.date())
    st.caption("Múi giờ hiển thị: America/Los_Angeles")
    if st.button("Làm mới dữ liệu"):
        st.rerun()

params = [start_date, end_date_exclusive]

# Overview
try:
    overview = query("""
        SELECT
            COUNT(*) AS SESSION_COUNT,
            SUM(ENERGY_KWH) AS TOTAL_ENERGY_KWH,
            AVG(ENERGY_KWH) AS AVG_ENERGY_PER_SESSION_KWH
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS
        WHERE LOCAL_DATE >= ? AND LOCAL_DATE < ?
    """, params)
    row = overview.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Tổng phiên sạc", f"{int(numeric_or_zero(row['SESSION_COUNT'])):,}")
    c2.metric("Tổng năng lượng", f"{numeric_or_zero(row['TOTAL_ENERGY_KWH']):,.1f} kWh")
    c3.metric("Năng lượng trung bình/phiên", f"{numeric_or_zero(row['AVG_ENERGY_PER_SESSION_KWH']):,.2f} kWh")
except Exception as exc:
    show_query_error("Không tải được KPI tổng quan", exc)
    st.stop()

# Q1
st.header("Q1. Nhu cầu sạc tập trung vào ngày nào và khung giờ nào?")
try:
    q1 = query(Q1_WEEKDAY_HOUR_SQL, params)
    if q1.empty:
        st.info("Không có phiên sạc trong khoảng đang chọn.")
    else:
        weekday_order = [
            "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
            "Thứ Sáu", "Thứ Bảy", "Chủ Nhật",
        ]
        pivot = q1.pivot(
            index="DAY_NAME", columns="LOCAL_HOUR", values="SESSION_COUNT"
        ).fillna(0)
        pivot = pivot.reindex(
            index=weekday_order,
            columns=list(range(24)),
            fill_value=0,
        )
        fig = px.imshow(
            pivot,
            aspect="auto",
            labels={
                "x": "Giờ bắt đầu (America/Los_Angeles)",
                "y": "Ngày trong tuần",
                "color": "Số phiên",
            },
            title="Heatmap số phiên bắt đầu theo thứ × giờ",
        )
        st.plotly_chart(fig, use_container_width=True)

        weekday_weekend = query(Q1_WEEKDAY_WEEKEND_SQL, params)
        left, right = st.columns(2)
        with left:
            fig = px.line(
                weekday_weekend,
                x="LOCAL_HOUR",
                y="AVG_SESSIONS_PER_DAY",
                color="DAY_TYPE",
                markers=True,
                title="Số phiên bắt đầu trung bình mỗi ngày",
                labels={
                    "LOCAL_HOUR": "Giờ bắt đầu",
                    "AVG_SESSIONS_PER_DAY": "Phiên/ngày",
                    "DAY_TYPE": "Nhóm ngày",
                },
            )
            st.plotly_chart(fig, use_container_width=True)
        with right:
            fig = px.line(
                weekday_weekend,
                x="LOCAL_HOUR",
                y="AVG_START_HOUR_KWH_PER_DAY",
                color="DAY_TYPE",
                markers=True,
                title="kWh gắn với phiên bắt đầu trung bình mỗi ngày",
                labels={
                    "LOCAL_HOUR": "Giờ bắt đầu",
                    "AVG_START_HOUR_KWH_PER_DAY": "kWh/ngày",
                    "DAY_TYPE": "Nhóm ngày",
                },
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Số phiên và kWh được chuẩn hóa theo số ngày lịch trong từng nhóm. "
            "kWh được gán theo giờ bắt đầu phiên, không phải điện năng đo riêng trong giờ đó."
        )
except Exception as exc:
    show_query_error("Lỗi Q1", exc)

# Q2
st.header("Q2. Mức độ sử dụng ghi nhận khác nhau thế nào giữa các EVSE?")
try:
    q2 = query(Q2_STATION_USAGE_SQL, params)
    if not q2.empty:
        q2_by_sessions = q2.sort_values(
            "SESSION_COUNT", ascending=False
        ).reset_index(drop=True)
        q2_by_energy = q2.sort_values(
            "TOTAL_ENERGY_KWH", ascending=False
        ).reset_index(drop=True)
        left, right = st.columns(2)
        with left:
            fig = px.bar(
                q2_by_sessions,
                x="STATION_ID",
                y="SESSION_COUNT",
                title="Số phiên theo EVSE (xếp hạng theo số phiên)",
                labels={"STATION_ID": "EVSE", "SESSION_COUNT": "Số phiên"},
            )
            fig.update_xaxes(tickangle=-90)
            st.plotly_chart(fig, use_container_width=True)
        with right:
            fig = px.bar(
                q2_by_energy,
                x="STATION_ID",
                y="TOTAL_ENERGY_KWH",
                title="Tổng năng lượng theo EVSE (xếp hạng theo kWh)",
                labels={"STATION_ID": "EVSE", "TOTAL_ENERGY_KWH": "Năng lượng (kWh)"},
            )
            fig.update_xaxes(tickangle=-90)
            st.plotly_chart(fig, use_container_width=True)
        display_q2 = q2.rename(columns={
            "STATION_ID": "Mã EVSE",
            "SESSION_COUNT": "Số phiên",
            "TOTAL_ENERGY_KWH": "Tổng năng lượng (kWh)",
            "AVG_ENERGY_PER_SESSION_KWH": "kWh trung bình/phiên",
            "AVG_CONNECTION_MINUTES": "Thời lượng kết nối TB (phút)",
            "ENERGY_SHARE_PCT": "Tỷ trọng năng lượng (%)",
        })
        st.dataframe(display_q2, use_container_width=True, hide_index=True)
        top_energy = q2.iloc[0]
        top_sessions = q2.loc[q2["SESSION_COUNT"].idxmax()]
        st.info(
            f"EVSE dẫn đầu về năng lượng: {top_energy['STATION_ID']} "
            f"({float(top_energy['TOTAL_ENERGY_KWH']):,.1f} kWh); "
            f"EVSE có nhiều phiên nhất: {top_sessions['STATION_ID']} "
            f"({int(top_sessions['SESSION_COUNT']):,} phiên)."
        )
except Exception as exc:
    show_query_error("Lỗi Q2", exc)

# Q3
st.header("Q3. Thời lượng kết nối và khoảng từ mẫu dòng điện dương cuối đến lúc ngắt kết nối")
try:
    q3a = query(Q3_CONNECTION_DURATION_SQL, params)
    if not q3a.empty:
        st.plotly_chart(
            px.bar(
                q3a,
                x="DURATION_GROUP",
                y="SESSION_COUNT",
                title="Số phiên theo nhóm thời lượng kết nối",
                labels={"DURATION_GROUP": "Thời lượng kết nối", "SESSION_COUNT": "Số phiên"},
            ),
            use_container_width=True,
        )
        display_q3 = q3a.rename(columns={
            "DURATION_GROUP": "Nhóm thời lượng",
            "SESSION_COUNT": "Số phiên",
            "AVG_CONNECTION_MINUTES": "Kết nối trung bình (phút)",
            "AVG_ENERGY_KWH": "Năng lượng TB (kWh)",
        })
        st.dataframe(display_q3, use_container_width=True, hide_index=True)

    q3b = query(Q3_POST_LAST_CURRENT_SQL, params)
    qrow = q3b.iloc[0]
    a, b, c = st.columns(3)
    a.metric("Phiên đủ điều kiện", f"{int(numeric_or_zero(qrow['VALID_SESSIONS'])):,}")
    b.metric(
        "Trung vị từ mẫu dòng điện dương cuối",
        f"{numeric_or_zero(qrow['MEDIAN_POST_CURRENT_MINUTES']):.1f} phút",
    )
    c.metric(
        "P95 từ mẫu dòng điện dương cuối",
        f"{numeric_or_zero(qrow['P95_POST_CURRENT_MINUTES']):.1f} phút",
    )
    st.caption(
        "Khoảng thời gian được tính từ timestamp cuối cùng có charging_current_a > 0 "
        "trong Static đến disconnect_time của API. Đây không phải thời điểm pin đầy hay "
        "thời điểm sạc kết thúc chính xác; kết quả chỉ có ở các phiên ghép API–Static hợp lệ."
    )
except Exception as exc:
    show_query_error("Lỗi Q3; kiểm tra MART.SESSION_POST_CURRENT và dữ liệu Static", exc)

# Q4
st.header("Q4. Năng lượng yêu cầu so với năng lượng thực nhận")
try:
    q4 = query(Q4_LATEST_REQUESTS_SQL, params)
    total_sessions_df = query(Q4_TOTAL_SESSIONS_SQL, params)
    total_sessions = int(numeric_or_zero(total_sessions_df.iloc[0]["TOTAL_SESSIONS"]))
    valid_request_sessions = len(q4)
    request_coverage_pct = (
        100.0 * valid_request_sessions / total_sessions if total_sessions else 0.0
    )

    a, b, c, d, e = st.columns(5)
    a.metric("Tổng phiên trong phạm vi lọc", f"{total_sessions:,}")
    b.metric("Phiên có yêu cầu hợp lệ", f"{valid_request_sessions:,}")
    c.metric("Độ bao phủ yêu cầu hợp lệ", f"{request_coverage_pct:.2f}%")
    if not q4.empty:
        ratio = pd.to_numeric(
            q4["DELIVERED_VS_REQUESTED_PCT"], errors="coerce"
        ).dropna()
        d.metric(
            "Trung vị thực nhận/yêu cầu",
            f"{ratio.median():.1f}%" if not ratio.empty else "N/A",
        )
        achieved_90_pct = (
            100.0 * float((ratio >= 90).mean()) if not ratio.empty else 0.0
        )
        e.metric(
            "Phiên đạt ≥ 90% yêu cầu",
            f"{achieved_90_pct:.1f}%" if not ratio.empty else "N/A",
            help="Tỷ lệ tính trên các phiên có yêu cầu kWh hợp lệ và tỷ lệ thực nhận/yêu cầu tính được.",
        )
        lim = float(max(q4["KWH_REQUESTED"].max(), q4["DELIVERED_KWH"].max())) * 1.05
        fig = px.scatter(
            q4,
            x="KWH_REQUESTED",
            y="DELIVERED_KWH",
            hover_name="STATION_ID",
            hover_data=["SESSION_ID", "DELIVERED_VS_REQUESTED_PCT"],
            title="kWh yêu cầu cuối cùng và kWh thực nhận",
            render_mode="svg",
            labels={
                "KWH_REQUESTED": "Năng lượng yêu cầu (kWh)",
                "DELIVERED_KWH": "Năng lượng thực nhận (kWh)",
                "STATION_ID": "EVSE",
                "SESSION_ID": "Mã phiên",
                "DELIVERED_VS_REQUESTED_PCT": "Thực nhận/yêu cầu (%)",
            },
        )
        # A single color keeps the chart focused on the relationship between
        # requested and delivered energy; EVSE identity remains available on hover.
        fig.update_traces(
            marker={
                "color": "#4C8BF5",
                "size": 6,
                "opacity": 0.45,
                "line": {"width": 0},
            }
        )
        fig.add_shape(
            type="line",
            x0=0,
            y0=0,
            x1=lim,
            y1=lim,
            line={"color": "#F59E0B", "dash": "dash", "width": 2},
        )
        # Equal axis ranges and scale ensure the y=x reference is visually truthful.
        fig.update_xaxes(range=[0, lim], title="Năng lượng yêu cầu (kWh)")
        fig.update_yaxes(
            range=[0, lim],
            title="Năng lượng thực nhận (kWh)",
            scaleanchor="x",
            scaleratio=1,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(
            "Mỗi điểm đại diện một phiên sạc; tất cả điểm dùng cùng màu để dễ quan sát mật độ. "
            "Di chuột lên điểm để xem mã EVSE, mã phiên và tỷ lệ thực nhận/yêu cầu. "
            "Đường nét đứt y = x biểu thị mức thực nhận bằng yêu cầu: điểm dưới đường là "
            "thực nhận thấp hơn yêu cầu, điểm trên đường là cao hơn. "
            "Chọn userInputs mới nhất theo modified_at và input_id trước khi lọc "
            "kWh_requested > 0. Độ bao phủ = số phiên có yêu cầu kWh hợp lệ / tổng phiên "
            "trong khoảng lọc. Tỷ lệ thực nhận/yêu cầu là so sánh mô tả, không chứng minh nguyên nhân chênh lệch."
        )
    else:
        d.metric("Trung vị thực nhận/yêu cầu", "N/A")
        e.metric("Phiên đạt ≥ 90% yêu cầu", "N/A")
        st.info("Không có phiên nào có yêu cầu kWh hợp lệ trong khoảng đang chọn.")
except Exception as exc:
    show_query_error("Lỗi Q4", exc)

# Q5
st.header("Q5. Power quan sát và độ bao phủ dữ liệu theo thời gian")
POWER_START_DATE = "2020-07-01"
POWER_END_DATE_EXCLUSIVE = "2020-12-01"
power_start_date = max(start_date, POWER_START_DATE)
power_end_date = min(end_date_exclusive, POWER_END_DATE_EXCLUSIVE)

if power_start_date >= power_end_date:
    st.info(
        "Q5 chỉ có dữ liệu Power trong cửa sổ phân tích 07/2020–11/2020. "
        "Hãy điều chỉnh khoảng tháng để giao với cửa sổ này."
    )
else:
    power_params = [power_start_date, power_end_date]
    try:
        power_summary = query(Q5_POWER_SUMMARY_SQL, power_params)
        site_hour_summary = query(Q5_SITE_HOUR_SUMMARY_SQL, power_params)
        prow = power_summary.iloc[0]
        srow = site_hour_summary.iloc[0]

        a, b, c, d, e = st.columns(5)
        a.metric("Static samples", f"{int(numeric_or_zero(prow['TOTAL_SAMPLES'])):,}")
        b.metric("Power samples", f"{int(numeric_or_zero(prow['POWER_SAMPLES'])):,}")
        c.metric(
            "Power row coverage",
            f"{numeric_or_zero(prow['POWER_ROW_COVERAGE_PCT']):.2f}%",
            help="Power samples / toàn bộ hàng Static trong cửa sổ đã chọn.",
        )
        e.metric(
            "Site-hour coverage",
            f"{numeric_or_zero(srow['SITE_HOUR_OBSERVATION_COVERAGE_PCT']):.1f}%",
            help=(
                f"{int(numeric_or_zero(srow['HOURS_WITH_OBSERVATION'])):,} / "
                f"{int(numeric_or_zero(srow['EXPECTED_UTC_HOURS'])):,} giờ UTC có ít nhất "
                "một EVSE ghi nhận."
            ),
        )
        d.metric("EVSE có quan sát", f"{int(numeric_or_zero(prow['STATIONS'])):,}")
        st.caption(
            f"Station-hour buckets: {int(numeric_or_zero(prow['STATION_HOUR_BUCKETS'])):,} · "
            f"Giờ UTC có quan sát: {int(numeric_or_zero(srow['HOURS_WITH_OBSERVATION'])):,} · "
            f"Không có quan sát: {int(numeric_or_zero(srow['HOURS_WITHOUT_OBSERVATION'])):,}."
        )

        monthly_power = query(Q5_MONTHLY_POWER_SQL, power_params)
        station_scope = query(Q5_STATION_SCOPE_SQL)
        station_ids = station_scope["STATION_ID"].dropna().astype(str).tolist()
        first_month = pd.Period(pd.Timestamp(power_start_date), freq="M")
        last_month = pd.Period(
            pd.Timestamp(power_end_date) - pd.Timedelta(days=1), freq="M"
        )
        month_values = [
            str(month)
            for month in pd.period_range(first_month, last_month, freq="M")
        ]

        if station_ids and month_values:
            if not monthly_power.empty:
                monthly_power["MONTH_LABEL"] = pd.to_datetime(
                    monthly_power["LOCAL_MONTH"]
                ).dt.strftime("%Y-%m")
            else:
                monthly_power["MONTH_LABEL"] = pd.Series(dtype="object")

            complete_index = pd.MultiIndex.from_product(
                [station_ids, month_values],
                names=["STATION_ID", "MONTH_LABEL"],
            )
            complete = (
                monthly_power.set_index(["STATION_ID", "MONTH_LABEL"])
                .reindex(complete_index)
                .reset_index()
            )
            complete["CALENDAR_HOUR_OBSERVATION_PCT"] = pd.to_numeric(
                complete["CALENDAR_HOUR_OBSERVATION_PCT"], errors="coerce"
            ).fillna(0.0)
            complete["OBSERVED_UTC_HOURS"] = pd.to_numeric(
                complete["OBSERVED_UTC_HOURS"], errors="coerce"
            ).fillna(0)
            coverage = complete.groupby("MONTH_LABEL", as_index=False).agg(
                MEAN_STATION_COVERAGE_PCT=(
                    "CALENDAR_HOUR_OBSERVATION_PCT", "mean"
                ),
                MEDIAN_STATION_COVERAGE_PCT=(
                    "CALENDAR_HOUR_OBSERVATION_PCT", "median"
                ),
                STATIONS_WITH_OBSERVATION=(
                    "OBSERVED_UTC_HOURS", lambda values: int((values > 0).sum())
                ),
            )
            coverage_plot = coverage.rename(columns={
                "MEAN_STATION_COVERAGE_PCT": "Coverage trung bình",
                "MEDIAN_STATION_COVERAGE_PCT": "Coverage trung vị",
            })
            left, right = st.columns(2)
            with left:
                st.plotly_chart(
                    px.line(
                        coverage_plot,
                        x="MONTH_LABEL",
                        y=["Coverage trung bình", "Coverage trung vị"],
                        markers=True,
                        title="Coverage giờ có quan sát trung bình/trung vị theo tháng",
                        labels={
                            "MONTH_LABEL": "Tháng",
                            "value": "Giờ có quan sát (%)",
                            "variable": "Chỉ số",
                        },
                    ),
                    use_container_width=True,
                )
            with right:
                st.plotly_chart(
                    px.bar(
                        coverage,
                        x="MONTH_LABEL",
                        y="STATIONS_WITH_OBSERVATION",
                        title="Số EVSE có ít nhất một quan sát trong tháng",
                        labels={
                            "MONTH_LABEL": "Tháng",
                            "STATIONS_WITH_OBSERVATION": "Số EVSE",
                        },
                    ),
                    use_container_width=True,
                )
            st.plotly_chart(
                px.imshow(
                    complete.pivot(
                        index="STATION_ID",
                        columns="MONTH_LABEL",
                        values="CALENDAR_HOUR_OBSERVATION_PCT",
                    ),
                    aspect="auto",
                    labels={"x": "Tháng", "y": "EVSE", "color": "Giờ có quan sát (%)"},
                    title="Heatmap coverage EVSE × tháng (không có quan sát = 0% coverage)",
                ),
                use_container_width=True,
            )

        site_hour_profile = query(Q5_SITE_HOUR_PROFILE_SQL, power_params)
        if not site_hour_profile.empty:
            site_hour_plot = site_hour_profile.rename(columns={
                "AVG_EVSE_WITH_POWER": "EVSE có Power trung bình",
                "MAX_EVSE_WITH_POWER": "EVSE có Power tối đa",
            })
            st.plotly_chart(
                px.line(
                    site_hour_plot,
                    x="LOCAL_HOUR",
                    y=["EVSE có Power trung bình", "EVSE có Power tối đa"],
                    markers=True,
                    title="Số EVSE có ít nhất một mẫu Power theo giờ địa phương",
                    labels={"LOCAL_HOUR": "Giờ", "value": "Số EVSE", "variable": "Chỉ số"},
                ),
                use_container_width=True,
            )
            display_site_hour = site_hour_profile.rename(columns={
                "LOCAL_HOUR": "Giờ địa phương",
                "AVG_EVSE_WITH_POWER": "EVSE có Power trung bình",
                "MAX_EVSE_WITH_POWER": "EVSE có Power tối đa",
                "AVG_HOURLY_COVERAGE_PCT": "Coverage trung bình (%)",
                "HOURS_WITH_OBSERVATION": "Số giờ có quan sát",
            })
            st.dataframe(display_site_hour, use_container_width=True, hide_index=True)

        hod = query(Q5_HOUR_OF_DAY_POWER_SQL, power_params)
        if not hod.empty:
            hod_plot = hod.rename(columns={
                "MEAN_STATION_HOUR_POWER_KW": "Power trung bình (kW)",
                "P95_STATION_HOUR_POWER_KW": "Power P95 (kW)",
            })
            st.plotly_chart(
                px.line(
                    hod_plot,
                    x="LOCAL_HOUR",
                    y=["Power trung bình (kW)", "Power P95 (kW)"],
                    markers=True,
                    title="Phân bố Power trung bình/P95 theo giờ địa phương",
                    labels={
                        "LOCAL_HOUR": "Giờ địa phương",
                        "value": "Power (kW)",
                        "variable": "Chỉ số",
                    },
                ),
                use_container_width=True,
            )
        st.warning(
            "Static là chuỗi phép đo theo phiên, không phải telemetry 24/7. "
            "Giờ không có bản ghi không đồng nghĩa EVSE hỏng. "
            "Trung bình station-hour giữa các trạm không đồng bộ; không cộng chúng để gọi là tổng phụ tải JPL."
        )
        st.caption(
            f"Phạm vi Q5: {power_start_date} đến {power_end_date} (ngày kết thúc không bao gồm). "
            "Độ phủ giờ dùng lưới UTC đầy đủ, bao gồm giờ không có quan sát."
        )
    except Exception as exc:
        st.error(
            "Không tải được phân tích Power. Hãy kiểm tra MART.POWER_STATION_HOUR, "
            "MART.POWER_STATION_MONTH và MART.POWER_SITE_HOUR."
        )
        st.exception(exc)

st.caption("Nguồn: ACN-Data API và ACN-Data Static — JPL Arroyo Garage 01. Mọi kết luận phải được diễn giải trong giới hạn độ bao phủ và dữ liệu quan sát.")
