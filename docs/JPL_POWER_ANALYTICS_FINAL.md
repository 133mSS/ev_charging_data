# JPL Power Analytics – final methodology and runbook

## 1. Purpose and scope

This workflow adds a defensible Power-analysis layer to the JPL EV Charging Analytics project. It uses the complete cleaned ACN-Data Static measurement file, not only Static rows that matched an API session.

The project has two complementary data streams:

- **ACN-Data API:** charging-session metadata and session intervals (connection_time, disconnect_time, station_id, energy_kwh).
- **ACN-Data Static:** per-session electrical samples (timestamp, charging_current_a, voltage_v, power_kw).

Static files are session-scoped measurement traces. They are not a continuous 24/7 telemetry feed for every EVSE. A missing hour therefore means no Static sample was published for that EVSE-hour; it does not by itself prove an EVSE outage.

## 2. Why Power is analyzed in July–November 2020

The full Static inventory spans 2018-10-08 to 2020-12-02. The source data has a known retention limitation: historical records before 2020-06-17 retained Charging Current, while the other electrical fields such as Voltage and Power were not retained under the source system's data-retention policy. June 2020 is a transition month. The full-Static audit measured 40.44% row-level Power coverage for June, while July–November 2020 had 100% row-level Power coverage in the available records. December is only present through December 2.

Consequently, July–November 2020 is the selected window for Power-profile comparisons. It is not the only period used by the overall project: API-based session counts, delivered energy, connection duration, and charging-demand analysis can use the broader API history.

## 3. EVSE population and selection

In the local Static snapshot:

- 52 historical station IDs appear in the archive.
- 50 station IDs have at least one Static observation in July–November 2020.
- 32 station IDs have observations in all five months and satisfy the monthly Power coverage selection threshold.
- 18 additional station IDs have observations in one to four months; in every observed station-month shown in the user's diagnostic, Power row coverage was 100%.
- 2 station IDs have no observation in the five-month Power window.

The 32-station list is a balanced comparison cohort. It is not the only valid analysis population. Use all 50 observed station IDs for descriptive analysis, while preserving missing station-month combinations as missing/zero coverage rather than inventing sensor readings. Retain the 32-station cohort as a sensitivity/comparison subset.

Do not interpret historical station IDs as a count of EVSEs installed simultaneously.

## 4. Coverage definitions

Keep these measures separate:

1. **Power row coverage** = non-null Power samples / all Static measurement rows. The 100% result in July–November describes rows that exist in the archive.
2. **Station-hour observation coverage** = station-hours with at least one Static sample / all elapsed calendar hours in the month. This is not EVSE uptime.
3. **Site-hour observation presence** = elapsed UTC hours with at least one Static sample from any in-scope station / all elapsed UTC hours in the selected window.
4. **Stations with Power per hour** = number of distinct station IDs with at least one non-null Power sample in that UTC hour.
5. **Station-hour mean Power** = mean of non-null Power samples for one EVSE in one UTC-hour bucket.

The site-hour output is a complete UTC-hour grid. It includes hours with no observations, where station counts are zero and measured Power remains null. UTC keys preserve both occurrences of the repeated local clock hour at the end of daylight-saving time.

## 5. Results from the current full-Static run

The user's all-stations run for July–November 2020 reported:

- 175,390,901 Static rows scanned.
- 14,427,675 rows in the selected local-time window.
- 18,218 station-hour buckets.
- 100% row-level Power coverage in the selected records.
- 50 station IDs observed in the selected window.
- Zero UTC hours in which all 50 station IDs had Power.

The user's current station-month summary (50-station denominator) is:

| Month | Stations with observations | Stations without observations | Mean station-hour coverage | Median station-hour coverage | Maximum station-hour coverage |
|---|---:|---:|---:|---:|---:|
| 2020-07 | 37 | 13 | 9.08% | 2.96% | 31.72% |
| 2020-08 | 45 | 5 | 11.43% | 7.19% | 35.22% |
| 2020-09 | 40 | 10 | 8.23% | 4.10% | 32.64% |
| 2020-10 | 46 | 4 | 12.28% | 7.39% | 42.34% |
| 2020-11 | 41 | 9 | 8.49% | 3.33% | 36.62% |

The local calendar window has 3,673 elapsed hours (July 744, August 744, September 720, October 744, November 721). An earlier site-hour export contained only 2,240 hours with at least one observation. The updated temporal audit writes all 3,673 hours, including the 1,433 hours with no observation from any of the 50 stations. Hourly coverage threshold shares must use this complete grid as the denominator.

Before the complete-grid export, the distribution among the 2,240 observed hours ranged from one to 27 EVSEs with Power; 562 observed hours had only one EVSE and only nine observed hours had at least 25 EVSEs. The complete-grid output will include the additional zero-observation hours.

## 6. Interpretation rules

- Do not convert missing Power into 0 kW.
- Do not interpret missing station-hours as an EVSE outage.
- Do not call the sum of per-station hourly means a synchronized facility load. Electrical samples from different EVSEs are not guaranteed to share identical timestamps.
- The temporal script names this descriptive quantity sum_station_hour_mean_power_kw. It is only the sum of station-hour sample means for stations with observations in that hour.
- For a true synchronized aggregate, measurements would need to be aligned on actual timestamps with an explicit sampling-window and sensor-coverage rule. The current project does not claim that such a site-wide load estimate is available.
- The API alignment field api_session_minutes_sum is the sum of session-minutes. It may include overlapping session intervals and is not unique occupied wall-clock time.
- The API–Static alignment is an audit of session/time correspondence, not proof that all API sessions have complete Static traces.

## 7. Reproducible execution

Run these from the repository root in PowerShell after the JPL API and Static transforms have completed.

### A. Full-Static temporal coverage

~~~powershell
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --all-stations --chunksize 500000
~~~

Outputs:

- data/analytics/jpl_power_temporal/jpl_station_hourly_temporal_coverage.csv
- data/analytics/jpl_power_temporal/jpl_station_month_temporal_coverage.csv
- data/analytics/jpl_power_temporal/jpl_station_hour_of_day_profile.csv
- data/analytics/jpl_power_temporal/jpl_site_hourly_observed_load.csv
- data/analytics/jpl_power_temporal/jpl_temporal_coverage_summary.json

The site-hour file now has one row for every elapsed UTC hour in the selected window.

### B. API–Static hourly alignment

~~~powershell
python scripts/audit_jpl_api_static_hourly_alignment.py --start-month 2020-07 --end-month 2020-11 --chunksize 500000
~~~

Outputs:

- data/analytics/jpl_api_static_alignment/jpl_api_static_station_hour_alignment.csv
- data/analytics/jpl_api_static_alignment/jpl_api_static_alignment_summary.json

The script expands API connection intervals into UTC-hour buckets, scans the full cleaned Static dataset, and distinguishes matched API sessions, API-only sessions, matched Static sessions with observations, and Static-only sessions.

### C. Power dashboard

~~~powershell
streamlit run dashboard/power_analytics.py
~~~

This page reads the generated CSV artifacts and does not require the warehouse database. The main application remains available through streamlit run dashboard/app.py.

### D. Tests

~~~powershell
python -m unittest discover -s tests -v
~~~

The unit tests cover daylight-saving month lengths, station selection rules, complete site-hour grids, and API interval splitting.

## 8. Evidence to capture for the report

Capture screenshots of:

1. Console output for the full-Static temporal audit, showing rows scanned, rows in the selected period, 50 observed station IDs, and full UTC-hour coverage summary.
2. jpl_station_month_temporal_coverage.csv or the dashboard EVSE × month coverage heatmap.
3. The dashboard chart of EVSE count with Power per UTC hour.
4. The station-hour Power profile with its station-hour definition and coverage context.
5. API–Static alignment console output and a filtered sample from jpl_api_static_station_hour_alignment.csv.
6. The final unit-test output.

Do not present API–Static alignment results as completed until the alignment script has been run successfully on the local source files.
