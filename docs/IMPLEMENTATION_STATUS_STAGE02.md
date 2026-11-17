# JPL Migration – Stage 02 implementation status

## 1. Verified local data snapshot

The following figures came from the user's local Windows execution and are not synthetic:

- API snapshot: 33,638 unique session IDs after refresh.
- Static repository inventory: 27,723 CSV.GZ files, 52 historical filename station IDs, 2018-10-08 to 2020-12-02.
- Full cleaned Static file: 175,390,901 measurement rows.
- API–Static mapping after refresh: 25,647 MATCHED, 1,978 STATIC_ONLY, 7,991 API_ONLY.
- Full-history row-level Power coverage: about 8.81%; Power/Voltage were not retained uniformly over the complete history.
- July–November 2020 selected-window audit over all Static rows: 14,427,675 rows, 18,218 station-hour buckets, 50 station IDs, and 100% row-level Power coverage among the rows present.
- No UTC hour in that window had Power observations from all 50 station IDs.

## 2. EVSE population decision

The 50 station IDs with at least one observation during July–November 2020 are the descriptive Power population.

- 32 station IDs have observations in all five months and form the balanced month-comparison cohort.
- 18 station IDs have observations in one to four months. The user's per-month diagnostic found 100% Power row coverage in every observed month for these stations.
- 2 station IDs have no observations in the selected five-month window.

Missing station-month observations are not evidence that an EVSE was inactive or faulty. The selector now reports NOT_OBSERVED_IN_ALL_FIVE_MONTHS, includes the missing months, and retains the legacy active_months column only as a compatibility alias. That alias counts months with records; it is not device uptime.

## 3. Temporal coverage findings

The user's current 50-station station-month summary:

| Month | Stations with observations | Mean station-hour observation coverage | Median | Maximum |
|---|---:|---:|---:|---:|
| 2020-07 | 37 | 9.08% | 2.96% | 31.72% |
| 2020-08 | 45 | 11.43% | 7.19% | 35.22% |
| 2020-09 | 40 | 8.23% | 4.10% | 32.64% |
| 2020-10 | 46 | 12.28% | 7.39% | 42.34% |
| 2020-11 | 41 | 8.49% | 3.33% | 36.62% |

These are observation-presence rates, not EVSE uptime. Static files are per-session traces, not continuous 24/7 telemetry.

The earlier site-hour CSV contained only the 2,240 hours with at least one observation. The temporal-audit code has since been updated to write a complete 3,673-UTC-hour grid, including 1,433 hours with no observations from any station. The updated script must be rerun locally to regenerate this corrected output and its summary denominators.

A sum of station-hour mean Power values is not synchronized facility load. The script now names this descriptive statistic sum_station_hour_mean_power_kw and documents the limitation.

## 4. Implemented in this branch

- scripts/select_jpl_power_analysis_scope.py: selects the 32-station balanced cohort and reports missing observation months explicitly.
- scripts/audit_jpl_temporal_coverage.py: chunked audit of the full cleaned Static dataset, plus a complete UTC-hour grid with no-observation hours included.
- scripts/audit_jpl_api_static_hourly_alignment.py: expands API connection intervals into UTC-hour buckets and compares them with full-Static measurements by station and hour. It keeps MATCHED, API_ONLY, STATIC_ONLY and unmapped evidence separate.
- dashboard/power_analytics.py: CSV-driven Streamlit page for full-Static Power and coverage analysis, with optional API–Static alignment displays.
- dashboard/app.py: clarifies that the original warehouse Power section is based on API-matched Static measurements and must not be interpreted as synchronized facility demand.
- scripts/run_jpl_power_analytics.ps1: one-command Windows runner for tests, temporal audit and API–Static alignment.
- tests/test_jpl_temporal_coverage.py and tests/test_jpl_api_static_hourly_alignment.py: unit tests for DST denominators, missing-month selection, complete site-hour grids, and API interval splitting.
- .github/workflows/python-tests.yml: runs unit tests on pushes to this branch and pull requests to main.
- docs/JPL_POWER_ANALYTICS_FINAL.md: final methodology, definitions, result summary, runbook and evidence checklist.

## 5. What is validated and what remains

Validated:
- The user's full-Static temporal audit has completed over all 175,390,901 records.
- The updated unit-test suite passed in GitHub Actions at commit e33515a254cb8f26c389a588b75c44366d373502.
- The selector distinguishes missing observation months from missing Power values.

Must still be executed on the user's local dataset after pulling the latest branch:
1. Rerun the updated full-Static temporal audit so the site-hour CSV includes all 3,673 hours.
2. Run scripts/audit_jpl_api_static_hourly_alignment.py and inspect its output summary and CSV.
3. Launch dashboard/power_analytics.py and verify the charts against local artifacts.
4. Capture the evidence screenshots listed in docs/JPL_POWER_ANALYTICS_FINAL.md.

Not claimed as complete:
- The API–Static hourly alignment has not yet been run against the user's local files.
- The new Power dashboard has not yet been manually verified in the user's Windows environment.
- A PostgreSQL aggregate fact table for full-Static Power has not been added. The current warehouse fact remains matched-only and serves session reconciliation/QA.

## 6. Recommended execution on Windows

From the repository root, after confirming the working tree is safe to update:

~~~powershell
git status --short
git pull origin feature/jpl-temporal-power-audit
~~~

Then:

~~~powershell
.\scripts\run_jpl_power_analytics.ps1
~~~

For a lower-memory run:

~~~powershell
.\scripts\run_jpl_power_analytics.ps1 -ChunkSize 250000
~~~

To launch the Power dashboard automatically after the two audit scripts:

~~~powershell
.\scripts\run_jpl_power_analytics.ps1 -LaunchDashboard
~~~
