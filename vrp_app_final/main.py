from __future__ import annotations

import csv
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from copy import deepcopy
from tkinter import filedialog, messagebox, scrolledtext, ttk

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from vrp_app_final.schemas import (  # type: ignore
        CustomerDemand,
        FleetUnit,
        LocationRecord,
        SolverConfig,
        SolverKey,
        VRPProblemData,
    )
    from vrp_app_final.solver_contracts import (  # type: ignore
        choose_available_solvers,
        get_solver_adapter,
    )
else:
    from .schemas import CustomerDemand, FleetUnit, LocationRecord, SolverConfig, SolverKey, VRPProblemData
    from .solver_contracts import choose_available_solvers, get_solver_adapter


BG = "#0b1220"
PANEL = "#111827"
SURFACE = "#162033"
SURFACE_ALT = "#0f172a"
ACCENT = "#0f766e"
ACCENT2 = "#5eead4"
SUCCESS = "#16a34a"
WARNING = "#d97706"
DANGER = "#dc2626"
TEXT = "#e5eef9"
TEXT_DIM = "#94a3b8"
BORDER = "#263449"
LOG_BG = "#09111d"
LOG_FG = "#9ae6b4"
TITLE_FONT = ("Bahnschrift", 17, "bold")
SUBTITLE_FONT = ("Segoe UI", 9)
SECTION_FONT = ("Segoe UI", 10, "bold")
LABEL_FONT = ("Segoe UI", 8)
SMALL_FONT = ("Segoe UI", 7)
MONO_FONT = ("Consolas", 8)

GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
FALLBACK_SPEED_KMH = 35.0
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
NSGA_WARNING_CUSTOMER_THRESHOLD = 40
AUTOSAVE_DIR = os.path.join(os.getenv("APPDATA") or BASE_DIR, "VRP_App_Final")
AUTOSAVE_PATH = os.path.join(AUTOSAVE_DIR, "autosave_project.json")
RUNTIME_DATA_DIR = AUTOSAVE_DIR
XLSX_NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def google_geocode(address: str, api_key: str):
    candidates = [address.strip()]
    if "ankara" not in address.lower():
        candidates.append(address.strip() + ", Ankara, Turkiye")

    for query in candidates:
        params = {
            "address": query,
            "key": api_key,
            "region": "tr",
            "components": "country:TR",
        }
        url = GOOGLE_GEOCODE_URL + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": "VRP-App-Final/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                obj = json.loads(response.read().decode("utf-8"))
        except Exception:
            continue

        if obj.get("status") != "OK":
            continue

        results = obj.get("results") or []
        if not results:
            continue

        location = results[0].get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        if lat is not None and lng is not None:
            time.sleep(0.2)
            return float(lat), float(lng)
    return None


def osrm_route(lat1: float, lon1: float, lat2: float, lon2: float):
    url = (
        "https://router.project-osrm.org/route/v1/driving/"
        f"{lon1},{lat1};{lon2},{lat2}?overview=false"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "VRP-App-Final/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            obj = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None, None

    if obj.get("code") != "Ok":
        return None, None

    routes = obj.get("routes") or []
    if not routes:
        return None, None

    distance_m = routes[0].get("distance")
    duration_s = routes[0].get("duration")
    if distance_m is None:
        return None, None

    time.sleep(0.15)
    return round(distance_m / 1000.0, 3), round((duration_s or 0.0) / 60.0, 3)


def _excel_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord("A") + 1)
    return max(0, value - 1)


def _read_xlsx_rows(path: str) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("main:si", XLSX_NS):
                parts = [node.text or "" for node in item.findall(".//main:t", XLSX_NS)]
                shared_strings.append("".join(parts))

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = workbook_root.findall("main:sheets/main:sheet", XLSX_NS)
        if not sheets:
            return []
        rel_id = sheets[0].attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")

        rel_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        sheet_target = None
        for rel in rel_root:
            if rel.attrib.get("Id") == rel_id:
                sheet_target = rel.attrib.get("Target")
                break
        sheet_path = "xl/" + (sheet_target or "worksheets/sheet1.xml").lstrip("/")

        sheet_root = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str]] = []
        for row in sheet_root.findall("main:sheetData/main:row", XLSX_NS):
            values: dict[int, str] = {}
            max_col = -1
            for cell in row.findall("main:c", XLSX_NS):
                ref = cell.attrib.get("r", "")
                col_idx = _excel_col_to_index(ref)
                max_col = max(max_col, col_idx)
                cell_type = cell.attrib.get("t")
                value_node = cell.find("main:v", XLSX_NS)
                inline_node = cell.find("main:is/main:t", XLSX_NS)
                raw_value = value_node.text if value_node is not None else (inline_node.text if inline_node is not None else "")
                if cell_type == "s" and raw_value:
                    try:
                        values[col_idx] = shared_strings[int(raw_value)]
                    except Exception:
                        values[col_idx] = raw_value
                else:
                    values[col_idx] = raw_value or ""
            if max_col >= 0:
                rows.append([values.get(idx, "").strip() for idx in range(max_col + 1)])
        return rows


def _read_table_rows(path: str) -> list[list[str]]:
    lower = path.lower()
    if lower.endswith(".csv"):
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return [[(cell or "").strip() for cell in row] for row in csv.reader(handle)]
    if lower.endswith(".xlsx"):
        return _read_xlsx_rows(path)
    raise ValueError("Unsupported file type. Please select an .xlsx or .csv file.")


class VRPFinalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VRP App Final")
        self.geometry("1260x860")
        self.minsize(1060, 720)
        self.configure(bg=BG)

        self._queue = queue.Queue()
        self._geo_stop = [False]
        self._geo_running = False
        self._after_id = None
        self._solve_stop = [False]
        self._solve_running = False
        self._solve_thread = None
        self._last_solver_result = None
        self._last_solver_key = SolverKey.NSGA2.value

        self._locations = [
            {
                "id": 0,
                "name": "Depot",
                "address": "",
                "is_depot": True,
                "selected": False,
                "demand": 0.0,
            }
        ]
        self._fleet = [
            {
                "vehicle_type_id": "vehicle-1",
                "label": "Standard Vehicle",
                "count": 3,
                "capacity": 10.0,
                "fixed_cost": 45.0,
                "cost_per_km": 32.0,
                "speed_kmh": 35.0,
            }
        ]
        self._dist_matrix = [[0.0]]
        self._time_matrix = [[0.0]]
        self._customer_rows = []
        self._result_solutions = []
        self._result_warnings = []

        self._build_ui()
        if not self._load_autosave():
            self._refresh_all_views()
        self._after_id = self.after(100, self._poll_queue)

    def _build_ui(self):
        header = tk.Frame(self, bg=SURFACE_ALT, height=66, highlightthickness=1, highlightbackground=BORDER)
        header.pack(fill="x", padx=10, pady=(10, 0))
        header.pack_propagate(False)
        accent_bar = tk.Frame(header, bg=ACCENT, width=8)
        accent_bar.pack(side="left", fill="y")

        title_wrap = tk.Frame(header, bg=SURFACE_ALT)
        title_wrap.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(
            title_wrap,
            text="VRP App Final",
            font=TITLE_FONT,
            bg=SURFACE_ALT,
            fg=TEXT,
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Manage locations, fleet, and solver flow in one screen.",
            font=SUBTITLE_FONT,
            bg=SURFACE_ALT,
            fg=TEXT_DIM,
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            header,
            text="Desktop Planner",
            font=("Segoe UI", 8, "bold"),
            bg=SURFACE,
            fg=ACCENT2,
            padx=10,
            pady=5,
        ).pack(side="right", padx=14)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "dark.Treeview",
            background=SURFACE,
            foreground=TEXT,
            fieldbackground=SURFACE,
            borderwidth=0,
            rowheight=30,
            font=LABEL_FONT,
        )
        style.map("dark.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure(
            "dark.Treeview.Heading",
            background=SURFACE_ALT,
            foreground=ACCENT2,
            borderwidth=0,
            font=("Segoe UI", 9, "bold"),
            padding=8,
        )
        style.configure(
            "app.TCombobox",
            fieldbackground=SURFACE_ALT,
            background=SURFACE_ALT,
            foreground=TEXT,
            arrowcolor=ACCENT2,
            bordercolor=BORDER,
            lightcolor=SURFACE_ALT,
            darkcolor=SURFACE_ALT,
            padding=6,
        )
        style.map("app.TCombobox", fieldbackground=[("readonly", SURFACE_ALT)], selectbackground=[("readonly", SURFACE_ALT)])
        style.configure("run.Horizontal.TProgressbar", troughcolor=SURFACE_ALT, background=ACCENT, borderwidth=0)

        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True, padx=10, pady=(8, 10))

        self._nav = tk.Frame(shell, bg=SURFACE_ALT, width=185, highlightthickness=1, highlightbackground=BORDER)
        self._nav.pack(side="left", fill="y")
        self._nav.pack_propagate(False)

        self._content_host = tk.Frame(shell, bg=BG, highlightthickness=1, highlightbackground=BORDER)
        self._content_host.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._tab_loc = tk.Frame(self._content_host, bg=BG)
        self._tab_cust = tk.Frame(self._content_host, bg=BG)
        self._tab_fleet = tk.Frame(self._content_host, bg=BG)
        self._tab_run = tk.Frame(self._content_host, bg=BG)
        self._tab_matrix = tk.Frame(self._content_host, bg=BG)
        self._tab_results = tk.Frame(self._content_host, bg=BG)
        self._tab_routeview = tk.Frame(self._content_host, bg=BG)

        self._tab_order = [
            ("loc", "Locations", self._tab_loc),
            ("cust", "Customers", self._tab_cust),
            ("fleet", "Fleet", self._tab_fleet),
            ("run", "Run", self._tab_run),
            ("matrix", "Matrices", self._tab_matrix),
            ("results", "Results", self._tab_results),
            ("routeview", "Route View", self._tab_routeview),
        ]
        self._nav_buttons = {}
        self._active_tab_key = None

        self._build_nav()

        self._build_location_tab()
        self._build_customer_tab()
        self._build_fleet_tab()
        self._build_run_tab()
        self._build_matrix_tab()
        self._build_results_tab()
        self._build_route_view_tab()
        self._select_tab("loc")

    def _card(self, parent, title: str):
        outer = tk.Frame(
            parent,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )
        outer.pack(fill="x", pady=4)
        tk.Label(
            outer,
            text=title,
            font=SECTION_FONT,
            bg=PANEL,
            fg=ACCENT2,
        ).pack(anchor="w", padx=10, pady=(8, 4))
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=(0, 10))
        return inner

    def _section_label(self, parent, text: str, *, pady=(0, 6)):
        return tk.Label(parent, text=text, font=SECTION_FONT, bg=BG, fg=TEXT).pack(anchor="w", pady=pady)

    def _build_nav(self):
        brand = tk.Frame(self._nav, bg=SURFACE_ALT)
        brand.pack(fill="x", padx=10, pady=(12, 8))
        tk.Label(brand, text="Control Panel", font=("Segoe UI", 10, "bold"), bg=SURFACE_ALT, fg=ACCENT2).pack(anchor="w")
        tk.Label(
            brand,
            text="All main screens stay pinned here.",
            font=SMALL_FONT,
            bg=SURFACE_ALT,
            fg=TEXT_DIM,
            wraplength=145,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        for key, label, _frame in self._tab_order:
            btn = tk.Button(
                self._nav,
                text=label,
                command=lambda current=key: self._select_tab(current),
                font=("Segoe UI", 9, "bold"),
                bg=SURFACE_ALT,
                fg=TEXT_DIM,
                activebackground=SURFACE,
                activeforeground=TEXT,
                relief="flat",
                bd=0,
                anchor="w",
                padx=12,
                pady=8,
                cursor="hand2",
            )
            btn.pack(fill="x", padx=8, pady=2)
            self._nav_buttons[key] = btn

    def _select_tab(self, key: str):
        self._active_tab_key = key
        for current_key, _label, frame in self._tab_order:
            frame.pack_forget()
            if current_key == key:
                frame.pack(fill="both", expand=True)
            btn = self._nav_buttons.get(current_key)
            if not btn:
                continue
            if current_key == key:
                btn.configure(bg=ACCENT, fg="white", activebackground=ACCENT, activeforeground="white")
            else:
                btn.configure(bg=SURFACE_ALT, fg=TEXT_DIM, activebackground=SURFACE, activeforeground=TEXT)

    def _make_entry(self, parent, *, textvariable=None, width=None, show=None):
        return tk.Entry(
            parent,
            textvariable=textvariable,
            font=LABEL_FONT,
            bg=SURFACE_ALT,
            fg=TEXT,
            insertbackground=TEXT,
            relief="flat",
            bd=5,
            width=width,
            show=show,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )

    def _make_button(self, parent, text: str, command, tone: str = "neutral"):
        colors = {
            "accent": (ACCENT, "white"),
            "success": (SUCCESS, "white"),
            "danger": (DANGER, "white"),
            "warning": (WARNING, "white"),
            "neutral": (SURFACE, TEXT),
            "ghost": (PANEL, TEXT_DIM),
        }
        bg_color, fg_color = colors[tone]
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 8, "bold" if tone in {"accent", "success", "danger", "warning"} else "normal"),
            bg=bg_color,
            fg=fg_color,
            activebackground=bg_color,
            activeforeground=fg_color,
            relief="flat",
            bd=0,
            padx=10,
            pady=5,
            cursor="hand2",
        )

    def _make_text_area(self, parent, *, height=10, fg=TEXT):
        return scrolledtext.ScrolledText(
            parent,
            font=MONO_FONT,
            bg=LOG_BG,
            fg=fg,
            insertbackground=TEXT,
            relief="flat",
            bd=5,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            height=height,
        )

    def _make_sidebar_layout(self, parent, *, sidebar_width=300):
        shell = tk.Frame(parent, bg=BG)
        shell.pack(fill="both", expand=True, padx=10, pady=10)

        paned = tk.PanedWindow(shell, orient="horizontal", sashrelief="flat", sashwidth=6, bg=BG, bd=0)
        paned.pack(fill="both", expand=True)

        sidebar_outer = tk.Frame(paned, bg=BG, width=sidebar_width)
        sidebar_outer.pack_propagate(False)
        canvas_wrap = tk.Frame(
            sidebar_outer,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
        )
        canvas_wrap.pack(fill="both", expand=True)
        sidebar_canvas = tk.Canvas(canvas_wrap, bg=BG, highlightthickness=0)
        sidebar_scroll = tk.Scrollbar(
            canvas_wrap,
            orient="vertical",
            command=sidebar_canvas.yview,
            width=14,
            troughcolor=SURFACE_ALT,
            bg=ACCENT,
            activebackground=ACCENT2,
            relief="flat",
            bd=0,
            highlightthickness=0,
        )
        sidebar_inner = tk.Frame(sidebar_canvas, bg=BG)
        sidebar_window = sidebar_canvas.create_window((0, 0), window=sidebar_inner, anchor="nw")
        sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_canvas.pack(side="left", fill="both", expand=True)
        sidebar_scroll.pack(side="right", fill="y")
        sidebar_inner.bind("<Configure>", lambda _e: sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all")))
        sidebar_canvas.bind("<Configure>", lambda e: sidebar_canvas.itemconfigure(sidebar_window, width=e.width))

        def _on_mousewheel(event):
            sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        sidebar_canvas.bind("<Enter>", lambda _e: sidebar_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        sidebar_canvas.bind("<Leave>", lambda _e: sidebar_canvas.unbind_all("<MouseWheel>"))

        content = tk.Frame(
            paned,
            bg=BG,
            highlightthickness=1,
            highlightbackground=BORDER,
        )

        paned.add(sidebar_outer, minsize=250, width=sidebar_width)
        paned.add(content, minsize=460)
        return sidebar_inner, content

    def _build_location_tab(self):
        left, right = self._make_sidebar_layout(self._tab_loc, sidebar_width=295)

        api_card = self._card(left, "Google API Key")
        self._api_key_var = tk.StringVar()
        self._api_key_entry = self._make_entry(api_card, textvariable=self._api_key_var, show="*")
        self._api_key_entry.pack(fill="x")
        self._make_button(api_card, "Goster / Gizle", self._toggle_api_key, tone="ghost").pack(anchor="w", pady=(8, 0))

        depot_card = self._card(left, "Depot Details")
        self._depot_name_var = tk.StringVar()
        self._depot_addr_var = tk.StringVar()
        for label, var in (("Depot Name", self._depot_name_var), ("Depot Address", self._depot_addr_var)):
            tk.Label(depot_card, text=label, font=SMALL_FONT, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
            self._make_entry(depot_card, textvariable=var).pack(fill="x", pady=(0, 6))
        self._make_button(depot_card, "Update Depot", self._save_depot_form, tone="accent").pack(fill="x")

        form_card = self._card(left, "Customer Location")
        self._loc_form_id = None
        self._loc_name_var = tk.StringVar()
        self._loc_addr_var = tk.StringVar()
        for label, var in (("Name", self._loc_name_var), ("Address", self._loc_addr_var)):
            tk.Label(form_card, text=label, font=SMALL_FONT, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
            self._make_entry(form_card, textvariable=var).pack(fill="x", pady=(0, 6))
        tk.Label(
            form_card,
            text="Records added in this section are treated as customers.",
            font=SMALL_FONT,
            bg=PANEL,
            fg=TEXT_DIM,
            wraplength=210,
            justify="left",
        ).pack(anchor="w", pady=(2, 8))

        button_row = tk.Frame(form_card, bg=PANEL)
        button_row.pack(fill="x")
        for text, cmd, color in (
            ("Add New", self._add_location, "accent"),
            ("Update", self._update_location, "success"),
            ("Clear", self._clear_location_form, "neutral"),
        ):
            self._make_button(button_row, text, cmd, tone=color).pack(fill="x", pady=(0, 6))

        file_card = self._card(left, "File Actions")
        for text, cmd in (
            ("Save Project", self._save_project),
            ("Load Project", self._load_project),
            ("Save Locations", self._save_locations),
            ("Load Locations", self._load_locations),
            ("Import from Excel / CSV", self._import_locations_from_sheet),
            ("Load Matrices from JSON", self._load_matrices_from_json),
        ):
            self._make_button(file_card, text, cmd, tone="neutral").pack(fill="x", pady=3)

        geo_card = self._card(left, "Geocoding and OSRM")
        self._btn_geocode = self._make_button(geo_card, "Find Coordinates", self._start_geocoding, tone="warning")
        self._btn_geocode.pack(fill="x", pady=(0, 4))
        self._btn_matrix = self._make_button(geo_card, "Build Distance + Time Matrix", self._start_matrix, tone="accent")
        self._btn_matrix.pack(fill="x", pady=(0, 4))
        self._btn_geo_stop = self._make_button(geo_card, "Stop", self._stop_geo, tone="danger")
        self._btn_geo_stop.configure(state="disabled")
        self._btn_geo_stop.pack(fill="x")

        self._section_label(right, "Locations", pady=(12, 6))
        columns = ("ID", "Type", "Name", "Address", "Demand", "Selected", "Lat", "Lon")
        tree_frame = tk.Frame(right, bg=BG)
        tree_frame.pack(fill="both", expand=True, pady=(4, 0), padx=12)
        self._loc_tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=12, style="dark.Treeview")
        widths = [45, 70, 140, 260, 65, 60, 90, 90]
        for col, width in zip(columns, widths):
            self._loc_tree.heading(col, text=col)
            self._loc_tree.column(col, width=width, anchor="center")
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._loc_tree.xview)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._loc_tree.yview)
        self._loc_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._loc_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        hsb.pack(side="bottom", fill="x")
        self._loc_tree.bind("<<TreeviewSelect>>", self._load_selected_location)

        row = tk.Frame(right, bg=BG)
        row.pack(fill="x", pady=(8, 0), padx=12)
        self._make_button(row, "Delete Selected Location", self._delete_selected_location, tone="danger").pack(side="left")

        self._section_label(right, "Activity Log", pady=(12, 4))
        self._geo_log = self._make_text_area(right, height=10, fg=LOG_FG)
        self._geo_log.configure(state="disabled")
        self._geo_log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_customer_tab(self):
        self._section_label(self._tab_cust, "Customer selection and demand values", pady=(10, 4))

        top = tk.Frame(self._tab_cust, bg=BG)
        top.pack(fill="x", padx=12, pady=(0, 6))
        self._cust_summary = tk.Label(top, text="", font=LABEL_FONT, bg=BG, fg=ACCENT2)
        self._cust_summary.pack(side="left")
        self._make_button(top, "Select All", self._select_all_customers, tone="accent").pack(side="right", padx=(6, 0))
        self._make_button(top, "Clear All", self._deselect_all_customers, tone="neutral").pack(side="right")

        outer = tk.Frame(self._tab_cust, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        outer.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        self._cust_frame = tk.Frame(canvas, bg=PANEL)
        self._cust_window = canvas.create_window((0, 0), window=self._cust_frame, anchor="nw")
        self._cust_canvas = canvas
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._cust_frame.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(self._cust_window, width=e.width))

    def _build_fleet_tab(self):
        left, right = self._make_sidebar_layout(self._tab_fleet, sidebar_width=285)

        form_card = self._card(left, "Vehicle Type Form")
        self._fleet_form_type_id = None
        self._fleet_vars = {
            "label": tk.StringVar(),
            "count": tk.StringVar(value="1"),
            "capacity": tk.StringVar(value="10"),
            "fixed_cost": tk.StringVar(value="45"),
            "cost_per_km": tk.StringVar(value="32"),
            "speed_kmh": tk.StringVar(value="35"),
        }
        labels = {
            "label": "Label",
            "count": "Count",
            "capacity": "Capacity",
            "fixed_cost": "Fixed Cost",
            "cost_per_km": "Cost per Km",
            "speed_kmh": "Speed (km/h)",
        }
        for key in ("label", "count", "capacity", "fixed_cost", "cost_per_km", "speed_kmh"):
            tk.Label(form_card, text=labels[key], font=SMALL_FONT, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
            self._make_entry(form_card, textvariable=self._fleet_vars[key]).pack(fill="x", pady=(0, 6))

        row = tk.Frame(form_card, bg=PANEL)
        row.pack(fill="x")
        self._make_button(row, "Add New Type", self._add_fleet_unit, tone="accent").pack(fill="x", pady=(0, 6))
        self._make_button(row, "Update", self._update_fleet_unit, tone="success").pack(fill="x", pady=(0, 6))
        self._make_button(row, "Clear", self._clear_fleet_form, tone="neutral").pack(fill="x")

        self._section_label(right, "Fleet Summary", pady=(12, 6))
        self._fleet_summary = tk.Label(right, text="", font=LABEL_FONT, bg=BG, fg=ACCENT2)
        self._fleet_summary.pack(anchor="w", pady=(2, 6), padx=12)
        columns = ("ID", "Label", "Count", "Capacity", "Fixed", "Km Cost", "Speed")
        fleet_frame = tk.Frame(right, bg=BG)
        fleet_frame.pack(fill="both", expand=True, padx=12)
        self._fleet_tree = ttk.Treeview(fleet_frame, columns=columns, show="headings", height=10, style="dark.Treeview")
        widths = [110, 160, 60, 80, 80, 80, 80]
        for col, width in zip(columns, widths):
            self._fleet_tree.heading(col, text=col)
            self._fleet_tree.column(col, width=width, anchor="center")
        fleet_hsb = ttk.Scrollbar(fleet_frame, orient="horizontal", command=self._fleet_tree.xview)
        fleet_vsb = ttk.Scrollbar(fleet_frame, orient="vertical", command=self._fleet_tree.yview)
        self._fleet_tree.configure(xscrollcommand=fleet_hsb.set, yscrollcommand=fleet_vsb.set)
        self._fleet_tree.pack(side="left", fill="both", expand=True)
        fleet_vsb.pack(side="right", fill="y")
        fleet_hsb.pack(side="bottom", fill="x")
        self._fleet_tree.bind("<<TreeviewSelect>>", self._load_selected_fleet)

        self._make_button(right, "Delete Selected Vehicle Type", self._delete_selected_fleet, tone="danger").pack(anchor="w", pady=(8, 12), padx=12)

    def _build_run_tab(self):
        left, right = self._make_sidebar_layout(self._tab_run, sidebar_width=305)

        solver_card = self._card(left, "Solver")
        self._solver_var = tk.StringVar(value=SolverKey.NSGA2.value)
        self._solver_menu = ttk.Combobox(
            solver_card,
            textvariable=self._solver_var,
            state="readonly",
            values=[SolverKey.NSGA2.value, SolverKey.BLOODHOUND.value],
            style="app.TCombobox",
        )
        self._solver_menu.pack(fill="x", pady=(0, 6))
        self._solver_menu.bind("<<ComboboxSelected>>", lambda _e: self._update_param_visibility())
        self._solver_hint = tk.Label(solver_card, text="", font=SMALL_FONT, bg=PANEL, fg=TEXT_DIM, justify="left", wraplength=215)
        self._solver_hint.pack(anchor="w")

        nsga_card = self._card(left, "NSGA-II Parameters")
        self._nsga_card = nsga_card.master
        self._nsga_entries = {}
        for label, key, default in (
            ("Population", "pop_size", "60"),
            ("Generations", "generations", "400"),
            ("Seed", "seed", "0"),
            ("Crossover", "crossover_rate", "0.90"),
            ("Base Mutation", "base_mutation", "0.05"),
            ("Boost Mutation", "boost_mutation", "0.60"),
            ("Mutation Kind", "mutation_kind", "inversion"),
            ("Duplicate Pen.", "duplicate_penalty", "12.0"),
            ("Tournament K", "tournament_k", "2"),
        ):
            row = tk.Frame(nsga_card, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=TEXT_DIM, width=14, anchor="w", font=SMALL_FONT).pack(side="left")
            entry = self._make_entry(row, width=10)
            entry.insert(0, default)
            entry.pack(side="right")
            self._nsga_entries[key] = entry

        bloodhound_card = self._card(left, "Bloodhound Parameters")
        self._bloodhound_card = bloodhound_card.master
        self._bloodhound_entries = {}
        for label, key, default in (
            ("Wolves", "num_wolves", "12"),
            ("Hunts", "num_hunts", "20"),
            ("Explore Iter.", "explore_iterations", "120"),
            ("Reserve Blood", "reserve_blood", "2.0"),
            ("Lambda Reg", "lambda_reg", "0.30"),
            ("Alpha (a)", "a", "1.5"),
            ("Beta (b)", "b", "2.0"),
            ("Gamma (c)", "c", "1.0"),
            ("B Param", "b_par", "1.2"),
            ("Inherit Frac", "inherit_frac", "0.35"),
            ("Ruin Frac", "ruin_frac", "0.20"),
            ("RR Repeats", "rr_repeats", "2"),
            ("Verbose", "verbose", "true"),
        ):
            row = tk.Frame(bloodhound_card, bg=PANEL)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, bg=PANEL, fg=TEXT_DIM, width=14, anchor="w", font=SMALL_FONT).pack(side="left")
            entry = self._make_entry(row, width=10)
            entry.insert(0, default)
            entry.pack(side="right")
            self._bloodhound_entries[key] = entry

        btn_row = tk.Frame(left, bg=BG)
        btn_row.pack(fill="x", pady=(10, 0))
        self._btn_run = self._make_button(btn_row, "START", self._start_solve, tone="success")
        self._btn_run.pack(fill="x", pady=(0, 4))
        self._btn_stop = self._make_button(btn_row, "STOP", self._stop_solve, tone="danger")
        self._btn_stop.configure(state="disabled")
        self._btn_stop.pack(fill="x")

        self._prog_var = tk.DoubleVar(value=0.0)
        self._prog_lbl = tk.Label(left, text="Ready", font=LABEL_FONT, bg=BG, fg=TEXT_DIM)
        self._prog_lbl.pack(anchor="w", pady=(12, 2))
        ttk.Progressbar(left, variable=self._prog_var, maximum=100, style="run.Horizontal.TProgressbar").pack(fill="x")

        self._section_label(right, "Run Summary", pady=(12, 6))
        self._run_summary = tk.Label(right, text="", font=LABEL_FONT, bg=BG, fg=TEXT_DIM, justify="left")
        self._run_summary.pack(anchor="w", pady=(2, 8), padx=12)

        self._section_label(right, "Run Log", pady=(10, 4))
        self._run_log = self._make_text_area(right, fg=LOG_FG)
        self._run_log.configure(state="disabled")
        self._run_log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_matrix_tab(self):
        tk.Label(
            self._tab_matrix,
            text="Distance and time matrices can be edited as JSON.",
            font=LABEL_FONT,
            bg=BG,
            fg=TEXT_DIM,
        ).pack(anchor="w", padx=12, pady=(8, 4))

        btn_row = tk.Frame(self._tab_matrix, bg=BG)
        btn_row.pack(fill="x", padx=12)
        for text, cmd, color in (
            ("Apply", self._apply_matrices, "success"),
            ("Resize to Locations", self._resize_matrices_to_locations, "neutral"),
            ("Save JSON", self._save_matrices, "neutral"),
            ("Load JSON", self._load_matrices_file, "neutral"),
        ):
            self._make_button(btn_row, text, cmd, tone=color).pack(side="left", padx=(0, 6))

        split = tk.PanedWindow(self._tab_matrix, sashrelief="flat", bg=BG)
        split.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        left = tk.Frame(split, bg=BG)
        right = tk.Frame(split, bg=BG)
        split.add(left)
        split.add(right)

        self._section_label(left, "Distance Matrix", pady=(0, 4))
        self._section_label(right, "Time Matrix", pady=(0, 4))
        self._dist_text = self._make_text_area(left, fg=TEXT)
        self._time_text = self._make_text_area(right, fg=TEXT)
        self._dist_text.pack(fill="both", expand=True, pady=(4, 0))
        self._time_text.pack(fill="both", expand=True, pady=(4, 0))

    def _build_results_tab(self):
        top = tk.Frame(self._tab_results, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="Solutions", font=SECTION_FONT, bg=BG, fg=TEXT).pack(side="left")
        self._result_title = tk.Label(top, text="", font=LABEL_FONT, bg=BG, fg=ACCENT2)
        self._result_title.pack(side="right", padx=(8, 0))
        self._make_button(top, "Save Results", self._save_results, tone="neutral").pack(side="right")
        self._make_button(top, "Open Route View", lambda: self._select_tab("routeview"), tone="accent").pack(side="right", padx=(0, 8))

        self._result_summary = tk.Label(
            self._tab_results,
            text="Run a solver to see a structured summary here.",
            font=LABEL_FONT,
            bg=BG,
            fg=TEXT_DIM,
            justify="left",
            anchor="w",
        )
        self._result_summary.pack(fill="x", padx=12, pady=(0, 8))

        columns = ("ID", "Total Cost", "Objectives", "Route Count", "Feasible")
        self._result_tree = ttk.Treeview(self._tab_results, columns=columns, show="headings", height=10, style="dark.Treeview")
        widths = [90, 120, 260, 90, 80]
        for col, width in zip(columns, widths):
            self._result_tree.heading(col, text=col)
            self._result_tree.column(col, width=width, anchor="center")
        self._result_tree.pack(fill="x", padx=12)
        self._result_tree.bind("<<TreeviewSelect>>", self._show_selected_solution)

        self._section_label(self._tab_results, "Warnings", pady=(10, 4))
        self._result_warning_text = self._make_text_area(self._tab_results, height=5, fg="#fca5a5")
        self._result_warning_text.configure(state="disabled")
        self._result_warning_text.pack(fill="x", padx=12, pady=(0, 8))

        self._section_label(self._tab_results, "Details", pady=(10, 4))
        self._result_detail = self._make_text_area(self._tab_results, height=16, fg="#fbbf24")
        self._result_detail.configure(state="disabled")
        self._result_detail.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _build_route_view_tab(self):
        top = tk.Frame(self._tab_routeview, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top, text="Selected Route View", font=SECTION_FONT, bg=BG, fg=TEXT).pack(side="left")
        self._route_view_title = tk.Label(top, text="", font=LABEL_FONT, bg=BG, fg=ACCENT2)
        self._route_view_title.pack(side="right")

        self._route_view_hint = tk.Label(
            self._tab_routeview,
            text="Select a solution in Results to inspect all route steps here.",
            font=LABEL_FONT,
            bg=BG,
            fg=TEXT_DIM,
            justify="left",
            anchor="w",
        )
        self._route_view_hint.pack(fill="x", padx=12, pady=(0, 8))

        self._route_view_text = self._make_text_area(self._tab_routeview, height=28, fg="#fbbf24")
        self._route_view_text.configure(state="disabled")
        self._route_view_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    def _refresh_all_views(self):
        self._normalize_locations_and_matrices()
        self._load_depot_form()
        self._refresh_location_tree()
        self._refresh_customer_tab()
        self._refresh_fleet_tree()
        self._load_matrix_editors()
        self._refresh_run_summary()
        self._update_solver_choices()

    def _normalize_locations_and_matrices(self):
        if not self._locations:
            self._locations = [
                {
                    "id": 0,
                    "name": "Depot",
                    "address": "",
                    "is_depot": True,
                    "selected": False,
                    "demand": 0.0,
                }
            ]

        old_locations = self._locations[:]
        old_dist = deepcopy(self._dist_matrix)
        old_time = deepcopy(self._time_matrix)
        old_size = len(old_locations)

        if not any(loc.get("is_depot") for loc in old_locations):
            old_locations[0]["is_depot"] = True
        else:
            first_depot = next(i for i, loc in enumerate(old_locations) if loc.get("is_depot"))
            for i, loc in enumerate(old_locations):
                loc["is_depot"] = i == first_depot

        ordered = sorted(old_locations, key=lambda loc: (0 if loc.get("is_depot") else 1, loc.get("id", 0)))
        old_index = {id(loc): idx for idx, loc in enumerate(old_locations)}
        for new_id, loc in enumerate(ordered):
            loc["id"] = new_id
            loc["demand"] = 0.0 if loc.get("is_depot") else float(loc.get("demand", 1.0))
            if loc.get("is_depot"):
                loc["selected"] = False
        self._locations = ordered

        n = len(self._locations)
        new_dist = [[0.0] * n for _ in range(n)]
        new_time = [[0.0] * n for _ in range(n)]
        for new_i, loc_i in enumerate(self._locations):
            old_i = old_index.get(id(loc_i))
            if old_i is None or old_i >= old_size:
                continue
            for new_j, loc_j in enumerate(self._locations):
                old_j = old_index.get(id(loc_j))
                if old_j is None or old_j >= old_size:
                    continue
                if old_i < len(old_dist) and old_j < len(old_dist[old_i]):
                    new_dist[new_i][new_j] = old_dist[old_i][old_j]
                if old_i < len(old_time) and old_j < len(old_time[old_i]):
                    new_time[new_i][new_j] = old_time[old_i][old_j]

        self._dist_matrix = new_dist
        self._time_matrix = new_time

    def _toggle_api_key(self):
        self._api_key_entry.configure(show="" if self._api_key_entry.cget("show") == "*" else "*")

    def _geo_log_write(self, message: str):
        self._geo_log.configure(state="normal")
        self._geo_log.insert("end", message + "\n")
        self._geo_log.see("end")
        self._geo_log.configure(state="disabled")

    def _run_log_write(self, message: str):
        self._run_log.configure(state="normal")
        self._run_log.insert("end", message + "\n")
        self._run_log.see("end")
        self._run_log.configure(state="disabled")

    def _refresh_location_tree(self):
        for row in self._loc_tree.get_children():
            self._loc_tree.delete(row)
        for loc in self._locations:
            self._loc_tree.insert(
                "",
                "end",
                iid=str(loc["id"]),
                values=(
                    loc["id"],
                    "Depot" if loc.get("is_depot") else "Customer",
                    loc.get("name", ""),
                    loc.get("address", ""),
                    f"{loc.get('demand', 0.0):.2f}",
                    "Evet" if loc.get("selected") else "Hayir",
                    f"{loc['lat']:.5f}" if "lat" in loc else "-",
                    f"{loc['lon']:.5f}" if "lon" in loc else "-",
                ),
            )

    def _clear_location_form(self):
        self._loc_form_id = None
        self._loc_name_var.set("")
        self._loc_addr_var.set("")

    def _get_depot(self) -> dict:
        depot = next((loc for loc in self._locations if loc.get("is_depot")), None)
        if depot is None:
            depot = {
                "id": 0,
                "name": "Depot",
                "address": "",
                "is_depot": True,
                "selected": False,
                "demand": 0.0,
            }
            self._locations.insert(0, depot)
        return depot

    def _make_placeholder_locations(self, count: int) -> list[dict]:
        if count <= 0:
            return []

        rows = [
            {
                "id": 0,
                "name": "Depot",
                "address": "",
                "is_depot": True,
                "selected": False,
                "demand": 0.0,
            }
        ]
        for idx in range(1, count):
            rows.append(
                {
                    "id": idx,
                    "name": f"Customer {idx}",
                    "address": "",
                    "is_depot": False,
                    "selected": True,
                    "demand": 1.0,
                }
            )
        return rows

    def _load_depot_form(self):
        depot = self._get_depot()
        self._depot_name_var.set(depot.get("name", "Depot"))
        self._depot_addr_var.set(depot.get("address", ""))

    def _save_depot_form(self):
        depot = self._get_depot()
        depot_name = self._depot_name_var.get().strip() or "Depot"
        depot_address = self._depot_addr_var.get().strip()
        depot["name"] = depot_name
        depot["address"] = depot_address
        depot["is_depot"] = True
        depot["selected"] = False
        depot["demand"] = 0.0
        self._refresh_all_views()
        self._geo_log_write(f"Depot updated: {depot_name}")

    def _load_selected_location(self, _event=None):
        selection = self._loc_tree.selection()
        if not selection:
            return
        loc_id = int(selection[0])
        loc = self._locations[loc_id]
        if loc.get("is_depot"):
            self._load_depot_form()
            self._clear_location_form()
            self._geo_log_write("Depot selected. You can update its address from the left-side 'Depot Details' panel.")
            return
        self._loc_form_id = loc_id
        self._loc_name_var.set(loc.get("name", ""))
        self._loc_addr_var.set(loc.get("address", ""))

    def _add_location(self):
        name = self._loc_name_var.get().strip()
        address = self._loc_addr_var.get().strip()
        if not name:
            messagebox.showwarning("Warning", "Location name cannot be empty.")
            return

        self._locations.append(
            {
                "id": len(self._locations),
                "name": name,
                "address": address,
                "is_depot": False,
                "selected": True,
                "demand": 1.0,
            }
        )
        self._clear_location_form()
        self._refresh_all_views()
        self._geo_log_write(f"Location added: {name}")

    def _update_location(self):
        if self._loc_form_id is None:
            messagebox.showinfo("Info", "Select a location from the table to update it.")
            return

        loc = self._locations[self._loc_form_id]
        loc["name"] = self._loc_name_var.get().strip()
        loc["address"] = self._loc_addr_var.get().strip()
        loc["is_depot"] = False
        if not loc.get("selected"):
            loc["selected"] = True
        if loc.get("demand", 0.0) <= 0:
            loc["demand"] = 1.0
        self._clear_location_form()
        self._refresh_all_views()
        self._geo_log_write(f"Location updated: {loc['name']}")

    def _delete_selected_location(self):
        selection = self._loc_tree.selection()
        if not selection:
            return
        loc_id = int(selection[0])
        if self._locations[loc_id].get("is_depot"):
            messagebox.showwarning("Warning", "The depot cannot be deleted. You can update it instead.")
            return
        deleted = self._locations.pop(loc_id)
        self._refresh_all_views()
        self._geo_log_write(f"Location deleted: {deleted['name']}")

    def _project_payload(self) -> dict:
        return {
            "locations": self._locations,
            "fleet": self._fleet,
            "distance_matrix": self._dist_matrix,
            "time_matrix": self._time_matrix,
            "api_key": self._api_key_var.get(),
            "solver_key": self._solver_var.get() if hasattr(self, "_solver_var") else self._last_solver_key,
            "nsga_params": self._collect_solver_params(SolverKey.NSGA2) if hasattr(self, "_nsga_entries") else {},
            "bloodhound_params": self._collect_solver_params(SolverKey.BLOODHOUND) if hasattr(self, "_bloodhound_entries") else {},
        }

    def _write_project_file(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self._project_payload(), handle, ensure_ascii=False, indent=2)

    def _apply_project_data(self, data: dict) -> None:
        self._locations = data.get("locations", self._locations)
        self._fleet = data.get("fleet", self._fleet)
        self._dist_matrix = data.get("distance_matrix", self._dist_matrix)
        self._time_matrix = data.get("time_matrix", self._time_matrix)
        self._api_key_var.set(data.get("api_key", ""))
        if hasattr(self, "_solver_var"):
            self._solver_var.set(data.get("solver_key", self._solver_var.get()))
        if hasattr(self, "_nsga_entries"):
            for key, value in data.get("nsga_params", {}).items():
                if key in self._nsga_entries:
                    self._nsga_entries[key].delete(0, "end")
                    self._nsga_entries[key].insert(0, str(value))
        if hasattr(self, "_bloodhound_entries"):
            for key, value in data.get("bloodhound_params", {}).items():
                if key in self._bloodhound_entries:
                    self._bloodhound_entries[key].delete(0, "end")
                    self._bloodhound_entries[key].insert(0, str(value))
        self._clear_location_form()
        self._clear_fleet_form()
        self._refresh_all_views()

    def _save_autosave(self) -> None:
        self._write_project_file(AUTOSAVE_PATH)

    def _load_autosave(self) -> bool:
        if not os.path.exists(AUTOSAVE_PATH):
            return False
        try:
            with open(AUTOSAVE_PATH, encoding="utf-8") as handle:
                data = json.load(handle)
            self._apply_project_data(data)
            self._geo_log_write("Autosave restored.")
            return True
        except Exception:
            return False

    def _save_project(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="vrp_project.json")
        if not path:
            return
        self._write_project_file(path)
        messagebox.showinfo("Saved", path)

    def _load_project(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self._apply_project_data(data)
            self._geo_log_write(f"Project loaded: {path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _save_locations(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="locations.json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self._locations, handle, ensure_ascii=False, indent=2)
        messagebox.showinfo("Saved", path)

    def _load_locations(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                data = data.get("locations", [])
            self._locations = data
            self._refresh_all_views()
            self._geo_log_write(f"Locations loaded: {path}")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _import_locations_from_sheet(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Spreadsheet", "*.xlsx *.csv"),
                ("Excel Workbook", "*.xlsx"),
                ("CSV", "*.csv"),
            ]
        )
        if not path:
            return
        try:
            rows = _read_table_rows(path)
            imported = self._rows_to_location_records(rows)
            if not imported:
                messagebox.showwarning("Warning", "No valid customer rows were found in the selected file.")
                return
            next_id = max((loc["id"] for loc in self._locations), default=-1) + 1
            for offset, item in enumerate(imported):
                item["id"] = next_id + offset
            self._locations.extend(imported)
            self._clear_location_form()
            self._refresh_all_views()
            self._geo_log_write(f"Imported {len(imported)} customer locations from: {path}")
            messagebox.showinfo("Imported", f"{len(imported)} customer locations were added.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _rows_to_location_records(self, rows: list[list[str]]) -> list[dict]:
        if not rows:
            return []

        normalized_first = [cell.strip().lower() for cell in rows[0]]
        has_header = any(cell in {"name", "isim", "customer", "customer name", "address", "adres"} for cell in normalized_first)
        if has_header:
            name_idx = next((idx for idx, cell in enumerate(normalized_first) if cell in {"name", "isim", "customer", "customer name"}), 0)
            addr_idx = next((idx for idx, cell in enumerate(normalized_first) if cell in {"address", "adres", "location address"}), 1 if len(normalized_first) > 1 else 0)
            data_rows = rows[1:]
        else:
            name_idx = 0
            addr_idx = 1 if len(rows[0]) > 1 else 0
            data_rows = rows

        imported: list[dict] = []
        for row in data_rows:
            if not row:
                continue
            name = row[name_idx].strip() if name_idx < len(row) else ""
            address = row[addr_idx].strip() if addr_idx < len(row) else ""
            if not name and not address:
                continue
            if not name:
                name = f"Customer {len(imported) + 1}"
            imported.append(
                {
                    "id": 0,
                    "name": name,
                    "address": address,
                    "is_depot": False,
                    "selected": True,
                    "demand": 1.0,
                }
            )
        return imported

    def _start_geocoding(self):
        if self._geo_running:
            return
        api_key = self._api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("Error", "Google API key is required.")
            return
        missing = [loc for loc in self._locations if loc.get("address") and ("lat" not in loc or "lon" not in loc)]
        if not missing:
            messagebox.showinfo("Info", "There are no missing locations to geocode.")
            return
        self._geo_stop[0] = False
        self._geo_running = True
        self._btn_geocode.configure(state="disabled")
        self._btn_matrix.configure(state="disabled")
        self._btn_geo_stop.configure(state="normal")
        self._geo_log_write(f"Geocoding started ({len(missing)} locations).")
        threading.Thread(target=self._geocode_worker, args=(api_key,), daemon=True).start()

    def _geocode_worker(self, api_key: str):
        for loc in self._locations:
            if self._geo_stop[0]:
                self._queue.put(("geo_done", "geocode"))
                return
            if not loc.get("address") or ("lat" in loc and "lon" in loc):
                continue
            self._queue.put(("geo_log", f"Araniyor: {loc['name']}"))
            result = google_geocode(loc["address"], api_key)
            if result:
                loc["lat"], loc["lon"] = result
                self._queue.put(("geo_log", f"Found: {loc['name']} -> {result[0]:.5f}, {result[1]:.5f}"))
                self._queue.put(("refresh_all",))
            else:
                self._queue.put(("geo_log", f"Not found: {loc['name']}"))
        self._queue.put(("geo_done", "geocode"))

    def _start_matrix(self):
        if self._geo_running:
            return
        missing = [loc for loc in self._locations if "lat" not in loc or "lon" not in loc]
        if missing:
            messagebox.showwarning("Warning", "Coordinates are required for all locations.")
            return
        if len(self._locations) < 2:
            messagebox.showwarning("Warning", "At least a depot and 1 customer are required.")
            return
        self._geo_stop[0] = False
        self._geo_running = True
        self._btn_geocode.configure(state="disabled")
        self._btn_matrix.configure(state="disabled")
        self._btn_geo_stop.configure(state="normal")
        self._geo_log_write(f"OSRM matrix calculation started ({len(self._locations)}x{len(self._locations)}).")
        threading.Thread(target=self._matrix_worker, daemon=True).start()

    def _matrix_worker(self):
        n = len(self._locations)
        dist = [[0.0] * n for _ in range(n)]
        time_matrix = [[0.0] * n for _ in range(n)]
        total = n * n
        done = 0
        for i in range(n):
            for j in range(n):
                if self._geo_stop[0]:
                    self._queue.put(("geo_done", "matrix"))
                    return
                if i == j:
                    done += 1
                    continue
                lat1, lon1 = self._locations[i]["lat"], self._locations[i]["lon"]
                lat2, lon2 = self._locations[j]["lat"], self._locations[j]["lon"]
                dist_km, duration_min = osrm_route(lat1, lon1, lat2, lon2)
                if dist_km is None:
                    dist_km = haversine_km(lat1, lon1, lat2, lon2)
                if duration_min is None:
                    duration_min = (dist_km / FALLBACK_SPEED_KMH) * 60.0
                dist[i][j] = round(dist_km, 3)
                time_matrix[i][j] = round(duration_min, 3)
                done += 1
            self._queue.put(("geo_log", f"Matrix row {i + 1}/{n} completed (%{int(done / total * 100)})"))

        os.makedirs(RUNTIME_DATA_DIR, exist_ok=True)
        distance_path = os.path.join(RUNTIME_DATA_DIR, "distance_matrix.json")
        time_path = os.path.join(RUNTIME_DATA_DIR, "time_matrix.json")
        with open(distance_path, "w", encoding="utf-8") as handle:
            json.dump({"distance_matrix": dist}, handle, ensure_ascii=False, indent=2)
        with open(time_path, "w", encoding="utf-8") as handle:
            json.dump({"time_matrix": time_matrix}, handle, ensure_ascii=False, indent=2)

        self._queue.put(("matrix_ready", dist, time_matrix))
        self._queue.put(("geo_log", f"Distance matrix saved: {distance_path}"))
        self._queue.put(("geo_log", f"Time matrix saved: {time_path}"))
        self._queue.put(("geo_done", "matrix"))

    def _stop_geo(self):
        self._geo_stop[0] = True
        self._geo_log_write("Stop request sent.")

    def _refresh_customer_tab(self):
        for widget in self._cust_frame.winfo_children():
            widget.destroy()

        customers = [loc for loc in self._locations if not loc.get("is_depot")]
        self._customer_rows = []
        for column, minsize in ((0, 74), (1, 220), (2, 88), (3, 120)):
            self._cust_frame.grid_columnconfigure(column, minsize=minsize)
        for row_idx, loc in enumerate(customers):
            selected_var = tk.BooleanVar(value=bool(loc.get("selected", True)))
            demand_var = tk.StringVar(value=f"{float(loc.get('demand', 1.0)):.2f}")

            def on_change(*_args, location=loc, s_var=selected_var, d_var=demand_var):
                location["selected"] = bool(s_var.get())
                try:
                    location["demand"] = max(0.0, float(d_var.get()))
                except ValueError:
                    return
                self._refresh_run_summary()
                self._refresh_location_tree()

            selected_var.trace_add("write", on_change)
            demand_var.trace_add("write", on_change)

            row_bg = SURFACE if row_idx % 2 == 0 else PANEL
            tk.Label(
                self._cust_frame,
                text=f"ID {loc['id']}",
                bg=row_bg,
                fg=ACCENT2,
                width=8,
                anchor="w",
                font=("Segoe UI", 9, "bold"),
            ).grid(row=row_idx, column=0, padx=8, pady=4, sticky="ew")
            tk.Label(
                self._cust_frame,
                text=loc.get("name", ""),
                bg=row_bg,
                fg=TEXT,
                width=22,
                anchor="w",
                font=LABEL_FONT,
            ).grid(row=row_idx, column=1, padx=8, pady=4, sticky="ew")
            tk.Checkbutton(
                self._cust_frame,
                variable=selected_var,
                bg=row_bg,
                fg=TEXT,
                activebackground=row_bg,
                activeforeground=TEXT,
                selectcolor=SURFACE_ALT,
                highlightthickness=0,
            ).grid(row=row_idx, column=2, padx=8, pady=4)
            self._make_entry(self._cust_frame, textvariable=demand_var, width=10).grid(row=row_idx, column=3, padx=8, pady=4)
            self._customer_rows.append((selected_var, demand_var))

        selected_count = sum(1 for loc in customers if loc.get("selected"))
        self._cust_summary.configure(text=f"Selected customers: {selected_count} / {len(customers)}")

    def _select_all_customers(self):
        for loc in self._locations:
            if not loc.get("is_depot"):
                loc["selected"] = True
        self._refresh_all_views()

    def _deselect_all_customers(self):
        for loc in self._locations:
            if not loc.get("is_depot"):
                loc["selected"] = False
        self._refresh_all_views()

    def _clear_fleet_form(self):
        self._fleet_form_type_id = None
        self._fleet_vars["label"].set("")
        self._fleet_vars["count"].set("1")
        self._fleet_vars["capacity"].set("10")
        self._fleet_vars["fixed_cost"].set("45")
        self._fleet_vars["cost_per_km"].set("32")
        self._fleet_vars["speed_kmh"].set("35")

    def _fleet_payload_from_form(self) -> dict | None:
        try:
            return {
                "vehicle_type_id": self._fleet_form_type_id or f"vehicle-{len(self._fleet) + 1}",
                "label": self._fleet_vars["label"].get().strip() or "Yeni Arac",
                "count": int(self._fleet_vars["count"].get()),
                "capacity": float(self._fleet_vars["capacity"].get()),
                "fixed_cost": float(self._fleet_vars["fixed_cost"].get()),
                "cost_per_km": float(self._fleet_vars["cost_per_km"].get()),
                "speed_kmh": float(self._fleet_vars["speed_kmh"].get()),
            }
        except ValueError:
            messagebox.showerror("Error", "Fleet fields must contain valid numeric values.")
            return None

    def _add_fleet_unit(self):
        payload = self._fleet_payload_from_form()
        if payload is None:
            return
        self._fleet.append(payload)
        self._clear_fleet_form()
        self._refresh_all_views()

    def _load_selected_fleet(self, _event=None):
        selection = self._fleet_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        unit = self._fleet[idx]
        self._fleet_form_type_id = unit["vehicle_type_id"]
        for key, var in self._fleet_vars.items():
            var.set(str(unit[key]))

    def _update_fleet_unit(self):
        selection = self._fleet_tree.selection()
        if not selection:
            messagebox.showinfo("Info", "Select a fleet row to update it.")
            return
        payload = self._fleet_payload_from_form()
        if payload is None:
            return
        self._fleet[int(selection[0])] = payload
        self._clear_fleet_form()
        self._refresh_all_views()

    def _delete_selected_fleet(self):
        selection = self._fleet_tree.selection()
        if not selection:
            return
        idx = int(selection[0])
        deleted = self._fleet.pop(idx)
        self._clear_fleet_form()
        self._refresh_all_views()
        self._geo_log_write(f"Vehicle type deleted: {deleted['label']}")

    def _refresh_fleet_tree(self):
        for row in self._fleet_tree.get_children():
            self._fleet_tree.delete(row)
        for idx, unit in enumerate(self._fleet):
            self._fleet_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    unit["vehicle_type_id"],
                    unit["label"],
                    unit["count"],
                    unit["capacity"],
                    unit["fixed_cost"],
                    unit["cost_per_km"],
                    unit["speed_kmh"],
                ),
            )
        signatures = {
            (u["capacity"], u["fixed_cost"], u["cost_per_km"], u["speed_kmh"])
            for u in self._fleet
        }
        problem_type = "Homogeneous" if len(signatures) == 1 else "Heterogeneous"
        total_units = sum(u["count"] for u in self._fleet)
        self._fleet_summary.configure(text=f"Problem type: {problem_type} | Total vehicles: {total_units}")

    def _load_matrix_editors(self):
        self._dist_text.delete("1.0", "end")
        self._time_text.delete("1.0", "end")
        self._dist_text.insert("end", json.dumps(self._dist_matrix, indent=2))
        self._time_text.insert("end", json.dumps(self._time_matrix, indent=2))

    def _apply_matrices(self):
        try:
            dist = json.loads(self._dist_text.get("1.0", "end"))
            time_matrix = json.loads(self._time_text.get("1.0", "end"))
            n = len(self._locations)
            assert len(dist) == n and all(len(row) == n for row in dist), "Distance matrix size is invalid."
            assert len(time_matrix) == n and all(len(row) == n for row in time_matrix), "Time matrix size is invalid."
            self._dist_matrix = dist
            self._time_matrix = time_matrix
            messagebox.showinfo("Success", "Matrices applied.")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _resize_matrices_to_locations(self):
        self._normalize_locations_and_matrices()
        self._load_matrix_editors()
        messagebox.showinfo("Info", f"Matrix size updated to {len(self._locations)}x{len(self._locations)}.")

    def _save_matrices(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")], initialfile="matrices.json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"distance_matrix": self._dist_matrix, "time_matrix": self._time_matrix}, handle, ensure_ascii=False, indent=2)
        messagebox.showinfo("Saved", path)

    def _load_matrices_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            imported_locations = None
            dist_matrix = data.get("distance_matrix") or data.get("distance") or self._dist_matrix
            time_matrix = data.get("time_matrix") or data.get("time_matrix_minutes") or data.get("time") or self._time_matrix
            if isinstance(data, dict):
                imported_locations = data.get("locations")
                if imported_locations is None and data.get("depot") and data.get("customers"):
                    depot = dict(data.get("depot") or {})
                    depot.setdefault("is_depot", True)
                    depot.setdefault("selected", False)
                    depot.setdefault("demand", 0.0)
                    customers = []
                    for item in data.get("customers") or []:
                        row = dict(item)
                        row.setdefault("is_depot", False)
                        row.setdefault("selected", True)
                        row.setdefault("demand", 1.0)
                        customers.append(row)
                    imported_locations = [depot] + customers

            if not imported_locations and isinstance(dist_matrix, list) and dist_matrix:
                imported_locations = self._make_placeholder_locations(len(dist_matrix))

            if imported_locations:
                self._locations = imported_locations

            self._dist_matrix = dist_matrix
            self._time_matrix = time_matrix
            self._refresh_all_views()
            self._apply_matrices()
            self._load_matrix_editors()
            self._refresh_run_summary()
            self._geo_log_write(f"Matrix JSON loaded: {path}")
            self._geo_log_write(f"Loaded size: {len(self._dist_matrix)}x{len(self._dist_matrix)}")
            if imported_locations:
                self._geo_log_write(f"Locations loaded as well: {len(self._locations)} records")
            self._select_tab("matrix")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))

    def _load_matrices_from_json(self):
        self._load_matrices_file()

    def _refresh_run_summary(self):
        selected_count = sum(1 for loc in self._locations if not loc.get("is_depot") and loc.get("selected"))
        total_locations = len(self._locations)
        total_units = sum(unit["count"] for unit in self._fleet)
        signatures = {
            (u["capacity"], u["fixed_cost"], u["cost_per_km"], u["speed_kmh"])
            for u in self._fleet
        }
        problem_type = "Homogeneous" if len(signatures) == 1 else "Heterogeneous"
        self._run_summary.configure(
            text=(
                f"Total locations: {total_locations}\n"
                f"Selected customers: {selected_count}\n"
                f"Problem type: {problem_type}\n"
                f"Total vehicles: {total_units}\n"
                f"Solver: {self._solver_var.get() if hasattr(self, '_solver_var') else '-'}"
            )
        )
        if hasattr(self, "_solver_hint"):
            advisory = []
            if problem_type == "Heterogeneous":
                advisory.append("Bloodhound is required for heterogeneous fleets.")
            else:
                advisory.append("In homogeneous problems, vehicle count is adjusted by feasibility.")
            if selected_count > NSGA_WARNING_CUSTOMER_THRESHOLD and hasattr(self, "_solver_var") and self._solver_var.get() == SolverKey.NSGA2.value:
                advisory.append(
                    f"This problem size may exceed the recommended NSGA-II threshold ({selected_count} customers)."
                )
            self._solver_hint.configure(
                text=(
                    f"Available solvers: {self._solver_menu.cget('values') if hasattr(self, '_solver_menu') else '-'}\n"
                    + ("\n".join(advisory) if advisory else "The current selection is ready to run.")
                )
            )

    def _build_problem(self) -> VRPProblemData:
        selected_source_locations = [loc for loc in self._locations if loc.get("is_depot") or loc.get("selected")]
        source_indices = [loc["id"] for loc in selected_source_locations]

        locations = []
        demands = []
        for loc in selected_source_locations:
            locations.append(
                LocationRecord(
                    node_id=loc["id"],
                    name=loc.get("name", ""),
                    address=loc.get("address", ""),
                    lat=loc.get("lat"),
                    lon=loc.get("lon"),
                    is_depot=bool(loc.get("is_depot")),
                )
            )
            if not loc.get("is_depot"):
                demands.append(CustomerDemand(node_id=loc["id"], demand=float(loc.get("demand", 1.0))))

        fleet = [
            FleetUnit(
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

        solver_key = SolverKey(self._solver_var.get())
        sub_dist = [[self._dist_matrix[i][j] for j in source_indices] for i in source_indices]
        sub_time = [[self._time_matrix[i][j] for j in source_indices] for i in source_indices]
        return VRPProblemData(
            locations=locations,
            distance_matrix=sub_dist,
            time_matrix=sub_time,
            demands=demands,
            fleet=fleet,
            solver_config=SolverConfig(solver_key=solver_key, params=self._collect_solver_params(solver_key)),
        )

    def _collect_solver_params(self, solver_key: SolverKey) -> dict:
        if solver_key is SolverKey.NSGA2:
            return {
                "pop_size": int(self._nsga_entries["pop_size"].get()),
                "generations": int(self._nsga_entries["generations"].get()),
                "seed": int(self._nsga_entries["seed"].get()),
                "crossover_rate": float(self._nsga_entries["crossover_rate"].get()),
                "base_mutation": float(self._nsga_entries["base_mutation"].get()),
                "boost_mutation": float(self._nsga_entries["boost_mutation"].get()),
                "mutation_kind": self._nsga_entries["mutation_kind"].get().strip() or "inversion",
                "duplicate_penalty": float(self._nsga_entries["duplicate_penalty"].get()),
                "tournament_k": int(self._nsga_entries["tournament_k"].get()),
            }
        return {
            "num_wolves": int(self._bloodhound_entries["num_wolves"].get()),
            "num_hunts": int(self._bloodhound_entries["num_hunts"].get()),
            "explore_iterations": int(self._bloodhound_entries["explore_iterations"].get()),
            "reserve_blood": float(self._bloodhound_entries["reserve_blood"].get()),
            "lambda_reg": float(self._bloodhound_entries["lambda_reg"].get()),
            "a": float(self._bloodhound_entries["a"].get()),
            "b": float(self._bloodhound_entries["b"].get()),
            "c": float(self._bloodhound_entries["c"].get()),
            "b_par": float(self._bloodhound_entries["b_par"].get()),
            "inherit_frac": float(self._bloodhound_entries["inherit_frac"].get()),
            "ruin_frac": float(self._bloodhound_entries["ruin_frac"].get()),
            "rr_repeats": int(self._bloodhound_entries["rr_repeats"].get()),
            "verbose": self._bloodhound_entries["verbose"].get().strip().lower() in {"1", "true", "yes", "on"},
        }

    def _update_solver_choices(self):
        if not hasattr(self, "_solver_menu"):
            return
        try:
            problem = self._build_problem()
            supports = choose_available_solvers(problem)
            values = [item.solver_key.value for item in supports]
            self._solver_menu.configure(values=values)
            if self._solver_var.get() not in values:
                self._solver_var.set(values[0])
        except Exception:
            pass
        self._update_param_visibility()

    def _update_param_visibility(self):
        if not hasattr(self, "_nsga_card"):
            return
        solver = self._solver_var.get()
        if solver == SolverKey.NSGA2.value:
            self._nsga_card.pack(fill="x", pady=4)
            self._bloodhound_card.pack_forget()
        else:
            self._bloodhound_card.pack(fill="x", pady=4)
            self._nsga_card.pack_forget()
        self._refresh_run_summary()

    def _start_solve(self):
        if self._solve_running:
            return
        if sum(1 for loc in self._locations if not loc.get("is_depot") and loc.get("selected")) == 0:
            messagebox.showwarning("Warning", "At least one customer must be selected.")
            return
        try:
            problem = self._build_problem()
        except Exception as exc:
            messagebox.showerror("Error", str(exc))
            return

        self._solve_stop[0] = False
        self._solve_running = True
        self._last_solver_key = problem.solver_config.solver_key.value
        self._btn_run.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._prog_var.set(0)
        self._prog_lbl.configure(text="Running...")
        self._btn_run.configure(text="RUNNING...")
        self._run_log.configure(state="normal")
        self._run_log.delete("1.0", "end")
        self._run_log.configure(state="disabled")
        self._run_log_write(f"Solver started: {problem.solver_config.solver_key.value}")
        self._run_log_write(f"Selected customer count: {sum(1 for loc in self._locations if not loc.get('is_depot') and loc.get('selected'))}")
        self._run_log_write(f"Fleet type count: {len(self._fleet)}")

        self._solve_thread = threading.Thread(target=self._solve_worker, args=(problem,), daemon=True)
        self._solve_thread.start()

    def _stop_solve(self):
        self._solve_stop[0] = True
        self._run_log_write("Stop request sent.")

    def _solve_worker(self, problem: VRPProblemData):
        try:
            adapter = get_solver_adapter(problem.solver_config.solver_key)

            def progress_callback(payload: dict):
                self._queue.put(("solve_progress", payload))

            result = adapter.solve(problem, progress_callback=progress_callback, stop_flag=self._solve_stop)
            self._queue.put(("solve_done", result))
        except Exception as exc:
            self._queue.put(("solve_error", str(exc)))

    def _show_solver_result(self, result):
        self._last_solver_result = result
        self._result_solutions = result.solutions
        self._result_warnings = list(result.warnings)
        self._result_title.configure(text=f"{result.solver_key.value} | {len(result.solutions)} solutions")
        for row in self._result_tree.get_children():
            self._result_tree.delete(row)
        for idx, solution in enumerate(result.solutions, start=1):
            objective_text = ", ".join(f"{k}={v:.2f}" for k, v in solution.objectives.items())
            self._result_tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    solution.solution_id,
                    f"{solution.total_cost:.2f}",
                    objective_text,
                    len(solution.routes),
                    "Yes" if solution.feasible else "No",
                ),
            )
        total_routes = sum(len(solution.routes) for solution in result.solutions)
        feasible_count = sum(1 for solution in result.solutions if solution.feasible)
        best_cost = min((solution.total_cost for solution in result.solutions), default=0.0)
        self._result_summary.configure(
            text=(
                f"Solver: {result.solver_key.value.upper()}    "
                f"Problem: {result.problem_type.value.title()}    "
                f"Solutions: {len(result.solutions)}\n"
                f"Feasible solutions: {feasible_count}    "
                f"Total routes: {total_routes}    "
                f"Best total cost: {best_cost:.2f}"
            )
        )
        self._show_result_warnings()
        if result.solutions:
            self._result_tree.selection_set("1")
            self._show_selected_solution()

    def _save_results(self):
        if not self._last_solver_result or not self._result_solutions:
            messagebox.showwarning("Warning", "There are no results to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("Text", "*.txt")],
            initialfile="vrp_results.json",
        )
        if not path:
            return

        if path.endswith(".txt"):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"Solver: {self._last_solver_result.solver_key.value}\n")
                handle.write(f"Problem Type: {self._last_solver_result.problem_type.value}\n")
                handle.write(f"Warnings: {', '.join(self._result_warnings) if self._result_warnings else 'None'}\n\n")
                for solution in self._result_solutions:
                    handle.write(f"Solution: {solution.solution_id}\n")
                    handle.write(f"Total Cost: {solution.total_cost:.2f}\n")
                    for key, value in solution.objectives.items():
                        handle.write(f"  {key}: {value:.2f}\n")
                    for idx, route in enumerate(solution.routes, start=1):
                        handle.write(
                            f"  Route {idx}: vehicle={route.vehicle_label} nodes={route.nodes} "
                            f"dist={route.route_distance} time={route.route_time} "
                            f"fixed={route.fixed_cost} variable={route.variable_cost} cost={route.route_cost}\n"
                        )
                    handle.write("\n")
        else:
            export = {
                "solver_key": self._last_solver_result.solver_key.value,
                "problem_type": self._last_solver_result.problem_type.value,
                "objective_names": self._last_solver_result.objective_names,
                "warnings": self._result_warnings,
                "solutions": [],
            }
            for solution in self._result_solutions:
                export["solutions"].append(
                    {
                        "solution_id": solution.solution_id,
                        "objectives": solution.objectives,
                        "total_cost": solution.total_cost,
                        "feasible": solution.feasible,
                        "routes": [
                            {
                                "nodes": route.nodes,
                                "vehicle_label": route.vehicle_label,
                                "vehicle_type_id": route.vehicle_type_id,
                                "route_distance": route.route_distance,
                                "route_time": route.route_time,
                                "route_cost": route.route_cost,
                                "fixed_cost": route.fixed_cost,
                                "variable_cost": route.variable_cost,
                            }
                            for route in solution.routes
                        ],
                    }
                )
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(export, handle, ensure_ascii=False, indent=2)

        messagebox.showinfo("Saved", path)

    def _show_result_warnings(self):
        lines = self._result_warnings[:]
        if not lines and self._last_solver_result:
            if self._last_solver_result.solver_key is SolverKey.NSGA2:
                customer_count = sum(1 for loc in self._locations if not loc.get("is_depot") and loc.get("selected"))
                if customer_count > NSGA_WARNING_CUSTOMER_THRESHOLD:
                    lines.append(
                        f"NSGA-II ran with {customer_count} selected customers. Bloodhound may be more stable."
                    )
        if not lines:
            lines = ["No warnings."]
        self._result_warning_text.configure(state="normal")
        self._result_warning_text.delete("1.0", "end")
        self._result_warning_text.insert("end", "\n".join(lines))
        self._result_warning_text.configure(state="disabled")

    def _show_selected_solution(self, _event=None):
        selection = self._result_tree.selection()
        if not selection:
            return
        solution = self._result_solutions[int(selection[0]) - 1]
        location_names = {loc["id"]: loc.get("name", f"Node {loc['id']}") for loc in self._locations}
        total_fixed = sum((route.fixed_cost or 0.0) for route in solution.routes)
        total_variable = sum((route.variable_cost or 0.0) for route in solution.routes)
        total_distance = sum((route.route_distance or 0.0) for route in solution.routes)
        total_time = sum((route.route_time or 0.0) for route in solution.routes)
        lines = [
            f"Solution ID: {solution.solution_id}",
            f"Feasible: {'Yes' if solution.feasible else 'No'}",
            "",
            "Summary",
            f"Total Cost: {solution.total_cost:.2f}",
            f"Total Fixed Cost: {total_fixed:.2f}",
            f"Total Variable Cost: {total_variable:.2f}",
            f"Total Distance: {total_distance:.2f}",
            f"Total Time: {total_time:.2f}",
            f"Route Count: {len(solution.routes)}",
            "",
            "Objectives",
        ]
        for key, value in solution.objectives.items():
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value:.2f}")
        lines.append("")
        lines.append("Routes")
        for idx, route in enumerate(solution.routes, start=1):
            named_nodes = [location_names.get(node, str(node)) for node in route.nodes]
            stop_text = " -> ".join(named_nodes) if named_nodes else "No assigned customers"
            lines.extend(
                [
                    f"{idx}. Vehicle: {route.vehicle_label or '-'}",
                    f"Stops: Depot -> {stop_text} -> Depot",
                    f"Distance: {route.route_distance or 0:.2f} | Time: {route.route_time or 0:.2f} | Cost: {route.route_cost or 0:.2f}",
                    f"Fixed Cost: {route.fixed_cost or 0:.2f} | Variable Cost: {route.variable_cost or 0:.2f}",
                    "",
                ]
            )
        self._result_detail.configure(state="normal")
        self._result_detail.delete("1.0", "end")
        self._result_detail.insert("end", "\n".join(lines))
        self._result_detail.configure(state="disabled")
        self._route_view_title.configure(text=solution.solution_id)
        self._route_view_text.configure(state="normal")
        self._route_view_text.delete("1.0", "end")
        self._route_view_text.insert("end", "\n".join(lines))
        self._route_view_text.configure(state="disabled")

    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]
                if kind == "geo_log":
                    self._geo_log_write(item[1])
                elif kind == "refresh_all":
                    self._refresh_all_views()
                elif kind == "matrix_ready":
                    self._dist_matrix = item[1]
                    self._time_matrix = item[2]
                    self._load_matrix_editors()
                    self._refresh_run_summary()
                    self._geo_log_write("Matrices loaded into the app.")
                elif kind == "geo_done":
                    self._geo_running = False
                    self._btn_geocode.configure(state="normal")
                    self._btn_matrix.configure(state="normal")
                    self._btn_geo_stop.configure(state="disabled")
                    self._refresh_all_views()
                    self._geo_log_write(f"Operation completed: {item[1]}")
                elif kind == "solve_progress":
                    payload = item[1]
                    if payload.get("phase") == "evolution":
                        generation = payload.get("generation", 0)
                        total = max(1, int(self._nsga_entries["generations"].get()))
                        pct = min(100.0, generation / total * 100.0)
                        self._prog_var.set(pct)
                        self._prog_lbl.configure(text=f"Generation {generation}/{total}")
                        self._run_log_write(
                            f"Gen {generation} | rank1={payload.get('rank1_count')} | best={payload.get('best_cost'):.2f}"
                        )
                    elif payload.get("phase") == "bloodhound_log":
                        message = payload.get("message", "")
                        self._run_log_write(message)
                        if payload.get("current_hunt") and payload.get("total_hunts"):
                            current = int(payload["current_hunt"])
                            total = max(1, int(payload["total_hunts"]))
                            self._prog_var.set(min(100.0, current / total * 100.0))
                            self._prog_lbl.configure(text=f"Hunt {current}/{total}")
                    else:
                        self._prog_lbl.configure(text="Preparing...")
                        self._run_log_write(f"Progress: {payload}")
                elif kind == "solve_done":
                    result = item[1]
                    self._solve_running = False
                    self._btn_run.configure(state="normal")
                    self._btn_run.configure(text="START")
                    self._btn_stop.configure(state="disabled")
                    self._prog_var.set(100)
                    self._prog_lbl.configure(text="Completed")
                    self._run_log_write("Solver completed.")
                    if result.warnings:
                        for warning in result.warnings:
                            self._run_log_write(f"Warning: {warning}")
                    self._show_solver_result(result)
                    self._select_tab("results")
                elif kind == "solve_error":
                    self._solve_running = False
                    self._btn_run.configure(state="normal")
                    self._btn_run.configure(text="START")
                    self._btn_stop.configure(state="disabled")
                    self._prog_lbl.configure(text="Error")
                    self._run_log_write(f"Error: {item[1]}")
                    messagebox.showerror("Solve Error", item[1])
        except queue.Empty:
            pass
        self._after_id = self.after(100, self._poll_queue)

    def on_close(self):
        self._geo_stop[0] = True
        try:
            self._save_autosave()
        except Exception:
            pass
        if self._after_id is not None:
            self.after_cancel(self._after_id)
        self.destroy()


if __name__ == "__main__":
    app = VRPFinalApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
