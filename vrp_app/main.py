import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import queue
import json
import time
import math
import os
import urllib.parse
import urllib.request

from vrp_algorithm import run_nsga2
from default_data import DEFAULT_DISTANCE_MATRIX, DEFAULT_TIME_MATRIX

# ─── Renkler ──────────────────────────────────────────────────────────────────
BG        = "#1e1e2e"
PANEL     = "#2a2a3e"
ACCENT    = "#7c3aed"
ACCENT2   = "#a78bfa"
SUCCESS   = "#22c55e"
WARNING   = "#f59e0b"
DANGER    = "#ef4444"
TEXT      = "#e2e8f0"
TEXT_DIM  = "#94a3b8"
BORDER    = "#3f3f5a"
LOG_BG    = "#12121c"
LOG_FG    = "#a0f0a0"

FALLBACK_SPEED_KMH = 35.0
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ──────────────────────────────────────────────────────────────────────────────
# Geocoding + OSRM yardimci fonksiyonlar
# ──────────────────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2)
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def google_geocode(address: str, api_key: str):
    """Adres → (lat, lon) veya None. Oncelikle dener, sonra Ankara ekler."""
    candidates = [address.strip()]
    if "ankara" not in address.lower():
        candidates.append(address.strip() + ", Ankara, Turkiye")

    for query in candidates:
        params = {"address": query, "key": api_key,
                  "region": "tr", "components": "country:TR"}
        url = GOOGLE_GEOCODE_URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "VRP-App/2.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                obj = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        if obj.get("status") != "OK":
            continue
        results = obj.get("results") or []
        if not results:
            continue
        loc = results[0].get("geometry", {}).get("location", {})
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is not None and lng is not None:
            time.sleep(0.2)
            return float(lat), float(lng)
    return None


def osrm_route(lat1, lon1, lat2, lon2):
    """OSRM ile yol mesafesi (km) ve sure (dk). Basarisizsa None, None."""
    url = (f"https://router.project-osrm.org/route/v1/driving/"
           f"{lon1},{lat1};{lon2},{lat2}?overview=false")
    req = urllib.request.Request(url, headers={"User-Agent": "VRP-App/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            obj = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None, None
    if obj.get("code") != "Ok":
        return None, None
    routes = obj.get("routes") or []
    if not routes:
        return None, None
    dm = routes[0].get("distance")
    ds = routes[0].get("duration")
    if dm is None:
        return None, None
    time.sleep(0.15)
    return round(dm / 1000.0, 3), (None if ds is None else round(ds / 60.0, 3))


# ──────────────────────────────────────────────────────────────────────────────
# Ana Uygulama
# ──────────────────────────────────────────────────────────────────────────────

class VRPApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VRP - NSGA-II Optimizer")
        self.geometry("1200x820")
        self.minsize(1000, 680)
        self.configure(bg=BG)

        # --- VRP state ---
        self._queue      = queue.Queue()
        self._stop       = [False]
        self._running    = False
        self._thread     = None
        self._dist_matrix    = [row[:] for row in DEFAULT_DISTANCE_MATRIX]
        self._time_matrix    = [row[:] for row in DEFAULT_TIME_MATRIX]
        self._cust_vars      = []
        self._result_node_map = []
        self._results_data   = []

        # --- Lokasyon state ---
        self._locations  = []          # [{"id":0,"name":"Depo","address":"...","lat":..,"lon":..}, ...]
        self._geo_stop   = [False]
        self._geo_running = False

        self._build_ui()
        self._refresh_customer_tab()
        self._after_id = self.after(100, self._poll_queue)

    # =========================================================================
    # UI ISKELET
    # =========================================================================
    def _build_ui(self):
        hdr = tk.Frame(self, bg=ACCENT, height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="VRP - NSGA-II Multi-Objective Optimizer",
                 font=("Segoe UI", 14, "bold"), bg=ACCENT, fg="white"
                 ).pack(side="left", padx=18, pady=12)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook",     background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=TEXT_DIM,
                        padding=[13, 7], font=("Segoe UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", "white")])

        self._nb = ttk.Notebook(self)
        self._nb.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self._tab_loc     = tk.Frame(self._nb, bg=BG)
        self._tab_cust    = tk.Frame(self._nb, bg=BG)
        self._tab_run     = tk.Frame(self._nb, bg=BG)
        self._tab_matrix  = tk.Frame(self._nb, bg=BG)
        self._tab_results = tk.Frame(self._nb, bg=BG)

        self._nb.add(self._tab_loc,     text="Lokasyonlar")
        self._nb.add(self._tab_cust,    text="Musteri Secimi")
        self._nb.add(self._tab_run,     text="Calistir")
        self._nb.add(self._tab_matrix,  text="Matrisler")
        self._nb.add(self._tab_results, text="Sonuclar")

        self._build_location_tab()
        self._build_customer_tab()
        self._build_run_tab()
        self._build_matrix_tab()
        self._build_results_tab()

    # =========================================================================
    # LOKASYONlar SEKMESI
    # =========================================================================
    def _build_location_tab(self):
        p = self._tab_loc

        # ── Sol panel: kontroller ──────────────────────────────────────────
        left = tk.Frame(p, bg=BG, width=310)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        left.pack_propagate(False)

        # API Key
        api_card = self._card(left, "Google API Key")
        self._api_key_var = tk.StringVar()
        tk.Entry(api_card, textvariable=self._api_key_var,
                 font=("Segoe UI", 9), bg=BG, fg=TEXT,
                 insertbackground=TEXT, relief="flat", bd=4, show="*"
                 ).pack(fill="x", pady=(0, 4))
        tk.Button(api_card, text="Goster / Gizle",
                  font=("Segoe UI", 8), bg=PANEL, fg=TEXT_DIM,
                  relief="flat", bd=0, cursor="hand2",
                  command=self._toggle_api_key).pack(anchor="w")

        # Yeni lokasyon ekle
        add_card = self._card(left, "Yeni Lokasyon Ekle")
        for lbl, attr in [("Ad / Isim", "_new_name"), ("Adres", "_new_addr")]:
            tk.Label(add_card, text=lbl, font=("Segoe UI", 8),
                     bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
            e = tk.Entry(add_card, font=("Segoe UI", 9), bg=BG, fg=TEXT,
                         insertbackground=TEXT, relief="flat", bd=4)
            e.pack(fill="x", pady=(0, 4))
            setattr(self, attr, e)
        tk.Button(add_card, text="Ekle",
                  font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white",
                  relief="flat", bd=0, pady=6, cursor="hand2",
                  command=self._add_location).pack(fill="x")

        # Dosya islemleri
        file_card = self._card(left, "Dosya Islemleri")
        for txt, cmd in [
            ("locations.json Yukle",  self._load_locations_file),
            ("locations.json Kaydet", self._save_locations_file),
            ("Matrisleri JSON'dan Yukle", self._load_matrices_from_json),
        ]:
            tk.Button(file_card, text=txt,
                      font=("Segoe UI", 9), bg=PANEL, fg=TEXT,
                      activebackground=BORDER, relief="flat", bd=0,
                      pady=6, cursor="hand2", command=cmd).pack(fill="x", pady=2)

        # Geocoding / Matris butonlari
        geo_card = self._card(left, "Geocoding + Matris")
        self._btn_geocode = tk.Button(geo_card,
                  text="Koordinatlari Bul (Google)",
                  font=("Segoe UI", 9, "bold"), bg=WARNING, fg="white",
                  relief="flat", bd=0, pady=7, cursor="hand2",
                  command=self._start_geocoding)
        self._btn_geocode.pack(fill="x", pady=(0, 4))

        self._btn_matrix = tk.Button(geo_card,
                  text="Mesafe + Zaman Matrisi Hesapla (OSRM)",
                  font=("Segoe UI", 9, "bold"), bg=ACCENT, fg="white",
                  relief="flat", bd=0, pady=7, cursor="hand2",
                  command=self._start_matrix)
        self._btn_matrix.pack(fill="x", pady=(0, 4))

        self._btn_geo_stop = tk.Button(geo_card,
                  text="Durdur",
                  font=("Segoe UI", 9), bg=DANGER, fg="white",
                  relief="flat", bd=0, pady=5, cursor="hand2",
                  state="disabled", command=self._stop_geo)
        self._btn_geo_stop.pack(fill="x")

        # ── Sag panel: tablo + log ─────────────────────────────────────────
        right = tk.Frame(p, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)

        # Lokasyon tablosu
        tk.Label(right, text="Lokasyon Listesi",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w")

        loc_cols = ("ID", "Ad", "Adres", "Lat", "Lon", "Durum")
        style = ttk.Style()
        style.configure("loc.Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=24, font=("Segoe UI", 9))
        style.configure("loc.Treeview.Heading", background=ACCENT, foreground="white",
                        font=("Segoe UI", 9, "bold"))
        style.map("loc.Treeview", background=[("selected", ACCENT2)])

        tree_f = tk.Frame(right, bg=BG)
        tree_f.pack(fill="x", pady=(4, 0))

        self._loc_tree = ttk.Treeview(tree_f, columns=loc_cols,
                                       show="headings", height=10,
                                       style="loc.Treeview")
        for col, w in zip(loc_cols, [40, 150, 260, 90, 90, 80]):
            self._loc_tree.heading(col, text=col)
            self._loc_tree.column(col, width=w, anchor="center")

        vsb = ttk.Scrollbar(tree_f, orient="vertical", command=self._loc_tree.yview)
        self._loc_tree.configure(yscrollcommand=vsb.set)
        self._loc_tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")

        # Secili satiri sil butonu
        tk.Button(right, text="Secili Lokasyonu Sil",
                  font=("Segoe UI", 9), bg=DANGER, fg="white",
                  relief="flat", bd=0, padx=12, pady=5, cursor="hand2",
                  command=self._delete_selected_location).pack(anchor="w", pady=(4, 0))

        # Geocoding logu
        tk.Label(right, text="Islem Logu",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT
                 ).pack(anchor="w", pady=(10, 2))
        self._geo_log = scrolledtext.ScrolledText(
            right, font=("Consolas", 8), bg=LOG_BG, fg=LOG_FG,
            insertbackground=LOG_FG, relief="flat", bd=4,
            state="disabled", height=8)
        self._geo_log.pack(fill="both", expand=True)

    # ── Lokasyon yardimcilari ──────────────────────────────────────────────

    def _toggle_api_key(self):
        entries = [w for w in self._tab_loc.winfo_children()]
        # entry widget'i bul
        for w in self._tab_loc.winfo_descendants():
            if isinstance(w, tk.Entry) and w.cget("show") in ("*", ""):
                w.configure(show="" if w.cget("show") == "*" else "*")
                break

    def _geo_log_write(self, msg):
        self._geo_log.configure(state="normal")
        self._geo_log.insert("end", msg + "\n")
        self._geo_log.see("end")
        self._geo_log.configure(state="disabled")

    def _refresh_loc_tree(self):
        for row in self._loc_tree.get_children():
            self._loc_tree.delete(row)
        for loc in self._locations:
            has_coords = "lat" in loc and "lon" in loc
            durum = "OK" if has_coords else "Eksik"
            self._loc_tree.insert("", "end", values=(
                loc.get("id", ""),
                loc.get("name", ""),
                loc.get("address", ""),
                f"{loc['lat']:.5f}" if has_coords else "-",
                f"{loc['lon']:.5f}" if has_coords else "-",
                durum,
            ))

    def _add_location(self):
        name = self._new_name.get().strip()
        addr = self._new_addr.get().strip()
        if not name or not addr:
            messagebox.showwarning("Uyari", "Ad ve adres bos olamaz!")
            return
        new_id = max((loc.get("id", 0) for loc in self._locations), default=-1) + 1
        self._locations.append({"id": new_id, "name": name, "address": addr})
        self._new_name.delete(0, "end")
        self._new_addr.delete(0, "end")
        self._refresh_loc_tree()
        self._geo_log_write(f"Eklendi: ID {new_id} | {name}")

    def _delete_selected_location(self):
        sel = self._loc_tree.selection()
        if not sel:
            return
        vals = self._loc_tree.item(sel[0])["values"]
        loc_id = vals[0]
        self._locations = [l for l in self._locations if l.get("id") != loc_id]
        # ID'leri yeniden sirala (depo=0 sabit kalsin)
        self._refresh_loc_tree()
        self._geo_log_write(f"Silindi: ID {loc_id}")

    def _load_locations_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self._locations = data
            self._refresh_loc_tree()
            self._geo_log_write(f"Yuklendi: {len(data)} lokasyon ({path})")
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _save_locations_file(self):
        if not self._locations:
            messagebox.showwarning("Uyari", "Lokasyon listesi bos!")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile="locations.json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._locations, f, ensure_ascii=False, indent=2)
        messagebox.showinfo("Kaydedildi", path)

    def _load_matrices_from_json(self):
        """distance_matrix.json + time_matrix.json yukle, matrisleri guncelle."""
        dist_path = filedialog.askopenfilename(
            title="distance_matrix.json sec",
            filetypes=[("JSON", "*.json")])
        if not dist_path:
            return
        time_path = filedialog.askopenfilename(
            title="time_matrix.json sec",
            filetypes=[("JSON", "*.json")])
        if not time_path:
            return
        try:
            with open(dist_path, encoding="utf-8") as f:
                d_obj = json.load(f)
            with open(time_path, encoding="utf-8") as f:
                t_obj = json.load(f)

            dist = d_obj.get("distance_matrix") or d_obj
            time_mat = t_obj.get("time_matrix_minutes") or t_obj

            n = len(dist)
            assert all(len(r) == n for r in dist), "Mesafe matrisi kare degil"
            assert len(time_mat) == n, "Zaman matrisi boyutu uyusmuyor"

            self._dist_matrix = dist
            self._time_matrix = time_mat
            self._refresh_customer_tab()
            self._load_matrix_editors()
            messagebox.showinfo("Basarili",
                f"Matrisler yuklendi: {n}x{n}\nMusteri Secimi sekmesi guncellendi.")
            self._nb.select(self._tab_cust)
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    # ── Geocoding worker ──────────────────────────────────────────────────

    def _start_geocoding(self):
        if self._geo_running:
            return
        api_key = self._api_key_var.get().strip()
        if not api_key:
            messagebox.showerror("Hata", "Lutfen Google API Key girin!")
            return
        missing = [l for l in self._locations if "lat" not in l or "lon" not in l]
        if not missing:
            messagebox.showinfo("Bilgi", "Tum lokasyonlarin koordinati mevcut.")
            return
        self._geo_stop[0] = False
        self._geo_running = True
        self._btn_geocode.configure(state="disabled")
        self._btn_matrix.configure(state="disabled")
        self._btn_geo_stop.configure(state="normal")
        self._geo_log_write(f"\nGeocoding basliyor... ({len(missing)} eksik)")
        threading.Thread(target=self._geocode_worker,
                         args=(api_key,), daemon=True).start()

    def _geocode_worker(self, api_key):
        for loc in self._locations:
            if self._geo_stop[0]:
                self._queue.put(("geo_log", "Durduruldu."))
                break
            if "lat" in loc and "lon" in loc:
                continue
            addr = loc.get("address", "")
            self._queue.put(("geo_log", f"Araniyor: ID {loc['id']} | {loc['name']} | {addr}"))
            result = google_geocode(addr, api_key)
            if result:
                loc["lat"], loc["lon"] = result
                self._queue.put(("geo_log", f"  Bulundu: {result[0]:.5f}, {result[1]:.5f}"))
                self._queue.put(("geo_refresh",))
            else:
                self._queue.put(("geo_log", f"  BULUNAMADI: {addr}"))
        self._queue.put(("geo_done", "geocode"))

    # ── Matrix worker ──────────────────────────────────────────────────────

    def _start_matrix(self):
        if self._geo_running:
            return
        missing_coords = [l for l in self._locations if "lat" not in l or "lon" not in l]
        if missing_coords:
            messagebox.showwarning("Uyari",
                f"{len(missing_coords)} lokasyonun koordinati eksik!\n"
                "Once 'Koordinatlari Bul' calistirin.")
            return
        if len(self._locations) < 2:
            messagebox.showwarning("Uyari", "En az 2 lokasyon gerekli (depo + 1 musteri).")
            return
        self._geo_stop[0] = False
        self._geo_running = True
        self._btn_geocode.configure(state="disabled")
        self._btn_matrix.configure(state="disabled")
        self._btn_geo_stop.configure(state="normal")
        n = len(self._locations)
        self._geo_log_write(f"\nOSRM matris hesaplaniyor... ({n}x{n} = {n*n} cift)")
        threading.Thread(target=self._matrix_worker, daemon=True).start()

    def _matrix_worker(self):
        locs = self._locations
        n = len(locs)
        dist_mat = [[0.0]*n for _ in range(n)]
        time_mat = [[0.0]*n for _ in range(n)]

        total = n * n
        done  = 0

        for i in range(n):
            for j in range(n):
                if self._geo_stop[0]:
                    self._queue.put(("geo_log", "Durduruldu."))
                    self._queue.put(("geo_done", "matrix_partial"))
                    return
                if i == j:
                    done += 1
                    continue
                lat1, lon1 = locs[i]["lat"], locs[i]["lon"]
                lat2, lon2 = locs[j]["lat"], locs[j]["lon"]
                dk, tm = osrm_route(lat1, lon1, lat2, lon2)
                if dk is None:
                    dk = haversine_km(lat1, lon1, lat2, lon2)
                if tm is None:
                    tm = (dk / FALLBACK_SPEED_KMH) * 60.0
                dist_mat[i][j] = round(dk, 3)
                time_mat[i][j] = round(tm, 3)
                done += 1

            pct = int(done / total * 100)
            self._queue.put(("geo_log", f"  Satir {i+1}/{n} tamamlandi (%{pct})"))

        # Matrisleri kaydet
        ids = [l.get("id") for l in locs]
        dist_path = os.path.join(BASE_DIR, "distance_matrix.json")
        time_path = os.path.join(BASE_DIR, "time_matrix.json")
        with open(dist_path, "w", encoding="utf-8") as f:
            json.dump({"ids": ids, "distance_matrix": dist_mat}, f, indent=2)
        with open(time_path, "w", encoding="utf-8") as f:
            json.dump({"ids": ids, "time_matrix_minutes": time_mat}, f, indent=2)

        self._queue.put(("geo_log", f"Kaydedildi: {dist_path}"))
        self._queue.put(("geo_log", f"Kaydedildi: {time_path}"))
        self._queue.put(("matrix_ready", dist_mat, time_mat))
        self._queue.put(("geo_done", "matrix"))

    def _stop_geo(self):
        self._geo_stop[0] = True

    # =========================================================================
    # MUSTERI SECIMI SEKMESI
    # =========================================================================
    def _build_customer_tab(self):
        p = self._tab_cust

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(top,
                 text="Optimize edilecek musteri ID'lerini secin  (ID 0 = Depo, her zaman dahil)",
                 font=("Segoe UI", 10), bg=BG, fg=TEXT_DIM).pack(side="left")

        btn_f = tk.Frame(top, bg=BG)
        btn_f.pack(side="right")
        tk.Button(btn_f, text="Tumunu Sec",    font=("Segoe UI", 9), bg=ACCENT, fg="white",
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                  command=self._select_all).pack(side="left", padx=4)
        tk.Button(btn_f, text="Tumunu Kaldir", font=("Segoe UI", 9), bg=PANEL, fg=TEXT,
                  relief="flat", bd=0, padx=10, pady=4, cursor="hand2",
                  command=self._deselect_all).pack(side="left", padx=4)

        self._sel_label = tk.Label(p, text="", font=("Segoe UI", 9, "bold"),
                                   bg=BG, fg=ACCENT2)
        self._sel_label.pack(anchor="w", padx=14, pady=(0, 4))

        outer = tk.Frame(p, bg=PANEL)
        outer.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        self._canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._cb_frame = tk.Frame(self._canvas, bg=PANEL)
        self._cb_window = self._canvas.create_window((0, 0), window=self._cb_frame, anchor="nw")
        self._cb_frame.bind("<Configure>",
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox("all")))
        self._canvas.bind("<Configure>",
            lambda e: self._canvas.itemconfig(self._cb_window, width=e.width))
        self._canvas.bind("<MouseWheel>",
            lambda e: self._canvas.yview_scroll(-1*(e.delta//120), "units"))

    def _refresh_customer_tab(self):
        n = len(self._dist_matrix) - 1
        for w in self._cb_frame.winfo_children():
            w.destroy()

        prev = {i + 1 for i, v in enumerate(self._cust_vars) if v.get()}
        self._cust_vars = []

        tk.Label(self._cb_frame,
                 text="  ID 0  -  DEPO (her zaman dahil)",
                 font=("Segoe UI", 9, "italic"), bg=PANEL, fg=TEXT_DIM,
                 anchor="w").grid(row=0, column=0, columnspan=6,
                                   sticky="w", padx=8, pady=(6, 2))
        cols = 6
        for cid in range(1, n + 1):
            # Lokasyon listesinden isim bul
            loc_name = ""
            if self._locations:
                match = next((l for l in self._locations if l.get("id") == cid), None)
                if match:
                    loc_name = f" {match.get('name','')}"

            var = tk.BooleanVar(value=(cid in prev) if prev else True)
            var.trace_add("write", lambda *a: self._update_sel_label())
            self._cust_vars.append(var)

            r = 1 + (cid - 1) // cols
            c = (cid - 1) % cols

            tk.Checkbutton(self._cb_frame,
                           text=f"ID {cid}{loc_name}",
                           variable=var,
                           font=("Segoe UI", 9),
                           bg=PANEL, fg=TEXT,
                           selectcolor=ACCENT,
                           activebackground=PANEL,
                           activeforeground=TEXT,
                           cursor="hand2"
                           ).grid(row=r, column=c, padx=10, pady=4, sticky="w")

        self._update_sel_label()

    def _update_sel_label(self):
        sel = [i+1 for i, v in enumerate(self._cust_vars) if v.get()]
        self._sel_label.configure(
            text=f"Secili: {len(sel)} / {len(self._cust_vars)} musteri  "
                 f"|  Toplam node (depo dahil): {len(sel)+1}")

    def _select_all(self):
        for v in self._cust_vars: v.set(True)

    def _deselect_all(self):
        for v in self._cust_vars: v.set(False)

    def _get_selected_nodes(self):
        return [0] + sorted([i+1 for i, v in enumerate(self._cust_vars) if v.get()])

    def _build_submatrix(self, nodes):
        sub_dist = [[self._dist_matrix[i][j] for j in nodes] for i in nodes]
        sub_time = [[self._time_matrix[i][j] for j in nodes] for i in nodes]
        return sub_dist, sub_time

    # =========================================================================
    # CALISTIR SEKMESI
    # =========================================================================
    def _build_run_tab(self):
        p = self._tab_run
        left  = tk.Frame(p, bg=BG, width=280)
        right = tk.Frame(p, bg=BG)
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        left.pack_propagate(False)

        card = self._card(left, "Parametreler")
        self._entries = {}
        for label, key, default in [
            ("Populasyon Buyuklugu", "pop_size",    "60"),
            ("Nesil Sayisi",         "generations", "500"),
            ("Seed",                 "seed",        "0"),
        ]:
            row = tk.Frame(card, bg=PANEL)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=("Segoe UI", 9), bg=PANEL,
                     fg=TEXT_DIM, width=22, anchor="w").pack(side="left")
            e = tk.Entry(row, font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT,
                         insertbackground=TEXT, relief="flat", bd=4, width=8)
            e.insert(0, default)
            e.pack(side="right")
            self._entries[key] = e

        btn_f = tk.Frame(left, bg=BG)
        btn_f.pack(fill="x", pady=(10, 0))

        self._btn_run = tk.Button(btn_f, text="BASLAT",
                                  font=("Segoe UI", 11, "bold"),
                                  bg=SUCCESS, fg="white",
                                  relief="flat", bd=0, pady=10, cursor="hand2",
                                  command=self._start)
        self._btn_run.pack(fill="x", pady=4)

        self._btn_stop = tk.Button(btn_f, text="DURDUR",
                                   font=("Segoe UI", 11, "bold"),
                                   bg=DANGER, fg="white",
                                   relief="flat", bd=0, pady=10, cursor="hand2",
                                   state="disabled", command=self._stop_run)
        self._btn_stop.pack(fill="x", pady=4)

        tk.Button(btn_f, text="Logu Temizle",
                  font=("Segoe UI", 9), bg=PANEL, fg=TEXT_DIM,
                  relief="flat", bd=0, pady=6, cursor="hand2",
                  command=self._clear_log).pack(fill="x", pady=4)

        self._prog_var = tk.DoubleVar()
        self._prog_lbl = tk.Label(left, text="Hazir", font=("Segoe UI", 9),
                                  bg=BG, fg=TEXT_DIM)
        self._prog_lbl.pack(pady=(12, 2))
        ttk.Style().configure("g.Horizontal.TProgressbar",
                              troughcolor=PANEL, background=ACCENT)
        ttk.Progressbar(left, variable=self._prog_var,
                        style="g.Horizontal.TProgressbar",
                        maximum=100).pack(fill="x", padx=4)

        tk.Label(right, text="Calisma Gunlugu",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT).pack(anchor="w")
        self._log = scrolledtext.ScrolledText(
            right, font=("Consolas", 9), bg=LOG_BG, fg=LOG_FG,
            insertbackground=LOG_FG, relief="flat", bd=4,
            state="disabled", wrap="none")
        self._log.pack(fill="both", expand=True, pady=(4, 0))

    # =========================================================================
    # MATRIS SEKMESI
    # =========================================================================
    def _build_matrix_tab(self):
        p = self._tab_matrix
        tk.Label(p, bg=BG, fg=TEXT_DIM, font=("Segoe UI", 9),
                 text="Mesafe ve zaman matrislerini JSON formatinda goruntuleyebilir/duzenleyebilirsiniz."
                 ).pack(anchor="w", padx=12, pady=(8, 4))

        tab_row = tk.Frame(p, bg=BG)
        tab_row.pack(fill="x", padx=12)

        self._mat_dist_frame = tk.Frame(p, bg=BG)
        self._mat_time_frame = tk.Frame(p, bg=BG)

        self._dist_text = scrolledtext.ScrolledText(
            self._mat_dist_frame, font=("Consolas", 8), bg=LOG_BG, fg="#c9d1d9",
            insertbackground="white", relief="flat", bd=4)
        self._dist_text.pack(fill="both", expand=True, padx=6, pady=6)

        self._time_text = scrolledtext.ScrolledText(
            self._mat_time_frame, font=("Consolas", 8), bg=LOG_BG, fg="#c9d1d9",
            insertbackground="white", relief="flat", bd=4)
        self._time_text.pack(fill="both", expand=True, padx=6, pady=6)

        self._btn_mt_dist = tk.Button(tab_row, text="Mesafe Matrisi",
                  font=("Segoe UI", 10, "bold"), bg=ACCENT, fg="white",
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._show_dist_tab)
        self._btn_mt_dist.pack(side="left", padx=(0, 4))

        self._btn_mt_time = tk.Button(tab_row, text="Zaman Matrisi",
                  font=("Segoe UI", 10), bg=PANEL, fg=TEXT,
                  relief="flat", bd=0, padx=14, pady=6, cursor="hand2",
                  command=self._show_time_tab)
        self._btn_mt_time.pack(side="left")

        self._mat_dist_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self._load_matrix_editors()

        btn_row = tk.Frame(p, bg=BG)
        btn_row.pack(fill="x", padx=12, pady=(4, 8))
        for txt, cmd, col in [
            ("Uygula",               self._apply_matrices,    SUCCESS),
            ("Varsayilana Sifirla",   self._reset_matrices,    PANEL),
            ("JSON Kaydet",           self._save_matrices,     PANEL),
            ("JSON Yukle",            self._load_matrices_file, PANEL),
        ]:
            tk.Button(btn_row, text=txt, font=("Segoe UI", 10), bg=col,
                      fg="white", relief="flat", bd=0, padx=16, pady=7,
                      cursor="hand2", command=cmd).pack(side="left", padx=(0, 6))

    def _show_dist_tab(self):
        self._mat_time_frame.pack_forget()
        self._mat_dist_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self._btn_mt_dist.configure(bg=ACCENT, font=("Segoe UI", 10, "bold"))
        self._btn_mt_time.configure(bg=PANEL,  font=("Segoe UI", 10))

    def _show_time_tab(self):
        self._mat_dist_frame.pack_forget()
        self._mat_time_frame.pack(fill="both", expand=True, padx=12, pady=(4, 0))
        self._btn_mt_time.configure(bg=ACCENT, font=("Segoe UI", 10, "bold"))
        self._btn_mt_dist.configure(bg=PANEL,  font=("Segoe UI", 10))

    def _load_matrix_editors(self):
        self._dist_text.delete("1.0", "end")
        self._dist_text.insert("end", json.dumps(self._dist_matrix, indent=2))
        self._time_text.delete("1.0", "end")
        self._time_text.insert("end", json.dumps(self._time_matrix, indent=2))

    def _apply_matrices(self):
        try:
            d = json.loads(self._dist_text.get("1.0", "end"))
            t = json.loads(self._time_text.get("1.0", "end"))
            n = len(d)
            assert all(len(r) == n for r in d), "Mesafe matrisi kare degil!"
            assert len(t) == n and all(len(r) == n for r in t), "Zaman matrisi uyusmuyor!"
            self._dist_matrix = d
            self._time_matrix = t
            self._refresh_customer_tab()
            messagebox.showinfo("Basarili", f"Matrisler guncellendi ({n}x{n})")
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    def _reset_matrices(self):
        self._dist_matrix = [row[:] for row in DEFAULT_DISTANCE_MATRIX]
        self._time_matrix = [row[:] for row in DEFAULT_TIME_MATRIX]
        self._load_matrix_editors()
        self._refresh_customer_tab()

    def _save_matrices(self):
        path = filedialog.asksaveasfilename(defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if path:
            with open(path, "w") as f:
                json.dump({"distance": self._dist_matrix, "time": self._time_matrix}, f, indent=2)
            messagebox.showinfo("Kaydedildi", path)

    def _load_matrices_file(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
            self._dist_matrix = data.get("distance") or data.get("distance_matrix") or data
            self._time_matrix = data.get("time") or data.get("time_matrix_minutes") or data
            self._load_matrix_editors()
            self._refresh_customer_tab()
        except Exception as e:
            messagebox.showerror("Hata", str(e))

    # =========================================================================
    # SONUCLAR SEKMESI
    # =========================================================================
    def _build_results_tab(self):
        p = self._tab_results

        top = tk.Frame(p, bg=BG)
        top.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(top, text="Pareto Cephesi - En Iyi Cozumler",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=TEXT).pack(side="left")
        tk.Button(top, text="Sonuclari Kaydet",
                  font=("Segoe UI", 9), bg=PANEL, fg=TEXT,
                  relief="flat", bd=0, padx=12, pady=6,
                  cursor="hand2", command=self._save_results).pack(side="right")

        cols = ("No", "Maliyet (TL)", "Maks Sure (dk)", "Ort Sure (dk)", "Rota Sayisi")
        style = ttk.Style()
        style.configure("dark.Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=26, font=("Segoe UI", 9))
        style.configure("dark.Treeview.Heading", background=ACCENT, foreground="white",
                        font=("Segoe UI", 9, "bold"))
        style.map("dark.Treeview", background=[("selected", ACCENT2)])

        tree_f = tk.Frame(p, bg=BG)
        tree_f.pack(fill="x", padx=12, pady=(6, 0))
        self._tree = ttk.Treeview(tree_f, columns=cols, show="headings",
                                  height=8, style="dark.Treeview")
        for col, w in zip(cols, [40, 120, 130, 130, 100]):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, anchor="center")
        vsb = ttk.Scrollbar(tree_f, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="x", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        tk.Label(p, text="Secili Cozum Detayi",
                 font=("Segoe UI", 10, "bold"), bg=BG, fg=TEXT
                 ).pack(anchor="w", padx=12, pady=(10, 2))
        self._detail = scrolledtext.ScrolledText(
            p, font=("Consolas", 9), bg=LOG_BG, fg="#fbbf24",
            insertbackground="white", relief="flat", bd=4, state="disabled", height=14)
        self._detail.pack(fill="both", expand=True, padx=12, pady=(0, 12))

    # =========================================================================
    # HELPERS
    # =========================================================================
    def _card(self, parent, title):
        outer = tk.Frame(parent, bg=PANEL)
        outer.pack(fill="x", pady=4)
        tk.Label(outer, text=title, font=("Segoe UI", 10, "bold"),
                 bg=PANEL, fg=ACCENT2).pack(anchor="w", padx=10, pady=(8, 4))
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="x", padx=10, pady=(0, 10))
        return inner

    def _log_write(self, msg):
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    # =========================================================================
    # CALISTIR / DURDUR (VRP)
    # =========================================================================
    def _start(self):
        if self._running:
            return
        nodes = self._get_selected_nodes()
        if len(nodes) < 2:
            messagebox.showwarning("Uyari", "En az 1 musteri secmelisiniz!")
            return
        try:
            pop_size    = int(self._entries["pop_size"].get())
            generations = int(self._entries["generations"].get())
            seed        = int(self._entries["seed"].get())
        except ValueError:
            messagebox.showerror("Hata", "Parametreler tam sayi olmali!")
            return

        sub_dist, sub_time = self._build_submatrix(nodes)
        self._stop[0]  = False
        self._running  = True
        self._btn_run.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._prog_var.set(0)
        self._prog_lbl.configure(text="Calisiyor...")
        self._clear_log()
        self._log_write(f"Baslatildi  |  pop={pop_size}  gen={generations}  seed={seed}")
        self._log_write(f"Secili musteriler ({len(nodes)-1}): {nodes[1:]}")
        self._log_write(f"Sub-matris: {len(nodes)}x{len(nodes)}\n")
        self._total_gens      = generations
        self._start_time      = time.time()
        self._result_node_map = nodes

        self._thread = threading.Thread(
            target=self._worker,
            args=(sub_dist, sub_time, pop_size, generations, seed),
            daemon=True)
        self._thread.start()

    def _stop_run(self):
        self._stop[0] = True
        self._log_write("\nKullanici tarafindan durduruldu.")

    def _worker(self, dist, time_mat, pop_size, generations, seed):
        try:
            def cb(gen, rank1, best_cost):
                self._queue.put(("progress", gen, rank1, best_cost))
            results = run_nsga2(dist, time_mat, pop_size, generations, seed,
                                callback=cb, stop_flag=self._stop)
            self._queue.put(("done", results))
        except Exception as e:
            self._queue.put(("error", str(e)))

    # =========================================================================
    # QUEUE POLLING (VRP + Geocoding mesajlari birlikte)
    # =========================================================================
    def _poll_queue(self):
        try:
            while True:
                item = self._queue.get_nowait()
                kind = item[0]

                # ── VRP mesajlari ──────────────────────────────────────────
                if kind == "progress":
                    _, gen, rank1, best_cost = item
                    pct = min(100.0, gen / self._total_gens * 100)
                    self._prog_var.set(pct)
                    elapsed = time.time() - self._start_time
                    self._prog_lbl.configure(
                        text=f"Nesil {gen}/{self._total_gens}  |  {pct:.0f}%  |  {elapsed:.0f}s")
                    self._log_write(
                        f"Gen {gen:5d} | Rank-1: {rank1:3d} | Maliyet: {best_cost:.2f}")

                elif kind == "done":
                    results = item[1]
                    elapsed = time.time() - self._start_time
                    self._running = False
                    self._btn_run.configure(state="normal")
                    self._btn_stop.configure(state="disabled")
                    self._prog_var.set(100)
                    self._prog_lbl.configure(text=f"Tamamlandi ({elapsed:.1f}s)")
                    self._log_write(f"\nTamamlandi! Sure: {elapsed:.1f}s")
                    self._log_write(f"Rank-1: {len(results)} cozum")
                    self._show_results(results)
                    self._nb.select(self._tab_results)

                elif kind == "error":
                    self._running = False
                    self._btn_run.configure(state="normal")
                    self._btn_stop.configure(state="disabled")
                    self._prog_lbl.configure(text="Hata!")
                    self._log_write(f"\nHata: {item[1]}")
                    messagebox.showerror("Hata", item[1])

                # ── Geocoding / Matris mesajlari ───────────────────────────
                elif kind == "geo_log":
                    self._geo_log_write(item[1])

                elif kind == "geo_refresh":
                    self._refresh_loc_tree()

                elif kind == "matrix_ready":
                    _, dist_mat, time_mat = item
                    self._dist_matrix = dist_mat
                    self._time_matrix = time_mat
                    self._load_matrix_editors()
                    self._refresh_customer_tab()
                    self._geo_log_write("Matrisler uygulamaya yuklendi. Musteri Secimi sekmesi guncellendi.")

                elif kind == "geo_done":
                    self._geo_running = False
                    self._btn_geocode.configure(state="normal")
                    self._btn_matrix.configure(state="normal")
                    self._btn_geo_stop.configure(state="disabled")
                    what = item[1]
                    if what == "geocode":
                        self._geo_log_write("Geocoding tamamlandi.")
                        messagebox.showinfo("Tamamlandi", "Koordinat bulma islemi tamamlandi!")
                    elif what == "matrix":
                        self._geo_log_write("Matris hesaplama tamamlandi.")
                        messagebox.showinfo("Tamamlandi",
                            "Mesafe + Zaman matrisleri hesaplandi!\n"
                            "Musteri Secimi sekmesi otomatik guncellendi.")
                        self._nb.select(self._tab_cust)

        except queue.Empty:
            pass
        self._after_id = self.after(100, self._poll_queue)

    # =========================================================================
    # SONUCLAR
    # =========================================================================
    def _map_route(self, route):
        nm = self._result_node_map
        return [nm[idx] for idx in route]

    def _loc_name(self, orig_id):
        """Orijinal ID icin lokasyon adini dondur."""
        if self._locations:
            match = next((l for l in self._locations if l.get("id") == orig_id), None)
            if match:
                return match.get("name", f"ID{orig_id}")
        return f"ID{orig_id}"

    def _show_results(self, results):
        self._results_data = results
        for row in self._tree.get_children():
            self._tree.delete(row)
        for i, r in enumerate(results, 1):
            self._tree.insert("", "end", iid=str(i), values=(
                i, f"{r['cost']:.2f}", f"{r['max_duration']:.2f}",
                f"{r['avg_duration']:.2f}", len(r["routes"])
            ))
        if results:
            self._tree.selection_set("1")
            self._show_detail(results[0])

    def _on_select(self, _event):
        sel = self._tree.selection()
        if sel:
            idx = int(sel[0]) - 1
            if 0 <= idx < len(self._results_data):
                self._show_detail(self._results_data[idx])

    def _show_detail(self, r):
        self._detail.configure(state="normal")
        self._detail.delete("1.0", "end")
        lines = [
            f"Toplam Maliyet : {r['cost']:.2f} TL",
            f"Maks Sure      : {r['max_duration']:.2f} dk",
            f"Ort Sure       : {r['avg_duration']:.2f} dk",
            f"Rota Sayisi    : {len(r['routes'])}",
            "", "-" * 60,
            "ROTALAR (Orijinal ID + Isim):",
        ]
        for k, (route, dur) in enumerate(zip(r["routes"], r["durations"]), 1):
            orig = self._map_route(route)
            names = [self._loc_name(oid) for oid in orig]
            lines.append(
                f"  Taksi {k}: [Depo] -> "
                + " -> ".join(f"{oid}({nm})" for oid, nm in zip(orig, names))
                + f" -> [Depo]   ({dur:.2f} dk)")
        self._detail.insert("end", "\n".join(lines))
        self._detail.configure(state="disabled")

    def _save_results(self):
        if not self._results_data:
            messagebox.showwarning("Uyari", "Henuz sonuc yok!")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Metin Dosyasi", "*.txt"), ("JSON", "*.json")])
        if not path:
            return
        if path.endswith(".json"):
            export = []
            for r in self._results_data:
                export.append({
                    "cost": r["cost"],
                    "max_duration": r["max_duration"],
                    "avg_duration": r["avg_duration"],
                    "routes": [
                        {"ids": self._map_route(rt),
                         "names": [self._loc_name(i) for i in self._map_route(rt)],
                         "duration": dur}
                        for rt, dur in zip(r["routes"], r["durations"])
                    ],
                })
            with open(path, "w") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
        else:
            with open(path, "w", encoding="utf-8") as f:
                for i, r in enumerate(self._results_data, 1):
                    f.write(f"Cozum {i}\n")
                    f.write(f"  Maliyet   : {r['cost']:.2f}\n")
                    f.write(f"  Maks Sure : {r['max_duration']:.2f}\n")
                    f.write(f"  Ort Sure  : {r['avg_duration']:.2f}\n")
                    for k, (route, dur) in enumerate(zip(r["routes"], r["durations"]), 1):
                        orig  = self._map_route(route)
                        names = [self._loc_name(o) for o in orig]
                        f.write(f"  Taksi {k}: "
                                + " -> ".join(f"{o}({n})" for o, n in zip(orig, names))
                                + f"  ({dur:.2f} dk)\n")
                    f.write("\n")
        messagebox.showinfo("Kaydedildi", path)

    def on_close(self):
        self._stop[0]     = True
        self._geo_stop[0] = True
        self.after_cancel(self._after_id)
        self.destroy()


if __name__ == "__main__":
    app = VRPApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
