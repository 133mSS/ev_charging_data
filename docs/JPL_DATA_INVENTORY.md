# JPL Source Inventory – ACN-Data Static

**Inventory reference:** repository `tongxin-li/ACN-Data-Static`, branch `main`, folder `time series data/jpl/Arroyo_Garage_01`, Git tree snapshot queried on 2026-11-10.

## Verified Static snapshot

| Metric | Result |
|---|---:|
| CSV.GZ time-series files | **27,723** |
| Unique station IDs extracted from filenames | **52** |
| First session date in filenames | **2018-10-08** |
| Last session date in filenames | **2020-12-02** |
| Total compressed object size | **616,187,585 bytes (~587.6 MiB)** |
| Months containing files | **27** |

### File counts by year

| Year | Static files |
|---|---:|
| 2018 (from October) | 3,504 |
| 2019 | 17,129 |
| 2020 (through December 2) | 7,090 |
| **Total** | **27,723** |

### Monthly file counts

| Month | Files | Month | Files | Month | Files |
|---|---:|---|---:|---|---:|
| 2018-10 | 1,171 | 2019-07 | 1,485 | 2020-04 | 41 |
| 2018-11 | 1,279 | 2019-08 | 1,511 | 2020-05 | 251 |
| 2018-12 | 1,054 | 2019-09 | 1,419 | 2020-06 | 374 |
| 2019-01 | 1,364 | 2019-10 | 1,671 | 2020-07 | 506 |
| 2019-02 | 1,286 | 2019-11 | 1,348 | 2020-08 | 566 |
| 2019-03 | 1,399 | 2019-12 | 1,097 | 2020-09 | 451 |
| 2019-04 | 1,518 | 2020-01 | 1,474 | 2020-10 | 666 |
| 2019-05 | 1,645 | 2020-02 | 1,408 | 2020-11 | 473 |
| 2019-06 | 1,386 | 2020-03 | 835 | 2020-12 (through 2nd) | 45 |

## Important interpretation rules

- File count is a count of time-series files (one file per static session in this repository snapshot). It is not an API session count and should not be represented as the total number of JPL API sessions.
- The 52 station IDs are distinct historical identifiers visible in filenames. ACN-Data's site page currently describes JPL as having 50 EVSEs. Different snapshots/time ranges can contain equipment identifiers that changed over time. Do not force the Static count to equal 50.
- 2020 monthly file counts fall sharply after March. This is a visible property of this snapshot, but the reason must not be attributed to COVID-19 or another cause without independent evidence.
- This Static inventory says nothing by itself about whether each minute has complete measurements across all EVSEs. Coverage must be calculated after reading the time-series data.

## API status

API exact session count has **not yet been queried** in this environment because the uploaded project intentionally does not contain an ACN API token. Run `python run_pipeline.py --stage extract` with `ACN_API_TOKEN` set in `.env`, then `python scripts/audit_jpl_api_snapshot.py`. This is deliberately left as pending rather than inferred from the Static file count.

## Source links

- Static repository: https://github.com/tongxin-li/ACN-Data-Static
- Official dataset page: https://ev.caltech.edu/dataset.html
