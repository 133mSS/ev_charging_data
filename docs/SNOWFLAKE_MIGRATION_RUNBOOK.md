# Snowflake migration runbook — JPL EV Charging Analytics

## 1. Objective

This branch contains a Snowflake-first deployment path for the JPL project. Snowflake is intended to host raw landing tables, the warehouse, analytical marts, and the Streamlit dashboard. GitHub remains the source-code repository.

The migration preserves the existing cleaned outputs produced by the JPL pipeline. It does not regenerate synthetic data, replace the ACN-Data source, or delete the original PostgreSQL implementation.

## 2. Source data used

The project has two genuine ACN-Data JPL feeds:

1. **ACN-Data API session endpoint** — charging sessions and userInputs.
2. **ACN-Data Static time-series archive** — electrical samples including current, pilot, voltage, charging state, cumulative energy and Power.

The local audit previously completed:

- 33,638 API session records after refresh.
- 27,723 compressed Static source files in the JPL inventory.
- 175,390,901 cleaned Static measurement rows.
- 14,427,675 Static rows in the July–November 2020 Power analysis window.
- 50 station IDs with at least one Static observation in that window.
- 32 stations with observations in all five months; 18 more were observed in one to four months; two historical IDs had no observation in the window.

Static files are per-session traces, not continuous 24/7 EVSE telemetry. Missing station-hours are not device outages. Do not replace missing Power with zero.

## 3. Snowflake architecture

| Layer | Snowflake object | Purpose |
|---|---|---|
| Storage | RAW.JPL_RAW_STAGE | Internal landing stage for cleaned CSV/CSV.GZ files |
| Raw | RAW.STG_CHARGING_SESSIONS | API session metadata |
| Raw | RAW.STG_USER_INPUTS | User request history |
| Raw | RAW.STG_STATIC_MEASUREMENTS | Full Static measurement archive |
| Raw | RAW.STG_SESSION_MAPPING | MATCHED / API_ONLY / STATIC_ONLY relationship |
| Warehouse | WAREHOUSE.DIM_* | Station, user, date and time dimensions |
| Warehouse | WAREHOUSE.FACT_CHARGING_SESSIONS | One row per API charging session |
| Warehouse | WAREHOUSE.FACT_USER_REQUESTS | One row per user-input update |
| Warehouse | WAREHOUSE.FACT_STATIC_MEASUREMENTS | View over all Static rows, including STATIC_ONLY |
| Mart | MART.SESSION_POST_CURRENT | Last positive-current sample to API disconnect interval |
| Mart | MART.POWER_STATION_HOUR | EVSE × UTC-hour sample summary |
| Mart | MART.POWER_STATION_MONTH | EVSE × local-month observation coverage |
| Mart | MART.POWER_SITE_HOUR | Complete 3,673-hour UTC calendar grid |
| Mart | MART.POWER_HOUR_OF_DAY_PROFILE | Distribution of station-hour Power by local hour |
| App | ANALYTICS.JPL_EV_CHARGING_DASHBOARD | Streamlit Q1–Q5 application |

The full 175M-row Static feed remains in one raw table. The warehouse Static fact is a view that joins session mapping; it does not materialize a second full copy. Only the smaller analytical aggregates are materialized for dashboard responsiveness.

## 4. Trial-credit protection

The screenshot supplied by the project owner showed a Snowflake trial with 400 credits initially and 398 credits remaining at the time of the screenshot. This is a time-sensitive account snapshot, not a guarantee of current balance.

The bootstrap creates JPL_ETL_WH as X-Small with AUTO_SUSPEND=60 and AUTO_RESUME=TRUE. Do not resize to Medium/Large or leave a warehouse running continuously for this project.

Snowflake trial accounts run for 30 days or until free usage is exhausted, whichever comes first. At trial end the account is suspended and warehouses, loading and queries cannot run until the account is upgraded/reactivated. Storage also consumes free usage. Check the current Snowsight credit tile before running the full Static load.

## 5. Files added

- snowflake/00_bootstrap.sql — database, schemas, X-Small warehouse, CSV file format and internal stage.
- snowflake/01_raw_staging.sql — typed raw landing tables and load audit.
- snowflake/02_warehouse.sql — dimensions, API facts, user-request facts and full-Static view.
- snowflake/03_power_marts.sql — last-positive-current mart and Q5 station-hour/month/site-hour aggregates.
- snowflake/04_validation.sql — data reconciliation and Q1–Q5 validation queries.
- snowflake/streamlit_app.py — Snowflake-native Streamlit dashboard.
- snowflake/environment.yml — dashboard runtime dependencies.
- scripts/deploy_snowflake.py — local client that uploads existing processed files with PUT, loads them with COPY INTO, creates warehouse objects and publishes Streamlit.
- requirements-snowflake.txt — optional local Snowflake Python connector dependency.

## 6. Credentials

Copy values from .env.snowflake.example into the local .env. Do not commit the real .env.

Required for password authentication:
- SNOWFLAKE_ACCOUNT
- SNOWFLAKE_USER
- SNOWFLAKE_PASSWORD

Optional:
- SNOWFLAKE_ROLE
- SNOWFLAKE_WAREHOUSE (defaults to JPL_ETL_WH)
- SNOWFLAKE_AUTHENTICATOR (use OAUTH_AUTHORIZATION_CODE for managed Google OIDC sign-in; use externalbrowser for SAML 2.0 SSO. In either browser-based SSO mode, SNOWFLAKE_PASSWORD is not required)

The account identifier must be copied from Snowsight > account selector > View account details, not copied as the full browser URL. For an organization/account-name account, the connector value is organization-account_name; a legacy account locator is also supported. Do not include https://, a URL path, or .snowflakecomputing.com in SNOWFLAKE_ACCOUNT.

For `OAUTH_AUTHORIZATION_CODE`, the deployment code intentionally does not pass `SNOWFLAKE_USER`; Snowflake derives the identity from the browser-authorized access token. This avoids error 390309 when a cached/browser identity differs from a separately configured username. The read-only connection test prints `CURRENT_USER()` so you can confirm which Snowflake user was authenticated. The deployment script loads the repository-root .env with precedence over stale inherited Windows environment variables. Use the exact Snowflake login username, not an assumed display name. If you click the managed Sign in with Google option (OIDC), set SNOWFLAKE_AUTHENTICATOR=OAUTH_AUTHORIZATION_CODE; the connector opens the browser authorization flow. If the account instead uses Google Workspace as a SAML identity provider, set SNOWFLAKE_AUTHENTICATOR=externalbrowser. The two protocols are not interchangeable.

Use a role with privileges to create databases, schemas, warehouses, stages, tables, views and Streamlit apps. Do not share credentials in screenshots or logs.

## 7. Deployment from Windows

First check available free space and make sure the current processed files already exist. The deploy script uploads the existing compressed files; it does not create another local copy.

The local deployment wrapper creates its own Python virtual environment under %LOCALAPPDATA% (normally on C:) and routes temporary files there, avoiding the nearly-full D: project drive. It installs Snowflake Connector 5.2+, which supports the Python 3.15 interpreter shown in the development environment.

Before deployment, test authentication without modifying Snowflake objects:

~~~powershell
$py = "$env:LOCALAPPDATA\\JPL-Snowflake-Client\\venv\\Scripts\\python.exe"
& $py .\\scripts\\test_snowflake_connection.py
~~~

A successful check prints the current Snowflake user, role, account and region. It does not create a database or warehouse. For managed Google OIDC sign-in, set `SNOWFLAKE_AUTHENTICATOR=OAUTH_AUTHORIZATION_CODE` in the project-root `.env`; for SAML Google Workspace use `externalbrowser`. OIDC and SAML are different protocols.

For a low-risk first pass, deploy the database objects and API session inputs without the 175M-row Static load:

~~~powershell
.\scripts\run_snowflake_deploy.ps1
~~~

This loads API sessions, userInputs and the session mapping, then creates the core warehouse and the Streamlit app. Q1–Q4 can be checked; Q5 requires the Static load and Power marts.

After checking the Snowsight credit balance, load the full Static source and build Power marts:

~~~powershell
.\scripts\run_snowflake_deploy.ps1 -IncludeStatic -SkipCoreLoad
~~~

The Static file is uploaded directly from its existing local path to the Snowflake internal stage; AUTO_COMPRESS=FALSE avoids creating an extra compressed copy. If the compressed file is larger than 250 MiB, the loader prints a performance warning. Snowflake PUT can upload larger files in chunks, but COPY throughput is generally better with multiple 100–250 MiB compressed files. The current loader proceeds with the existing file and does not create local split copies.

The second command uses --skip-core-load so it does not truncate/reload the API sessions, userInputs or mapping tables from the first run. The command performs:
1. Bootstrap database and warehouse (idempotent).
2. Preserve API sessions, userInputs and session mapping from the first run.
3. Upload + COPY full Static measurements.
4. Rebuild dimensions/facts/views and Power marts.
6. Create dimensions/facts/views.
7. Optional heavy Power mart build.
8. Run validation queries.
9. Upload Streamlit source and publish the live app.

Re-running reloads the RAW staging tables before COPY. It is a full refresh of these JPL RAW inputs; it does not delete local files or the old PostgreSQL database.

## 8. Manual Snowsight alternative

If the local Snowflake Python connector cannot be installed, execute the SQL files in order from Snowsight Worksheets:

1. snowflake/00_bootstrap.sql
2. snowflake/01_raw_staging.sql
3. Upload CSV/CSV.GZ files to @JPL_ANALYTICS.RAW.JPL_RAW_STAGE using Snowsight's Upload Local Files or the Snowflake CLI.
4. Run appropriate COPY INTO commands for each RAW table.
5. snowflake/02_warehouse.sql
6. snowflake/03_power_marts.sql
7. snowflake/04_validation.sql

For dashboard deployment, upload snowflake/streamlit_app.py and snowflake/environment.yml to @JPL_ANALYTICS.RAW.JPL_RAW_STAGE/app, then run:

~~~sql
CREATE OR REPLACE STREAMLIT JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD
  FROM '@JPL_ANALYTICS.RAW.JPL_RAW_STAGE/app'
  MAIN_FILE = 'streamlit_app.py'
  QUERY_WAREHOUSE = JPL_ETL_WH;

ALTER STREAMLIT JPL_ANALYTICS.ANALYTICS.JPL_EV_CHARGING_DASHBOARD
  ADD LIVE VERSION FROM LAST;
~~~

## 9. Q1–Q5 coverage

| Question | Snowflake analysis |
|---|---|
| Q1 — Charging demand by time | Local weekday × start hour heatmap and normalized weekday/weekend averages per calendar day |
| Q2 — EVSE usage differences | Session counts, total kWh, mean kWh/session and connection duration by station |
| Q3 — Connection duration and retained connection after charging | API connection duration plus Static last sample with Charging Current > 0, joined to API disconnect time |
| Q4 — Requested versus delivered energy | Latest userInputs row per session selected first, then valid positive kWh requests compared with session kWhDelivered |
| Q5 — Power and temporal coverage | Full Static EVSE-hour Power summaries, EVSE-month coverage and complete UTC site-hour grid |

Q3 uses actual Static charging_current_a > 0 timestamps for the last-positive-current measure. It does not substitute the API doneChargingTime field for that measured timestamp.

Q4 uses the latest request event before filtering invalid/missing kwh_requested, avoiding accidental fallback to an older input event.

## 10. Required validation and report evidence

Do not state that Snowflake data migration is complete until these have been executed successfully in the user's account.

Capture:
1. Snowsight trial credit tile before and after the migration (do not expose account identifiers).
2. SHOW TABLES IN SCHEMA JPL_ANALYTICS.RAW and RAW row counts.
3. MART.V_LOAD_RECONCILIATION with API, userInput and full Static counts.
4. MART.POWER_SITE_HOUR count = 3,673 and hours-with/without-observation counts.
5. Q1–Q5 dashboard screenshot with populated metrics.
6. Snowflake query history showing the load and mart build completed.
7. The current Snowflake trial balance and expiry date before final submission.

Do not claim Snowflake-hosted ETL, warehouse or dashboard has run until the user's Snowsight account shows these outputs. The repository implementation is prepared; the account-side deployment and data load are the remaining execution steps.
