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
