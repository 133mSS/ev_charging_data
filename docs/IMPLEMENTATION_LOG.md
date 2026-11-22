# Implementation log – JPL migration

## 2026-11-10 – Stage 01

- Set the project scope to ACN-Data site `jpl` / `Arroyo_Garage_01`.
- Centralized site paths and ID in `project_config.py`.
- Replaced the Office API/static extraction and cleaning steps with JPL-aware scripts.
- Routed cleaned/matched outputs to `data/processed/jpl/`.
- Removed exact Office-specific assertions (7,303,648 measurements and 1,300 sessions) from static loaders; replaced them with integrity checks based on actual JPL counts.
- Isolated the JPL PostgreSQL container, port 5436 and volume from the former Office setup.
- Added Git sparse-checkout helper, Static tree inventory tool, and API snapshot audit tool. Static files are read directly from the sparse checkout to avoid a second copy.
- No raw JPL CSV.GZ measurement data or API JSON are bundled. JPL Static is ~587.8 MiB compressed and the API requires the user's private access token; fetch them locally before running transform/load.

- Added JPL demand heatmap SQL and Plotly visualization (weekday × local hour); visual output remains pending the actual JPL API/Static load.


## 2026-11-20 – Final project hardening

- Consolidated README, implementation status, Snowflake runbook and migration report with the completed 18-November account-side deployment results.
- Clarified session-level API/Static matching counts versus measurement-row counts.
- Standardized Q3 wording around the last positive-current sample and API disconnect; avoided treating it as an exact charge-completion timestamp.
- Added Q4 request coverage using valid latest requests divided by sessions in the selected period; full-snapshot coverage is 31,444 / 33,638 = 93.48%.
- Restricted Q5 visuals to the Power analysis window (July–November 2020), displayed 2,240 / 3,673 site-hour observation coverage, and used a fixed 50-station population in the EVSE × month heatmap.
- Updated monthly validation SQL to include unobserved station-month combinations at 0% calendar-hour coverage.
- Moved dashboard SQL into snowflake/analytics_queries.py and added Vietnamese weekday labels and a complete 7-day × 24-hour Q1 grid.
- Added snowflake/05_data_quality.sql and automated regression checks for keys, mapping, row reconciliation, dimension references, Q3 interval validity, and the complete UTC site-hour calendar.
- Extended LOAD_AUDIT lineage with RUN_ID, file size, source SHA-256 and COPY query ID; added an app-only deployment option to avoid reloading Static or rebuilding marts during UI updates.
- Added GitHub Actions branch matching for chore/**. The hardening branch is tested separately from the already-published baseline; final CI result is recorded in the pull request.
## 2026-11-22 – User ID conformance and fact-grain safeguards

- Audited 522 distinct user IDs in the session and userInputs payloads. All 522 match after canonicalizing leading zeroes; all 41,207 request rows match their session user after normalization.
- Preserved source `USER_ID` values and added a canonical `USER_ID_KEY` to `DIM_USER`, `FACT_CHARGING_SESSIONS` and `FACT_USER_REQUESTS`.
- Added an incremental `snowflake/06_user_id_key_migration.sql` path for existing Snowflake accounts. It updates only the three small user/session tables and does not reload RAW, Static measurements or Power marts.
- Added data-quality checks for duplicate/missing/orphan user keys, request-to-session integrity, normalized user-set reconciliation and Q4 one-row-per-session behavior.
- Kept Q4's latest-request selection before the Session Fact join to prevent request-detail fanout from duplicating session energy. Added explicit duplicate-session reporting to the Q4 validation query.
