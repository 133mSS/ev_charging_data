# JPL Power Analysis: temporal coverage and scope

## Purpose

This workflow audits Power measurements in the complete cleaned ACN-Data Static dataset. It does not require a measurement to be matched to an API session. API–Static matching is handled as a separate audit.

Static CSV.GZ files are per-session time-series traces, not continuous telemetry for every EVSE. A calendar hour without a Static sample is an hour without an observed session measurement, not proof of EVSE downtime.

## Analysis window

The full Static snapshot spans 2018-10-08 to 2020-12-02. Due to a source data-retention issue, the electrical fields other than Charging Current were not retained uniformly before 2020-06-17. The full-Static row audit found 40.44% Power coverage for June 2020 and 100% among available rows in July–November 2020. December is partial because the archive ends on December 2.

Use July–November 2020 for Power-profile comparisons. Other API session-history analyses can use the broader API history.

Timezone: America/Los_Angeles. Hourly keys are absolute UTC hours to preserve the repeated local hour at the daylight-saving fall-back.

## EVSE population

In the user's local snapshot:

- 52 historical station IDs occur in the Static archive.
- 50 have at least one observation in July–November 2020.
- 32 have observations in all five months; use these as the balanced comparison cohort.
- 18 have observations in one to four months; retain them for descriptive analysis in months where data exists.
- 2 have no observation in the selected window.

Missing station-month observations must not be interpreted as an inactive or faulty EVSE. The selector reports missing observation months explicitly. The legacy active_months field is a compatibility alias for months with records, not device uptime.

## Reproducible commands

Full-Static audit on all observed stations:

~~~powershell
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --all-stations --chunksize 500000
~~~

Balanced 32-station comparison cohort:

~~~powershell
python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 99
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11 --chunksize 500000
~~~

API–Static alignment:

~~~powershell
python scripts/audit_jpl_api_static_hourly_alignment.py --start-month 2020-07 --end-month 2020-11 --chunksize 500000
~~~

Power dashboard:

~~~powershell
streamlit run dashboard/power_analytics.py
~~~

One-command runner:

~~~powershell
.\scripts\run_jpl_power_analytics.ps1
~~~

## Output files

### Full-Static temporal audit: data/analytics/jpl_power_temporal/

| File | Grain | Use |
|---|---|---|
| jpl_station_hourly_temporal_coverage.csv | EVSE × absolute UTC hour with measurements | Sample density, hourly mean Power and sensor presence |
| jpl_station_month_temporal_coverage.csv | EVSE × local month | Calendar-hour observation presence and row-level sensor coverage |
| jpl_station_hour_of_day_profile.csv | EVSE × local hour-of-day | Compare observed station-hour Power patterns |
| jpl_site_hourly_observed_load.csv | Every elapsed absolute UTC hour, including empty hours | Number of EVSEs with samples/Power and coverage denominator |
| jpl_temporal_coverage_summary.json | Run | Scope, counts, coverage and output manifest |

The site-hour file contains the complete UTC-hour grid. For July–November 2020 the expected grid has 3,673 hours: July 744, August 744, September 720, October 744, and November 721. Hours without any observation have zero station counts and null measured Power.

### API–Static alignment: data/analytics/jpl_api_static_alignment/

| File | Grain | Use |
|---|---|---|
| jpl_api_static_station_hour_alignment.csv | EVSE × absolute UTC hour | API session interval overlap, matched/API-only sessions, Static matched/Static-only sessions and sample metrics |
| jpl_api_static_alignment_summary.json | Run | Counts and interpretation warning |

## Metric definitions

- **Power row coverage** = non-null Power samples / all Static measurement rows.
- **Calendar-hour observation coverage** = station-local calendar hours with at least one Static sample / elapsed hours in the local month. This is not EVSE uptime.
- **Power hour presence** = observed calendar hours with at least one non-null Power sample / calendar hours with any Static sample.
- **Observed station-hour Power** = mean of non-null Power samples within one EVSE and one absolute UTC-hour bucket.
- **Stations with Power per site-hour** = distinct EVSEs with at least one non-null Power sample in that UTC hour.
- **Site-hour observation presence** = hours with at least one in-scope Static sample / all elapsed UTC hours in the selected window.
- **API session minutes sum** = sum of API-session overlap minutes in a station-hour. Overlapping sessions can cause this to exceed unique occupied wall-clock minutes.

## Important interpretation constraints

- Missing Power must remain null; never fill it with 0 kW.
- A 100% row-level Power coverage means available Static rows contain Power. It does not mean every minute/hour has been observed.
- Do not interpret missing station-hours as device downtime.
- The temporal audit writes sum_station_hour_mean_power_kw as a descriptive sum of station-hour sample means. Samples from different EVSEs are not guaranteed to be simultaneous. Do not label this as total JPL facility demand.
- A synchronized facility-load estimate would require timestamp-level alignment across EVSEs with an explicit sampling window and coverage rule. The current project does not claim that this has been established.
- API–Static alignment is a correspondence audit; it does not prove that every API session has a complete Static trace.

## Warehouse design

warehouse.fact_static_measurements currently contains matched Static measurements only because the fact requires an API session foreign key. Keep it for session reconciliation and energy quality analysis.

The full-Static Power dashboard reads the generated CSV analytics directly so STATIC_ONLY measurements are retained in descriptive analysis. Do not use the matched-only warehouse fact as the sole source for the full-Static Power profile.

For the final result summary, evidence checklist, and implementation status, see docs/JPL_POWER_ANALYTICS_FINAL.md and docs/IMPLEMENTATION_STATUS_STAGE02.md.
