from __future__ import annotations

import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vrp_app_final import main as full_main  # type: ignore
else:
    from . import main as full_main


full_main.AUTOSAVE_DIR = os.path.join(os.getenv("APPDATA") or full_main.BASE_DIR, "VRP_App_Simplified")
full_main.AUTOSAVE_PATH = os.path.join(full_main.AUTOSAVE_DIR, "autosave_project.json")
full_main.RUNTIME_DATA_DIR = full_main.AUTOSAVE_DIR


class SimplifiedVRPApp(full_main.VRPFinalApp):
    NSGA_DEFAULTS = {
        "pop_size": 60,
        "generations": 1000,
        "seed": 0,
        "crossover_rate": 0.99,
        "base_mutation": 0.03,
        "boost_mutation": 0.30,
        "mutation_kind": "swap",
        "duplicate_penalty": 12.0,
        "tournament_k": 5,
    }
    BLOODHOUND_DEFAULTS = {
        "num_wolves": 50,
        "num_hunts": 40,
        "explore_iterations": 120,
        "reserve_blood": 2.3,
        "lambda_reg": 1.0,
        "a": 2.0,
        "b": 1.0,
        "c": 1.4,
        "b_par": 1.2,
        "inherit_frac": 0.5,
        "ruin_frac": 0.20,
        "rr_repeats": 4,
        "verbose": True,
    }

    class _LockedValue:
        def __init__(self, value):
            self.value = "" if value is None else str(value)

        def get(self):
            return self.value

        def delete(self, *_args):
            self.value = ""

        def insert(self, _index, value):
            self.value = "" if value is None else str(value)

    def __init__(self):
        super().__init__()
        self.title("VRP App Simplified")

    def _build_run_tab(self):
        left, right = self._make_sidebar_layout(self._tab_run, sidebar_width=305)

        solver_card = self._card(left, "Automatic Solver")
        self._solver_var = full_main.tk.StringVar(value=full_main.SolverKey.NSGA2.value)
        self._solver_badge = full_main.tk.Label(
            solver_card,
            text="Solver will be selected automatically.",
            font=full_main.LABEL_FONT,
            bg=full_main.PANEL,
            fg=full_main.TEXT,
            justify="left",
            anchor="w",
        )
        self._solver_badge.pack(fill="x", pady=(0, 6))
        self._solver_hint = full_main.tk.Label(
            solver_card,
            text="Homogeneous fleets use NSGA-II. Heterogeneous fleets use Bloodhound.",
            font=full_main.SMALL_FONT,
            bg=full_main.PANEL,
            fg=full_main.TEXT_DIM,
            justify="left",
            wraplength=215,
        )
        self._solver_hint.pack(anchor="w")

        limits_card = self._card(left, "Route Constraint")
        self._nsga_entries = {
            key: self._LockedValue(value)
            for key, value in self.NSGA_DEFAULTS.items()
        }
        self._bloodhound_entries = {}
        row = full_main.tk.Frame(limits_card, bg=full_main.PANEL)
        row.pack(fill="x", pady=2)
        full_main.tk.Label(
            row,
            text="Max Route Min",
            bg=full_main.PANEL,
            fg=full_main.TEXT_DIM,
            width=14,
            anchor="w",
            font=full_main.SMALL_FONT,
        ).pack(side="left")
        max_route_entry = self._make_entry(row, width=10)
        max_route_entry.pack(side="right")
        self._bloodhound_entries["max_route_time_min"] = max_route_entry

        info = full_main.tk.Label(
            limits_card,
            text="Leave empty to disable the route-time cap. This limit is applied when Bloodhound is selected automatically.",
            font=full_main.SMALL_FONT,
            bg=full_main.PANEL,
            fg=full_main.TEXT_DIM,
            justify="left",
            wraplength=215,
        )
        info.pack(anchor="w", pady=(8, 0))

        btn_row = full_main.tk.Frame(left, bg=full_main.BG)
        btn_row.pack(fill="x", pady=(10, 0))
        self._btn_run = self._make_button(btn_row, "START", self._start_solve, tone="success")
        self._btn_run.pack(fill="x", pady=(0, 4))
        self._btn_stop = self._make_button(btn_row, "STOP", self._stop_solve, tone="danger")
        self._btn_stop.configure(state="disabled")
        self._btn_stop.pack(fill="x")

        self._prog_var = full_main.tk.DoubleVar(value=0.0)
        self._prog_lbl = full_main.tk.Label(left, text="Ready", font=full_main.LABEL_FONT, bg=full_main.BG, fg=full_main.TEXT_DIM)
        self._prog_lbl.pack(anchor="w", pady=(12, 2))
        full_main.ttk.Progressbar(left, variable=self._prog_var, maximum=100, style="run.Horizontal.TProgressbar").pack(fill="x")

        self._section_label(right, "Run Summary", pady=(12, 6))
        self._run_summary = full_main.tk.Label(right, text="", font=full_main.LABEL_FONT, bg=full_main.BG, fg=full_main.TEXT_DIM, justify="left")
        self._run_summary.pack(anchor="w", pady=(2, 8), padx=12)

        self._section_label(right, "Run Log", pady=(10, 4))
        self._run_log = self._make_text_area(right, fg=full_main.LOG_FG)
        self._run_log.configure(state="disabled")
        self._run_log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _infer_solver_key(self) -> full_main.SolverKey:
        signatures = {
            (u["capacity"], u["fixed_cost"], u["cost_per_km"])
            for u in self._fleet
        }
        if len(signatures) == 1:
            return full_main.SolverKey.NSGA2
        return full_main.SolverKey.BLOODHOUND

    def _build_problem(self) -> full_main.VRPProblemData:
        selected_source_locations = [loc for loc in self._locations if loc.get("is_depot") or loc.get("selected")]
        source_indices = [loc["id"] for loc in selected_source_locations]

        locations = []
        demands = []
        for loc in selected_source_locations:
            locations.append(
                full_main.LocationRecord(
                    node_id=loc["id"],
                    name=loc.get("name", ""),
                    address=loc.get("address", ""),
                    lat=loc.get("lat"),
                    lon=loc.get("lon"),
                    is_depot=bool(loc.get("is_depot")),
                )
            )
            if not loc.get("is_depot"):
                demands.append(full_main.CustomerDemand(node_id=loc["id"], demand=float(loc.get("demand", 1.0))))

        fleet = [
            full_main.FleetUnit(
                vehicle_type_id=item["vehicle_type_id"],
                label=item["label"],
                count=int(item["count"]),
                capacity=float(item["capacity"]),
                fixed_cost=float(item["fixed_cost"]),
                cost_per_km=float(item["cost_per_km"]),
                speed_kmh=float(item["speed_kmh"]),
            )
            for item in self._fleet
        ]

        solver_key = self._infer_solver_key()
        self._solver_var.set(solver_key.value)
        sub_dist = [[self._dist_matrix[i][j] for j in source_indices] for i in source_indices]
        sub_time = [[self._time_matrix[i][j] for j in source_indices] for i in source_indices]
        return full_main.VRPProblemData(
            locations=locations,
            distance_matrix=sub_dist,
            time_matrix=sub_time,
            demands=demands,
            fleet=fleet,
            solver_config=full_main.SolverConfig(solver_key=solver_key, params=self._collect_solver_params(solver_key)),
        )

    def _collect_solver_params(self, solver_key: full_main.SolverKey) -> dict:
        if solver_key is full_main.SolverKey.NSGA2:
            return dict(self.NSGA_DEFAULTS)
        params = dict(self.BLOODHOUND_DEFAULTS)
        max_route_text = self._bloodhound_entries["max_route_time_min"].get().strip()
        params["max_route_time_min"] = float(max_route_text) if max_route_text else None
        return params

    def _update_solver_choices(self):
        solver_key = self._infer_solver_key()
        self._solver_var.set(solver_key.value)
        if hasattr(self, "_solver_badge"):
            label = "NSGA-II" if solver_key is full_main.SolverKey.NSGA2 else "Bloodhound"
            self._solver_badge.configure(text=f"Auto-selected solver: {label}")
        self._refresh_run_summary()

    def _update_param_visibility(self):
        self._refresh_run_summary()

    def _refresh_run_summary(self):
        selected_count = sum(1 for loc in self._locations if not loc.get("is_depot") and loc.get("selected"))
        total_locations = len(self._locations)
        total_units = sum(unit["count"] for unit in self._fleet)
        signatures = {
            (u["capacity"], u["fixed_cost"], u["cost_per_km"])
            for u in self._fleet
        }
        problem_type = "Homogeneous" if len(signatures) == 1 else "Heterogeneous"
        solver_key = self._infer_solver_key()
        solver_name = "NSGA-II" if solver_key is full_main.SolverKey.NSGA2 else "Bloodhound"
        max_route_text = self._bloodhound_entries["max_route_time_min"].get().strip() if hasattr(self, "_bloodhound_entries") else ""
        if max_route_text.lower() == "none":
            max_route_text = ""
            self._bloodhound_entries["max_route_time_min"].delete(0, "end")
        max_route_line = max_route_text if max_route_text else "Disabled"
        self._run_summary.configure(
            text=(
                f"Total locations: {total_locations}\n"
                f"Selected customers: {selected_count}\n"
                f"Problem type: {problem_type}\n"
                f"Total vehicles: {total_units}\n"
                f"Auto solver: {solver_name}\n"
                f"Max route time: {max_route_line}"
            )
        )
        if hasattr(self, "_solver_hint"):
            if solver_key is full_main.SolverKey.NSGA2:
                text = "This fleet is homogeneous, so NSGA-II will run with locked internal parameters."
            else:
                text = "This fleet is heterogeneous, so Bloodhound will run with locked internal parameters."
                if max_route_text:
                    text += f"\nRoute-time cap: {max_route_text} minutes."
            self._solver_hint.configure(text=text)


if __name__ == "__main__":
    app = SimplifiedVRPApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
