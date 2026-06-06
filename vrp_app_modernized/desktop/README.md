# Desktop Shell

Electron development shell for PulseRoute.

Design goals:
- keep web UI intact
- provide real application window behavior
- preserve editable frontend/backend sources
- keep preload minimal and IPC-safe

Current bridge:
- read-only `window.desktopBridge` metadata

TODO:
- native file dialog wrappers for import/export
- native notifications bridge
- persisted desktop window layout state
- secure settings storage migration if needed
