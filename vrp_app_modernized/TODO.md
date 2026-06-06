# Deferred / TODO

## Integration follow-ups

- Replace simple CSV parsing with a robust quoted-field parser for enterprise imports.
- Add project-scoped matrix history browsing instead of only using the latest in-memory snapshot.
- Persist and expose matrix generation warnings per failed pair from all providers.
- Add project solution deletion / archiving controls.

## Solver UX follow-ups

- Add explicit Pareto-front visualization for NSGA-II when multiple returned solutions are exposed in the backend.
- Surface infeasibility penalty details more richly when Bloodhound returns non-feasible states.
- Expose advanced solver parameter presets and validation ranges in settings.

## Visualization follow-ups

- Replace the lightweight SVG route canvas with a richer map provider layer.
- Add cross-solution route quality diagnostics and overlap heatmaps.
- Add analytics dashboards across many saved solutions.

## Desktop follow-ups

- Wire desktop shell to native filesystem dialogs through Electron/Tauri IPC instead of browser file pickers.
- Add desktop-safe background process management for local backend startup and health monitoring.
