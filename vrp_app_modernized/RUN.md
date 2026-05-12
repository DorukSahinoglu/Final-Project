# PulseRoute Modernized Run Guide

## Web mode

1. Backend:
   - `cd backend`
   - `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`

2. Frontend:
   - `cd frontend`
   - `npm run dev`

3. Open:
   - `http://localhost:5173`
   - API docs: `http://127.0.0.1:8000/docs`

## Desktop dev shell

- Double-click `open_desktop_dev.bat`

This keeps the project editable and uses the same frontend/backend codepaths as the web version.

## Recommended demo flow

1. Open Settings and save a Google API key if you want Google geocoding and Google distance matrix.
2. In Workflow, click `Load sample`.
3. Save the project.
4. Geocode addresses.
5. Generate matrix.
6. Run Bloodhound and inspect the solution.
7. If the fleet is homogeneous, run NSGA-II too.
8. Open Compare for side-by-side saved solver results.

## Notes

- If Google API key is empty, geocoding falls back to Nominatim and matrix falls back to haversine.
- Updating a saved project clears stale matrices, jobs, and solutions on purpose.
- CSV import currently expects a simple comma-separated file with headers like:
  - `label,address,demand,latitude,longitude,service_time_min,notes,is_depot`
