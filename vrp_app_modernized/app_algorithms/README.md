Active app solver copies live in this folder.

These files are the ones the VRP app backend loads at runtime:

- `bloodhoundtest3_for_app.py`
- `NSGA_2_BETTER`

Purpose:
- keep the app's working solver versions separate from the broader `research/algorithms` area
- reduce accidental breakage from edits made to research copies

Important:
- if you want to change the live app solver behavior, edit the files in this folder
- after editing them, restart the backend before running a new optimization
