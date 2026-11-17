# JPL Migration – Stage 02 progress

## Completed from local execution results

- API snapshot refreshed to 33,638 unique session IDs; the live API total was 33,638 at the time of refresh.
- Static repository inventory: 27,723 CSV.GZ files, 52 historical filename station IDs, 2018-10-08 to 2020-12-02.
- Full Static transformation: 175,390,901 measurement rows.
- Initial API–Static mapping after API refresh: 25,647 MATCHED, 1,978 STATIC_ONLY, 7,991 API_ONLY.
- Full-Static sensor audit: 175,390,901 rows; current values non-null across the retained rows; row-level Power coverage about 8.81% over the full historical snapshot.
- Power coverage in the full Static snapshot was concentrated in June–December 2020; July–November 2020 had 100% row-level Power presence in the reported monthly aggregate.
- First-pass scope selection identified 32 station IDs with observations and Power present in all five months July–November 2020.
- The first-pass scope is a candidate set only; it has not yet passed the new calendar-hour temporal coverage audit.

## Added in this implementation branch

- scripts/select_jpl_power_analysis_scope.py: reproducible station selection, including a configurable minimum Power coverage threshold for each month; writes eligible and excluded stations separately.
- scripts/audit_jpl_temporal_coverage.py: chunked audit from the full cleaned Static file; writes station-hour, station-month, station/hour-of-day and observed site-hour outputs.
- tests/test_jpl_temporal_coverage.py: tests DST-aware month-hour denominators and candidate selection rules.
- docs/JPL_POWER_TEMPORAL_AUDIT.md: metric definitions, limitations and Warehouse design decision.

## Critical Warehouse design decision

The current static fact load consumes jpl_static_measurements_matched.csv.gz and requires an API session foreign key. That is suitable for API/Static reconciliation, but it drops STATIC_ONLY sessions. Power analytics must therefore use the full cleaned Static dataset and then a compact aggregate table built from all selected Static measurements. Do not use the matched-only static fact as the exclusive source for the JPL Power Load Profile.

## Next validation steps on Windows

1. Ensure data/inventory/jpl_sensor_coverage_all_static_by_station_month.csv exists from the full-Static sensor audit.
2. Run python scripts/select_jpl_power_analysis_scope.py --min-monthly-power-coverage 99.
3. Review the eligible and excluded EVSE files. If the 99% monthly threshold is too strict for the descriptive scope, compare against --min-monthly-power-coverage 0 and report the criterion explicitly.
4. Run python scripts/audit_jpl_temporal_coverage.py --start-month 2020-07 --end-month 2020-11.
5. Review jpl_station_month_temporal_coverage.csv and jpl_site_hourly_observed_load.csv. The latter reports observed Power only across stations with data; it does not fill missing station values with zero.
6. Only after temporal coverage is reviewed should the project add the compact PostgreSQL Power aggregate fact and connect it to the dashboard.

## Not yet verified

- Temporal coverage output on the user's full 175.4 million row file.
- Exact final EVSE selection under the 99% per-month threshold.
- Whether the observed minute/hour series is sufficiently continuous for a facility-wide load interpretation.
- PostgreSQL aggregate loading and Streamlit Power dashboard against the final temporal output.
