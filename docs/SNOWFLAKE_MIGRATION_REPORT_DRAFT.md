# Snowflake migration of JPL EV Charging Analytics — report draft

> **Status note:** This draft distinguishes the implemented Snowflake deployment package from the account-side data migration. Replace all pending-execution notes with real Snowsight evidence after running the deployment. Do not describe the Snowflake warehouse or dashboard as operational before the row-count checks pass.

## 1. Migration objective

The project originally used a local PostgreSQL warehouse and local processing for the ACN-Data JPL dataset. The local Static archive contains 27,723 compressed files and the cleaned measurement output contains 175,390,901 rows. Processing and storing this volume on the development laptop created a storage and compute bottleneck.

The migration introduces Snowflake as the unified cloud data platform for data landing, SQL transformation, analytical storage and Streamlit dashboard serving. GitHub remains the version-control system. The original local PostgreSQL pipeline is retained as a reference and fallback during migration.

## 2. Data sources

The project uses genuine ACN-Data sources, not synthetic/generated data:

- ACN-Data API provides charging-session metadata and userInputs.
- ACN-Data Static provides per-session electrical time-series measurements, including charging current, voltage, charging state, cumulative energy and Power.

The two sources complement one another: API records describe the charging session and user request history, while Static records provide electrical measurements during the session. The session mapping table preserves MATCHED, API_ONLY and STATIC_ONLY states rather than forcing unmatched records into an artificial join.

## 3. Snowflake architecture

The target architecture has five logical layers:

1. **RAW:** internal stage and typed landing tables for API sessions, userInputs, Static samples and session mapping.
2. **WAREHOUSE:** station, user, date and time dimensions; charging-session and user-request facts; a full-Static measurement view.
3. **MART:** derived connection-after-last-current metrics and compact station-hour, station-month and site-hour Power aggregates.
4. **ANALYTICS:** query-ready views supporting the five research questions.
5. **APPLICATION:** Streamlit in Snowflake, using the active Snowpark session instead of a local PostgreSQL connection.

The complete Static feed remains in one raw table. The warehouse Static fact is a view over that table with the session map attached, avoiding an unnecessary second physical copy of the 175-million-row dataset. Only compact analytical aggregates are materialized for dashboard responsiveness.

The Snowflake virtual warehouse is configured as X-Small with auto-resume and 60-second auto-suspend to limit trial-credit consumption.

## 4. Analytical questions

| Research question | Measures and visual analysis |
|---|---|
| Q1. When does charging demand occur? | Session starts by local weekday and hour; normalized weekday-versus-weekend session and energy averages per calendar day |
| Q2. How does recorded EVSE usage differ? | Session count, total delivered energy, average energy per session and connection duration by station |
| Q3. How long do vehicles remain connected? | API connection duration, plus elapsed time from the last Static sample where charging current is positive to API disconnect |
| Q4. How does delivered energy compare with user requests? | Latest userInputs request per session compared with kWhDelivered; coverage of sessions with a valid positive kWh request |
| Q5. How do Power observations vary over time? | Power sample coverage, EVSE-by-month observation heatmap, hourly station-hour Power distribution and number of EVSEs with observations |

Missing Static observations remain missing. They are not treated as zero kW or as proof that an EVSE was unavailable. A sum of station-hour averages is not presented as synchronized facility demand because different EVSE samples are not guaranteed to be simultaneous.

## 5. Verified local findings used to scope the cloud migration

The local JPL processing completed the following before the Snowflake migration:

- 33,638 API sessions after snapshot refresh.
- 175,390,901 cleaned Static measurement rows.
- 14,427,675 Static rows in the July–November 2020 Power analysis window.
- 50 station IDs with at least one observation during that window.
- 100% row-level Power availability among the Static rows present in the selected period.

The period July–November 2020 was selected for the Power comparison because the historical Static archive does not retain Power uniformly in earlier records. The local temporal audit found 18,218 observed EVSE-hour buckets and was designed to compare them with a complete 3,673-hour UTC calendar.

These local results are source-side validation figures; they are not evidence that the same rows have already been loaded into Snowflake.

## 6. Implementation in the repository

The Snowflake deployment package includes:

- SQL bootstrap for database, schemas, X-Small warehouse, CSV file format and internal stage.
- RAW staging table definitions for all source files.
- Snowflake warehouse model and full-Static view.
- Power marts for last-positive-current timing, station-hour observations, station-month coverage and complete site-hour calendar.
- SQL validation queries for row counts and Q1–Q5.
- A Python uploader that transfers existing local CSV/CSV.GZ files directly to the Snowflake internal stage using PUT, then loads them through COPY INTO.
- A Streamlit in Snowflake dashboard that queries Snowflake through the active Snowpark session.

## 7. Account-side deployment status

**Pending execution in the Snowflake account:** uploading the source files, running RAW COPY INTO, creating the warehouse objects, building Power marts and publishing the Streamlit app.

After deployment, insert evidence from:
- RAW row counts for sessions, userInputs, Static measurements and mapping.
- MART.V_LOAD_RECONCILIATION.
- Q5 POWER_SITE_HOUR row count and observation-presence counts.
- Screenshots of the Q1–Q5 Streamlit dashboard.
- Snowflake query history and trial credit balance.

The account screenshot supplied during implementation showed a Snowflake trial with 398 of 400 credits remaining and 13 days left at that time. This is a point-in-time account snapshot and must be refreshed before submission. Snowflake trial usage consumes credits for compute and storage; the trial expires after 30 days or when free usage is depleted, whichever comes first. A suspended trial cannot run warehouses, load data or execute queries until reactivated/upgraded.

## 8. Conclusion

The Snowflake migration package establishes a cloud-first target architecture that consolidates storage, ETL, analytical warehouse and dashboard serving in one platform. It is designed to remove the laptop's local compute and storage bottleneck, preserve the genuine multi-source ACN-Data dataset, and retain the analytical logic for the five research questions.

The migration should be considered technically complete only after the full data load, row-count reconciliation, Power mart generation and dashboard validation succeed in the user's Snowflake account.
