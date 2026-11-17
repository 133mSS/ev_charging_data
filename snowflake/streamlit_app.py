"""JPL EV Charging Analytics dashboard for Streamlit in Snowflake.

Create a Streamlit app in Snowsight and select this file as the app entry point.
The app uses the active Snowpark session; no local PostgreSQL/psycopg2 is needed.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from snowflake.snowpark.context import get_active_session


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
    q1 = query("""
        SELECT
            DAYOFWEEKISO(LOCAL_DATE) AS DAY_OF_WEEK,
            DAYNAME(LOCAL_DATE) AS DAY_NAME,
            LOCAL_HOUR,
            COUNT(*) AS SESSION_COUNT,
            SUM(ENERGY_KWH) AS ENERGY_KWH
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS
        WHERE LOCAL_DATE >= ? AND LOCAL_DATE < ?
        GROUP BY DAYOFWEEKISO(LOCAL_DATE), DAYNAME(LOCAL_DATE), LOCAL_HOUR
        ORDER BY DAY_OF_WEEK, LOCAL_HOUR
    """, params)
    if q1.empty:
        st.info("Không có phiên sạc trong khoảng đang chọn.")
    else:
        pivot = q1.pivot(index="DAY_NAME", columns="LOCAL_HOUR", values="SESSION_COUNT").fillna(0)
        order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        pivot = pivot.reindex([x for x in order if x in pivot.index])
        fig = px.imshow(
            pivot,
            aspect="auto",
            labels={"x": "Giờ bắt đầu (Los Angeles)", "y": "Ngày trong tuần", "color": "Số phiên"},
            title="Heatmap số phiên bắt đầu theo thứ × giờ",
        )
        st.plotly_chart(fig, use_container_width=True)

        weekday_weekend = query("""
            WITH CALENDAR_DAYS AS (
                SELECT DATEADD(DAY, DAY_OFFSET, START_DATE)::DATE AS LOCAL_DATE
                FROM (
                    SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS DAY_OFFSET,
                           TO_DATE(?) AS START_DATE
                    FROM TABLE(GENERATOR(ROWCOUNT => 4000))
                )
                WHERE DATEADD(DAY, DAY_OFFSET, START_DATE)::DATE < TO_DATE(?)
            ),
            DAY_TYPES AS (
                SELECT
                    LOCAL_DATE,
                    IFF(DAYOFWEEKISO(LOCAL_DATE) IN (6,7), 'Cuối tuần', 'Ngày thường') AS DAY_TYPE
                FROM CALENDAR_DAYS
            ),
            COUNTS AS (
                SELECT DAY_TYPE, COUNT(*) AS CALENDAR_DAYS
                FROM DAY_TYPES GROUP BY DAY_TYPE
            ),
            ACTIVITY AS (
                SELECT
                    DT.DAY_TYPE,
                    F.LOCAL_HOUR,
                    COUNT(*) AS SESSION_COUNT,
                    SUM(F.ENERGY_KWH) AS ENERGY_KWH
                FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS F
                JOIN DAY_TYPES DT ON DT.LOCAL_DATE = F.LOCAL_DATE
                GROUP BY DT.DAY_TYPE, F.LOCAL_HOUR
            )
            SELECT
                C.DAY_TYPE,
                H.HOUR_VALUE AS LOCAL_HOUR,
                COALESCE(A.SESSION_COUNT,0) / NULLIF(C.CALENDAR_DAYS,0) AS AVG_SESSIONS_PER_DAY,
                COALESCE(A.ENERGY_KWH,0) / NULLIF(C.CALENDAR_DAYS,0) AS AVG_START_HOUR_KWH_PER_DAY
            FROM COUNTS C
            CROSS JOIN (
                SELECT ROW_NUMBER() OVER (ORDER BY SEQ4()) - 1 AS HOUR_VALUE
                FROM TABLE(GENERATOR(ROWCOUNT => 24))
            ) H
            LEFT JOIN ACTIVITY A
                ON A.DAY_TYPE = C.DAY_TYPE AND A.LOCAL_HOUR = H.HOUR_VALUE
            ORDER BY C.DAY_TYPE, H.HOUR_VALUE
        """, params)
        left, right = st.columns(2)
        with left:
            fig = px.line(
                weekday_weekend, x="LOCAL_HOUR", y="AVG_SESSIONS_PER_DAY",
                color="DAY_TYPE", markers=True,
                title="Số phiên bắt đầu trung bình mỗi ngày",
            )
            st.plotly_chart(fig, use_container_width=True)
        with right:
            fig = px.line(
                weekday_weekend, x="LOCAL_HOUR", y="AVG_START_HOUR_KWH_PER_DAY",
                color="DAY_TYPE", markers=True,
                title="kWh gắn với phiên bắt đầu trung bình mỗi ngày",
            )
            st.plotly_chart(fig, use_container_width=True)
        st.caption("Số phiên và kWh được chuẩn hóa theo số ngày lịch trong từng nhóm. kWh được gán theo giờ bắt đầu phiên, không phải điện năng đo riêng trong giờ đó.")
except Exception as exc:
    show_query_error("Lỗi Q1", exc)

# Q2
st.header("Q2. Mức độ sử dụng ghi nhận khác nhau thế nào giữa các EVSE?")
try:
    q2 = query("""
        SELECT
            STATION_ID,
            COUNT(*) AS SESSION_COUNT,
            SUM(ENERGY_KWH) AS TOTAL_ENERGY_KWH,
            AVG(ENERGY_KWH) AS AVG_ENERGY_PER_SESSION_KWH,
            AVG(CONNECTION_DURATION_MINUTES) AS AVG_CONNECTION_MINUTES,
            100.0 * SUM(ENERGY_KWH) / NULLIF(SUM(SUM(ENERGY_KWH)) OVER (),0) AS ENERGY_SHARE_PCT
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS
        WHERE LOCAL_DATE >= ? AND LOCAL_DATE < ?
        GROUP BY STATION_ID
        ORDER BY TOTAL_ENERGY_KWH DESC
    """, params)
    if not q2.empty:
        left, right = st.columns(2)
        with left:
            st.plotly_chart(
                px.bar(q2, x="STATION_ID", y="SESSION_COUNT", title="Số phiên theo EVSE"),
                use_container_width=True,
            )
        with right:
            st.plotly_chart(
                px.bar(q2, x="STATION_ID", y="TOTAL_ENERGY_KWH", title="Tổng kWh theo EVSE"),
                use_container_width=True,
            )
        st.dataframe(q2, use_container_width=True, hide_index=True)
        top_energy = q2.iloc[0]
        top_sessions = q2.loc[q2["SESSION_COUNT"].idxmax()]
        st.info(
            f"Trạm dẫn đầu về năng lượng: {top_energy['STATION_ID']} "
            f"({float(top_energy['TOTAL_ENERGY_KWH']):,.1f} kWh); "
            f"trạm có nhiều phiên nhất: {top_sessions['STATION_ID']} "
            f"({int(top_sessions['SESSION_COUNT']):,} phiên)."
        )
except Exception as exc:
    show_query_error("Lỗi Q2", exc)

# Q3
st.header("Q3. Thời lượng kết nối và khoảng thời gian sau mẫu dòng sạc cuối")
try:
    q3a = query("""
        SELECT
            CASE
                WHEN CONNECTION_DURATION_MINUTES < 60 THEN '< 1 giờ'
                WHEN CONNECTION_DURATION_MINUTES < 180 THEN '1–3 giờ'
                WHEN CONNECTION_DURATION_MINUTES < 360 THEN '3–6 giờ'
                ELSE '>= 6 giờ'
            END AS DURATION_GROUP,
            COUNT(*) AS SESSION_COUNT,
            AVG(CONNECTION_DURATION_MINUTES) AS AVG_CONNECTION_MINUTES,
            AVG(ENERGY_KWH) AS AVG_ENERGY_KWH
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS
        WHERE LOCAL_DATE >= ? AND LOCAL_DATE < ?
          AND CONNECTION_DURATION_MINUTES >= 0
        GROUP BY DURATION_GROUP
        ORDER BY MIN(CONNECTION_DURATION_MINUTES)
    """, params)
    if not q3a.empty:
        st.plotly_chart(
            px.bar(q3a, x="DURATION_GROUP", y="SESSION_COUNT", title="Số phiên theo nhóm thời lượng kết nối"),
            use_container_width=True,
        )
        st.dataframe(q3a, use_container_width=True, hide_index=True)

    q3b = query("""
        SELECT
            COUNT(*) AS VALID_SESSIONS,
            MEDIAN(POST_LAST_CURRENT_MINUTES) AS MEDIAN_POST_CURRENT_MINUTES,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY POST_LAST_CURRENT_MINUTES) AS P95_POST_CURRENT_MINUTES,
            COUNT_IF(POST_LAST_CURRENT_MINUTES > 30) AS SESSIONS_OVER_30_MIN,
            COUNT_IF(POST_LAST_CURRENT_MINUTES > 60) AS SESSIONS_OVER_60_MIN
        FROM JPL_ANALYTICS.MART.SESSION_POST_CURRENT
        WHERE LOCAL_DATE >= ? AND LOCAL_DATE < ?
          AND POST_LAST_CURRENT_MINUTES >= 0
    """, params)
    qrow = q3b.iloc[0]
    a, b, c = st.columns(3)
    a.metric("Phiên đủ mốc dòng điện", f"{int(numeric_or_zero(qrow['VALID_SESSIONS'])):,}")
    b.metric("Trung vị sau mẫu cuối", f"{numeric_or_zero(qrow['MEDIAN_POST_CURRENT_MINUTES']):.1f} phút")
    c.metric("P95 sau mẫu cuối", f"{numeric_or_zero(qrow['P95_POST_CURRENT_MINUTES']):.1f} phút")
    st.caption("Mốc cuối được tính trực tiếp từ timestamp có charging_current_a > 0 trong Static. Chỉ các phiên ghép được với API mới có disconnect_time để tính khoảng sau kết nối.")
except Exception as exc:
    show_query_error("Lỗi Q3; kiểm tra MART.SESSION_POST_CURRENT và dữ liệu Static", exc)

# Q4
st.header("Q4. Năng lượng yêu cầu so với năng lượng thực nhận")
try:
    q4 = query("""
        WITH LATEST_REQUEST AS (
            SELECT *
            FROM JPL_ANALYTICS.WAREHOUSE.FACT_USER_REQUESTS
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY SESSION_ID
                ORDER BY MODIFIED_AT DESC NULLS LAST, INPUT_ID DESC
            ) = 1
        )
        SELECT
            F.SESSION_ID,
            F.STATION_ID,
            F.ENERGY_KWH AS DELIVERED_KWH,
            L.KWH_REQUESTED,
            100.0 * F.ENERGY_KWH / NULLIF(L.KWH_REQUESTED,0) AS DELIVERED_VS_REQUESTED_PCT
        FROM JPL_ANALYTICS.WAREHOUSE.FACT_CHARGING_SESSIONS F
        JOIN LATEST_REQUEST L USING (SESSION_ID)
        WHERE F.LOCAL_DATE >= ? AND F.LOCAL_DATE < ?
          AND L.KWH_REQUESTED > 0
    """, params)
    if not q4.empty:
        ratio = pd.to_numeric(q4["DELIVERED_VS_REQUESTED_PCT"], errors="coerce")
        a, b, c = st.columns(3)
        a.metric("Phiên có yêu cầu hợp lệ", f"{len(q4):,}")
        b.metric("Trung vị thực nhận/yêu cầu", f"{ratio.median():.1f}%")
        c.metric("Phiên đạt ≥ 90%", f"{100 * (ratio >= 90).mean():.1f}%")
        lim = float(max(q4["KWH_REQUESTED"].max(), q4["DELIVERED_KWH"].max())) * 1.05
        fig = px.scatter(
            q4, x="KWH_REQUESTED", y="DELIVERED_KWH", color="STATION_ID",
            hover_data=["SESSION_ID", "DELIVERED_VS_REQUESTED_PCT"],
            title="kWh yêu cầu cuối cùng và kWh thực nhận",
        )
        fig.add_shape(type="line", x0=0, y0=0, x1=lim, y1=lim, line={"dash":"dash"})
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Chọn bản userInputs mới nhất theo modified_at rồi mới lọc kWh_requested > 0. Phép so sánh mô tả không chứng minh nguyên nhân chênh lệch.")
    else:
        st.info("Không có phiên nào có yêu cầu kWh hợp lệ trong khoảng đang chọn.")
except Exception as exc:
    show_query_error("Lỗi Q4", exc)

# Q5
st.header("Q5. Power quan sát và độ bao phủ dữ liệu theo thời gian")
try:
    power_summary = query("""
        SELECT
            SUM(TOTAL_SAMPLES) AS TOTAL_SAMPLES,
            SUM(POWER_SAMPLES) AS POWER_SAMPLES,
            100.0 * SUM(POWER_SAMPLES) / NULLIF(SUM(TOTAL_SAMPLES),0) AS POWER_ROW_COVERAGE_PCT,
            COUNT(*) AS STATION_HOUR_BUCKETS,
            COUNT(DISTINCT STATION_ID) AS STATIONS
        FROM JPL_ANALYTICS.MART.POWER_STATION_HOUR
        WHERE LOCAL_MONTH >= TO_DATE(?) AND LOCAL_MONTH < TO_DATE(?)
    """, params)
    prow = power_summary.iloc[0]
    if numeric_or_zero(prow["TOTAL_SAMPLES"]) == 0:
        st.warning(
            "Chưa có Static measurements trong Snowflake. Q5 chỉ hiển thị đầy đủ sau khi "
            "chạy scripts/deploy_snowflake.py --include-static và tạo Power marts."
        )
    a, b, c, d = st.columns(4)
    a.metric("Static samples", f"{int(numeric_or_zero(prow['TOTAL_SAMPLES'])):,}")
    b.metric("Power row coverage", f"{numeric_or_zero(prow['POWER_ROW_COVERAGE_PCT']):.2f}%")
    c.metric("Station-hour buckets", f"{int(numeric_or_zero(prow['STATION_HOUR_BUCKETS'])):,}")
    d.metric("EVSE có quan sát", f"{int(numeric_or_zero(prow['STATIONS'])):,}")

    monthly_power = query("""
        SELECT *
        FROM JPL_ANALYTICS.MART.POWER_STATION_MONTH
        WHERE LOCAL_MONTH >= TO_DATE(?) AND LOCAL_MONTH < TO_DATE(?)
        ORDER BY LOCAL_MONTH, STATION_ID
    """, params)
    if not monthly_power.empty:
        # Complete EVSE × month grid: no row means no observation, not zero Power.
        station_ids = sorted(monthly_power["STATION_ID"].dropna().unique().tolist())
        monthly_power["MONTH_LABEL"] = pd.to_datetime(
            monthly_power["LOCAL_MONTH"]
        ).dt.strftime("%Y-%m")
        month_values = sorted(monthly_power["MONTH_LABEL"].unique().tolist())
        complete_index = pd.MultiIndex.from_product(
            [station_ids, month_values], names=["STATION_ID", "MONTH_LABEL"]
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
            MEAN_STATION_COVERAGE_PCT=("CALENDAR_HOUR_OBSERVATION_PCT", "mean"),
            MEDIAN_STATION_COVERAGE_PCT=("CALENDAR_HOUR_OBSERVATION_PCT", "median"),
            STATIONS_WITH_OBSERVATION=("OBSERVED_UTC_HOURS", lambda x: int((x > 0).sum())),
        )
        left, right = st.columns(2)
        with left:
            st.plotly_chart(
                px.line(coverage, x="MONTH_LABEL",
                        y=["MEAN_STATION_COVERAGE_PCT", "MEDIAN_STATION_COVERAGE_PCT"],
                        markers=True, title="Coverage giờ có quan sát trung bình/trung vị theo tháng"),
                use_container_width=True,
            )
        with right:
            st.plotly_chart(
                px.bar(coverage, x="MONTH_LABEL", y="STATIONS_WITH_OBSERVATION",
                       title="Số EVSE có ít nhất một quan sát trong tháng"),
                use_container_width=True,
            )
        st.plotly_chart(
            px.imshow(
                complete.pivot(index="STATION_ID", columns="MONTH_LABEL",
                               values="CALENDAR_HOUR_OBSERVATION_PCT").fillna(0),
                aspect="auto",
                labels={"x":"Tháng","y":"EVSE","color":"Giờ có quan sát (%)"},
                title="Heatmap coverage EVSE × tháng (tháng không quan sát = 0%)",
            ),
            use_container_width=True,
        )

    site_hour_profile = query("""
        SELECT
            LOCAL_HOUR,
            AVG(STATIONS_WITH_POWER) AS AVG_EVSE_WITH_POWER,
            MAX(STATIONS_WITH_POWER) AS MAX_EVSE_WITH_POWER,
            AVG(SELECTED_STATION_POWER_COVERAGE_PCT) AS AVG_HOURLY_COVERAGE_PCT,
            COUNT_IF(SITE_HOUR_HAS_ANY_OBSERVATION) AS DAYS_HOURS_WITH_OBSERVATION
        FROM JPL_ANALYTICS.MART.POWER_SITE_HOUR
        WHERE LOCAL_DATE >= TO_DATE(?) AND LOCAL_DATE < TO_DATE(?)
        GROUP BY LOCAL_HOUR
        ORDER BY LOCAL_HOUR
    """, params)
    if not site_hour_profile.empty:
        st.plotly_chart(
            px.line(
                site_hour_profile,
                x="LOCAL_HOUR",
                y=["AVG_EVSE_WITH_POWER", "MAX_EVSE_WITH_POWER"],
                markers=True,
                title="Số EVSE có ít nhất một mẫu Power theo giờ địa phương",
                labels={"LOCAL_HOUR": "Giờ", "value": "Số EVSE", "variable": "Chỉ số"},
            ),
            use_container_width=True,
        )
        st.dataframe(site_hour_profile, use_container_width=True, hide_index=True)

    hod = query("""
        SELECT
            LOCAL_HOUR,
            AVG(AVG_POWER_KW) AS MEAN_STATION_HOUR_POWER_KW,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY AVG_POWER_KW) AS P95_STATION_HOUR_POWER_KW,
            COUNT(*) AS STATION_HOUR_OBSERVATIONS,
            COUNT(DISTINCT STATION_ID) AS STATIONS_OBSERVED,
            SUM(POWER_SAMPLES) AS POWER_SAMPLES,
            SUM(TOTAL_SAMPLES) AS TOTAL_SAMPLES
        FROM JPL_ANALYTICS.MART.POWER_STATION_HOUR
        WHERE LOCAL_MONTH >= TO_DATE(?) AND LOCAL_MONTH < TO_DATE(?)
          AND POWER_SAMPLES > 0
        GROUP BY LOCAL_HOUR
        ORDER BY LOCAL_HOUR
    """, params)
    if not hod.empty:
        st.plotly_chart(
            px.line(hod, x="LOCAL_HOUR",
                    y=["MEAN_STATION_HOUR_POWER_KW","P95_STATION_HOUR_POWER_KW"],
                    markers=True, title="Phân bố Power trung bình/P95 theo giờ địa phương"),
            use_container_width=True,
        )
    st.warning(
        "Static là chuỗi phép đo theo phiên, không phải telemetry 24/7. "
        "Giờ không có bản ghi không đồng nghĩa EVSE hỏng. "
        "Trung bình station-hour giữa các trạm không đồng bộ; không cộng chúng để gọi là tổng phụ tải JPL."
    )
except Exception as exc:
    st.error(
        "Chưa có Power marts hoặc dữ liệu Static chưa được nạp. "
        "Hãy chạy scripts/deploy_snowflake.py --include-static và kiểm tra "
        "snowflake/03_power_marts.sql."
    )
    st.exception(exc)

st.caption("Nguồn: ACN-Data API và ACN-Data Static — JPL Arroyo Garage 01. Mọi kết luận phải được diễn giải trong giới hạn độ bao phủ và dữ liệu quan sát.")
