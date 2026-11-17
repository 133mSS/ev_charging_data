# JPL Migration – Implementation Status (Stage 01)

**Date:** 2026-11-10  
**Scope:** move the EV Charging Analytics project from `office001` to ACN-Data `jpl` / `Arroyo_Garage_01`.

## Completed in this package

- Centralized all paths and the site scope in `project_config.py`; the project rejects a non-JPL `ACN_SITE_ID` to prevent accidental cross-site mixing.
- Replaced the Office Static extractor/cleaner with JPL-specific ingestion and cleaning scripts.
- Added sparse-checkout instructions for only `time series data/jpl/Arroyo_Garage_01`.
- Added a reproducible Static inventory audit and a local environment/source preflight.
- Reworked API pagination to follow the API-provided `next` link, detect repeated links, preserve prior successful snapshots during interrupted downloads, and show actionable 401/403 messages.
- Changed the API audit to verify that one payload `siteID` is present without assuming it must equal the endpoint alias `jpl`.
- Made optional ACN `userInputs` attributes nullable in staging/warehouse schemas; records without `modifiedAt` are not inserted into date/time-keyed request facts.
- Made static-cleaning output atomic so an interrupted processing run does not replace the previous clean file with a partial result.
- Corrected date-dimension generation to use `America/Los_Angeles`, consistent with session and measurement fact keys.
- Kept the JPL PostgreSQL service isolated on port `5436`, with its own database and volume.
- Added a JPL demand heatmap query and a dashboard focused on demand patterns, station ranking, connection behavior, observed power/coverage, and requested-versus-delivered energy.
- Added seven unit tests for JPL filename parsing, session-key normalization, data transformations, and quality thresholds.

## Verified source inventory

The public ACN-Data Static repository README lists **27,723** JPL CSV.GZ time-series files under `time series data/jpl/Arroyo_Garage_01`, covering 2018–2020. A repository metadata inventory prepared for this project reports:

- 27,723 JPL time-series files
- 52 unique station identifiers in historical filenames
- Date range in filenames: 2018-10-08 to 2020-12-02
- Total compressed object size: 616,187,585 bytes (~587.6 MiB)

The 52 filename IDs represent historical identifiers in this snapshot. They are **not** a claim that 52 EVSEs were installed simultaneously. The ACN-Data site page currently describes JPL as having 50 EVSEs.

The API session count and API–Static matching rate remain **unverified** until the user's API token is configured and the live JPL endpoint is extracted. Do not infer the API session count from the Static file count.

## Verification performed in this environment

- `python -m compileall -q .` — passed.
- `python -m unittest discover -s tests -v` — 7 tests passed.
- The supplied monthly and station inventory CSV files sum to 27,723 records each and agree with the inventory summary — passed.
- Full ETL / database / Streamlit runtime was not executed here because this workspace does not contain the 27,723 raw Static files or the user's private ACN-Data API token, and Docker/PostgreSQL/Streamlit are not available in this execution environment.

## Required next steps on the user's Windows machine

1. Extract this ZIP and open PowerShell in the project root.
2. Create `.env` from `.env.example` and set `ACN_API_TOKEN` locally. Do not send the token in chat or commit `.env` to Git.
3. Run `scripts/clone_jpl_static_repo.ps1` to sparse-checkout the public JPL Static folder.
4. Run `python scripts/preflight_jpl.py` and `python scripts/audit_jpl_static_inventory.py`.
5. Run `python -m unittest discover -s tests -v`.
6. Run `python run_pipeline.py --stage extract`, then `python scripts/audit_jpl_api_snapshot.py`.
7. Run `python run_pipeline.py --stage transform`; review the API_ONLY / STATIC_ONLY / MATCHED counts and sample IDs before loading.
8. Start the isolated database using `docker compose up -d`, then run `python run_pipeline.py --stage load`.
9. Start the dashboard using `streamlit run dashboard/app.py`.

Do not finalize claims about peak hours, utilization, load profile, or the number of matched sessions until those calculations have been run against the extracted JPL data.

## Source references

- ACN-Data dataset and API documentation: https://ev.caltech.edu/dataset.html
- ACN-Data Static repository and JPL file count: https://github.com/tongxin-li/ACN-Data-Static
- Original dataset paper: Lee, Z. J., Li, T., & Low, S. H. (2019), *ACN-Data: Analysis and Applications of an Open EV Charging Dataset*, ACM e-Energy '19.
