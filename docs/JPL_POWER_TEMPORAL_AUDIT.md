# JPL Power Analysis: temporal coverage and scope

## Purpose

The full cleaned Static dataset contains 175,390,901 measurement rows. Power and Voltage are not available uniformly across the complete historical period. This workflow identifies EVSE candidates for a defensible Power Load Profile without forcing Static measurements to have an API session match.

## Agreed analysis windows

- Full Static history: used for historical coverage and provenance.
- API sessions: 2018-09 to 2021-09 in the current refreshed API snapshot.
- Power profile candidate window: July-November 2020.
- Timezone: America/Los_Angeles.

The July-November window was chosen because the full-Static row-level audit showed high Power coverage in these months. June 2020 is a transition month; December 2020 is partial because the Static archive ends on December 2.

## Candidate EVSE selection

Run:

\`\`\`powershell
python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 99
\`\`\`

An EVSE is eligible only when it:
1. Has Static observations in all five calendar months.
2. Has at least one non-null Power value in every month.
3. Meets the configured minimum row-level Power coverage in every month (default 99%).

This is a screening rule. It does not establish continuous EVSE uptime, nor does it imply that all 32 selected station IDs represent 32 EVSEs installed simultaneously.

The prior first-pass result found 32 candidates when the rule required observations and Power presence in each month. The stricter 99% monthly rule may select fewer; that is intentional and must be reported from the new run.

## Temporal audit

Run:

\`\`\`powershell
python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11
\`\`\`

The audit reads the full cleaned Static file in chunks and filters to the candidate EVSEs. It does not read the API-matched-only file.

### Output files

| File | Grain | Use |
|---|---|---|
| \`jpl_station_hourly_temporal_coverage.csv\` | EVSE × absolute UTC hour | Observed sample density, Power/Voltage presence, average observed power |
| \`jpl_station_month_temporal_coverage.csv\` | EVSE × local month | Calendar-hour observation coverage, hours with Power, row coverage |
| \`jpl_station_hour_of_day_profile.csv\` | EVSE × local hour-of-day | Compare observed hourly power patterns by clock hour |
| \`jpl_site_hourly_observed_load.csv\` | Absolute UTC hour | Sum of mean Power across EVSEs with Power observations and station coverage |
| \`jpl_temporal_coverage_summary.json\` | Run | Scope, row counts, coverage and output manifest |

## Metric definitions and interpretation

- **Calendar-hour observation coverage** = distinct local calendar hours with at least one Static measurement / actual elapsed hours in the local month. This is an observation-presence statistic, not EVSE uptime.
- **Power hour presence** = observed calendar hours containing at least one non-null Power sample / calendar hours with any Static sample.
- **Power row coverage** = non-null Power samples / all Static rows in the relevant group.
- **Observed hourly Power** = mean of non-null Power samples within that EVSE and absolute UTC-hour bucket.
- **Observed site Power sum** = sum of the per-EVSE hourly means for EVSEs with Power observations in that UTC hour. EVSEs with no Power observation are excluded, not zero-filled.
- **Positive Power share** = samples with Power > 0 / samples with non-null Power. A present Power value of 0 is a valid zero reading; it is not missing.
- UTC hour keys are retained to distinguish the repeated local 01:00 hour when daylight saving time ends.

Do not describe \`observed_power_sum_kw\` as total JPL facility demand unless coverage across the full relevant infrastructure is demonstrated. Label it as observed Power across the selected EVSEs and show station coverage next to the curve.

## Important modeling decision for the Warehouse

The current \`warehouse.fact_static_measurements\` load is based on \`jpl_static_measurements_matched.csv.gz\` and requires an API session foreign key. This table is suitable for API/Static reconciliation, but it excludes \`STATIC_ONLY\` measurements.

Therefore:
- Keep the matched fact for reconciliation and session-level energy QA.
- Build Power analytics from the full cleaned Static dataset and the selected EVSE scope.
- Load compact hourly aggregates into a separate aggregate fact table in a later implementation step.
- Do not use the matched-only fact as the sole source for Power Load Profile.

## COVID-19 context

July-November 2020 falls during the COVID-19 period. Interpret observed charging patterns as behavior in this specific period, not as a general description of normal JPL employee schedules without additional comparison data.
