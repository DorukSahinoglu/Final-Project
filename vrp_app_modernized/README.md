# PulseRoute Modernized App

Near-final editable desktop-ready VRP product workspace.

Structure:
- `frontend/` React + TypeScript + Tailwind + Framer Motion UI
- `backend/` FastAPI + SQLite service layer
- `desktop/` Electron desktop shell scaffold

Notes:
- Web version remains intact inside `frontend/`
- Desktop shell launches local frontend + backend during development
- Packaging is intentionally not frozen yet; architecture stays editable
