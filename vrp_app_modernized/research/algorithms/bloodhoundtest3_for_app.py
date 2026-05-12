import random
import math
import heapq
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Set
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

try:
    from numba import njit
    NUMBA_AVAILABLE = np is not None
except ImportError:
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

Point           = Tuple[float, float]
Route           = List[int]
Route_matrix    = List[Route]
Distance_matrix = List[List[float]]
Edge            = Tuple[int, int]
NUMBA_CACHE_ENABLED = __name__ != "<run_path>"


@njit(cache=NUMBA_CACHE_ENABLED)
def _route_distance_numba(route, dist):
    total = 0.0
    for i in range(len(route) - 1):
        total += dist[route[i], route[i + 1]]
    return total


@njit(cache=NUMBA_CACHE_ENABLED)
def _route_load_numba(route, demands):
    total = 0.0
    for i in range(len(route)):
        total += demands[route[i]]
    return total


@njit(cache=NUMBA_CACHE_ENABLED)
def _travel_time_numba(from_node, to_node, dist, speed):
    return dist[from_node, to_node] / speed


@njit(cache=NUMBA_CACHE_ENABLED)
def _best_insertion_position_numba(route, customer, dist):
    best_pos = 1
    best_delta = 1e18
    for i in range(len(route) - 1):
        a = route[i]
        b = route[i + 1]
        delta = dist[a, customer] + dist[customer, b] - dist[a, b]
        if delta < best_delta:
            best_delta = delta
            best_pos = i + 1
    return best_pos, best_delta


@njit(cache=NUMBA_CACHE_ENABLED)
def _evaluate_route_kernel_numba(
        route, dist, demands, time_window_open, time_window_close, service_times,
        capacity, cost_per_km, fixed_cost, speed, max_route_time_min
):
    load = _route_load_numba(route, demands)
    route_dist = _route_distance_numba(route, dist)
    cost = fixed_cost + route_dist * cost_per_km

    if load > capacity:
        return False, load, route_dist, 0.0, cost

    current_time = 0.0
    for i in range(1, len(route) - 1):
        prev_node = route[i - 1]
        node = route[i]
        current_time += _travel_time_numba(prev_node, node, dist, speed)
        window_open = time_window_open[node]
        window_close = time_window_close[node]
        if current_time < window_open:
            current_time = window_open
        if current_time > window_close:
            return False, load, route_dist, current_time, cost
        if node != 0:
            current_time += service_times[node]

    if len(route) >= 2:
        current_time += _travel_time_numba(route[len(route) - 2], route[len(route) - 1], dist, speed)

    if max_route_time_min >= 0.0 and current_time > max_route_time_min:
        return False, load, route_dist, current_time, cost

    return True, load, route_dist, current_time, cost


# SO: Soft-capacity versiyonu — kapasite aşımı False döndürmez, ceza ekler.
# Zaman pencereleri hard kalır.
@njit(cache=NUMBA_CACHE_ENABLED)
def _evaluate_route_kernel_soft_cap_numba(
        route, dist, demands, time_window_open, time_window_close, service_times,
        capacity, cost_per_km, fixed_cost, speed, max_route_time_min,
        cap_penalty_weight   # SO: birim aşım başına ceza ağırlığı
):
    load = _route_load_numba(route, demands)
    route_dist = _route_distance_numba(route, dist)
    cost = fixed_cost + route_dist * cost_per_km

    # SO: kapasite aşımı → False değil, ceza
    if load > capacity:
        cost += cap_penalty_weight * (load - capacity)

    current_time = 0.0
    for i in range(1, len(route) - 1):
        prev_node = route[i - 1]
        node = route[i]
        current_time += _travel_time_numba(prev_node, node, dist, speed)
        window_open = time_window_open[node]
        window_close = time_window_close[node]
        if current_time < window_open:
            current_time = window_open
        if current_time > window_close:
            return False, load, route_dist, current_time, cost  # TW hâlâ hard
        if node != 0:
            current_time += service_times[node]

    if len(route) >= 2:
        current_time += _travel_time_numba(route[len(route) - 2], route[len(route) - 1], dist, speed)

    if max_route_time_min >= 0.0 and current_time > max_route_time_min:
        return False, load, route_dist, current_time, cost

    return True, load, route_dist, current_time, cost


@njit(cache=NUMBA_CACHE_ENABLED)
def _best_vehicle_type_for_route_numba(
        route, dist, demands, time_window_open, time_window_close, service_times,
        capacities, cost_per_km, fixed_costs, speeds, max_counts, usage_counts,
        current_type_id, allow_current_type, max_route_time_min
):
    best_type_id = -1
    best_cost = 1e18
    best_dist = 1e18

    for type_id in range(len(capacities)):
        if allow_current_type and type_id == current_type_id:
            pass
        else:
            if usage_counts[type_id] >= max_counts[type_id]:
                continue

        route_ok, load, route_dist, route_time, cost = _evaluate_route_kernel_numba(
            route, dist, demands,
            time_window_open, time_window_close, service_times,
            capacities[type_id], cost_per_km[type_id], fixed_costs[type_id],
            speeds[type_id], max_route_time_min,
        )

        if route_ok:
            if (cost < best_cost or
                    (cost == best_cost and route_dist < best_dist) or
                    (cost == best_cost and route_dist == best_dist
                     and capacities[type_id] < capacities[best_type_id])):
                best_type_id = type_id
                best_cost = cost
                best_dist = route_dist

    return best_type_id, best_cost, best_dist


@njit(cache=NUMBA_CACHE_ENABLED)
def _route_has_duplicate_customer_numba(route, n_nodes):
    seen = np.zeros(n_nodes, dtype=np.uint8)
    for i in range(len(route)):
        node = route[i]
        if node == 0:
            continue
        if seen[node]:
            return True
        seen[node] = 1
    return False


@njit(cache=NUMBA_CACHE_ENABLED)
def _mark_covered_customers_numba(route, covered):
    for i in range(len(route)):
        node = route[i]
        if node != 0:
            covered[node] = 1


@njit(cache=NUMBA_CACHE_ENABLED)
def _compute_route_centroid_numba(route, coords, depot_x, depot_y):
    sx = 0.0
    sy = 0.0
    count = 0
    for i in range(len(route)):
        node = route[i]
        if node != 0:
            sx += coords[node, 0]
            sy += coords[node, 1]
            count += 1
    if count == 0:
        return depot_x, depot_y
    return sx / count, sy / count


@njit(cache=NUMBA_CACHE_ENABLED)
def _best_two_opt_move_numba(route, dist):
    best_i = -1
    best_k = -1
    best_delta = 0.0
    n = len(route)
    for i in range(1, n - 2):
        a = route[i - 1]
        b = route[i]
        for k in range(i + 1, n - 1):
            c = route[k]
            d = route[k + 1]
            delta = dist[a, c] + dist[b, d] - dist[a, b] - dist[c, d]
            if delta < best_delta:
                best_delta = delta
                best_i = i
                best_k = k
    return best_i, best_k, best_delta


@njit(cache=NUMBA_CACHE_ENABLED)
def _select_candidate_route_indices_numba(customer_x, customer_y, centroid_x, centroid_y, max_candidates):
    n = len(centroid_x)
    distances = np.empty(n, dtype=np.float64)
    indices   = np.empty(n, dtype=np.int64)
    for i in range(n):
        dx = customer_x - centroid_x[i]
        dy = customer_y - centroid_y[i]
        distances[i] = dx * dx + dy * dy
        indices[i]   = i
    order  = np.argsort(distances)
    limit  = min(max_candidates, n)
    result = np.empty(limit, dtype=np.int64)
    for i in range(limit):
        result[i] = indices[order[i]]
    return result


@njit(cache=NUMBA_CACHE_ENABLED)
def _count_granular_overlap_numba(route, granular_neighbors_row, granular_count):
    overlap = 0
    for i in range(len(route)):
        node = route[i]
        if node == 0:
            continue
        for j in range(granular_count):
            if node == granular_neighbors_row[j]:
                overlap += 1
                break
    return overlap


@njit(cache=NUMBA_CACHE_ENABLED)
def _route_spread_numba(route, coords, depot_x, depot_y):
    cx, cy = _compute_route_centroid_numba(route, coords, depot_x, depot_y)
    best = 0.0
    for i in range(len(route)):
        node = route[i]
        if node == 0:
            continue
        dx = coords[node, 0] - cx
        dy = coords[node, 1] - cy
        d = math.sqrt(dx * dx + dy * dy)
        if d > best:
            best = d
    return best


@njit(cache=NUMBA_CACHE_ENABLED)
def _customer_outlier_score_numba(
        route, customer, coords, dist, granular_neighbors, granular_counts, depot_x, depot_y
):
    present = False
    route_len = 0
    for i in range(len(route)):
        node = route[i]
        if node != 0:
            route_len += 1
            if node == customer:
                present = True
    if (not present) or route_len <= 1:
        return 0.0

    cx, cy = _compute_route_centroid_numba(route, coords, depot_x, depot_y)
    dx = coords[customer, 0] - cx
    dy = coords[customer, 1] - cy
    radial = math.sqrt(dx * dx + dy * dy)

    nearest = 1e18
    for i in range(len(route)):
        other = route[i]
        if other != 0 and other != customer:
            d = dist[customer, other]
            if d < nearest:
                nearest = d
    if nearest > 1e17:
        nearest = 0.0

    overlap = 0
    gcount = granular_counts[customer]
    for i in range(len(route)):
        other = route[i]
        if other == 0 or other == customer:
            continue
        for j in range(gcount):
            if other == granular_neighbors[customer, j]:
                overlap += 1
                break
    return radial + 0.45 * nearest - 55.0 * overlap


@njit(cache=NUMBA_CACHE_ENABLED)
def _rank_route_outliers_numba(
        route, coords, dist, granular_neighbors, granular_counts, depot_x, depot_y, max_customers
):
    customers = np.empty(len(route), dtype=np.int64)
    scores = np.empty(len(route), dtype=np.float64)
    count = 0
    for i in range(len(route)):
        node = route[i]
        if node != 0:
            customers[count] = node
            scores[count] = _customer_outlier_score_numba(
                route, node, coords, dist, granular_neighbors, granular_counts, depot_x, depot_y
            )
            count += 1
    if count == 0:
        return np.empty(0, dtype=np.int64)
    order = np.argsort(scores[:count])[::-1]
    limit = min(max_customers, count)
    result = np.empty(limit, dtype=np.int64)
    for i in range(limit):
        result[i] = customers[order[i]]
    return result


# ==============================================================================
#  ALGO CONFIG
# ==============================================================================

ALGO_CONFIG = {
    "alpha_cost_weight":                     0.82,
    "alpha_blood_weight":                    0.04,
    "alpha_history_weight":                  0.14,
    "elite_pool_max_size":                   4,
    "elite_max_similarity":                  0.90,
    "regret3_probability":                   0.35,
    "destroy_prob_shaw":                     0.35,
    "destroy_prob_worst":                    0.25,
    "destroy_prob_targeted":                 0.25,
    "targeted_destroy_neighbor_routes":      4,
    "route_elimination_max_routes":          2,
    "stagnation_hunt_limit":                 1,
    "stagnation_ruin_boost":                 0.20,
    "stagnation_ruin_cap":                   0.55,
    "adaptive_small_route_count":            15,
    "adaptive_medium_route_count":           25,
    "adaptive_dense_route_threshold":        8.5,
    "adaptive_medium_route_threshold":       6.5,
    "free_search_quality_update_interval":   4,
    "destroy_bandit_eps":                    0.06,
    "granular_neighbor_k":                   18,
    "granular_route_boost_weight":           5.0,
    "insertion_centroid_penalty_weight":     0.22,
    "insertion_outlier_penalty_weight":      0.65,
    "insertion_load_penalty_threshold":      0.82,
    "insertion_load_penalty_weight":         420.0,
    "outlier_source_routes":                 7,
    "outlier_target_routes":                 7,
    "outlier_customers_per_route":           4,
    "ejection_target_routes":                5,
    "ejection_candidates_per_route":         3,
    "cluster_rebuild_bad_routes":            4,
    "cluster_rebuild_neighbor_routes":       3,
    "cluster_rebuild_max_routes":            6,
    "route_surgery_max_targets":             3,
    "route_surgery_neighbor_routes":         3,
    "route_surgery_max_routes":              5,
    "micro_lns_neighbor_routes":             2,
    "micro_lns_extra_routes":                1,
    "micro_lns_attempts":                    7,
    "full_moon_bad_routes":                  2,
    "full_moon_neighbor_routes":             2,
    "full_moon_max_routes":                  4,
    "full_moon_attempts":                    5,
    "full_moon_post_ls_rounds":              1,
    "outlier_purge_routes":                  4,
    "outlier_purge_customers_per_route":     4,
    "targeted_rebuild_attempts":             5,
    "targeted_cleanup_spread_sigma":         1.0,
    "targeted_cleanup_distance_sigma":       1.25,
    "targeted_cleanup_cost_slack":           520.0,
    "targeted_cleanup_badness_gain":         60.0,
    "targeted_cleanup_prob":                 0.35,
    "targeted_cleanup_neighbor_routes":      2,
    "targeted_cleanup_extra_routes":         2,
    "bandit_reaction_factor":                0.30,
    "bandit_reward_global_best":             12.0,
    "bandit_reward_improving":               6.0,
    "bandit_reward_feasible":                1.5,
    "bandit_reward_fail":                    0.1,
    "bandit_mode_score_floor":               0.20,
    "bandit_prior_shaw":                     0.80,
    "bandit_prior_worst":                    0.90,
    "bandit_prior_targeted":                 4.80,
    "bandit_prior_route":                    1.10,
    "bandit_pathology_bias_prob":            0.90,
    "bandit_pathology_bonus_weight":         0.090,
    "bandit_targeted_bonus_mult":            2.10,
    "bandit_route_bonus_mult":               1.10,
    # SO: Strategic Oscillation parametreleri
    "so_cap_penalty_weight":                 300.0,   # birim kapasite aşımı başına ceza
    "so_relax_period":                       25,      # RELAX fazında kalınacak adım sayısı
    "so_enforce_period":                     25,      # ENFORCE fazında kalınacak adım sayısı
    "adaptive_profiles": {
        "dense": {
            "regret_customer_limit":   12,
            "regret_route_limit":       4,
            "long_route_mode":       True,
            "intra_routes":             4,
            "relocate_pairs":           4,
            "two_opt_pairs":            3,
            "cross_pairs":              2,
            "or_opt_pairs":             2,
            "max_cuts_per_route":       3,
            "max_cross_starts":         3,
            "path_customers":           8,
            "path_steps":               2,
            "ls_rounds":                1,
            "route_elimination_tries":  1,
        },
        "medium": {
            "regret_customer_limit":   18,
            "regret_route_limit":       6,
            "long_route_mode":      False,
            "intra_routes":             5,
            "relocate_pairs":           6,
            "two_opt_pairs":            4,
            "cross_pairs":              3,
            "or_opt_pairs":             3,
            "max_cuts_per_route":       4,
            "max_cross_starts":         4,
            "path_customers":          12,
            "path_steps":               4,
            "ls_rounds":                2,
            "route_elimination_tries":  1,
        },
        "light": {
            "regret_customer_limit":   24,
            "regret_route_limit":       8,
            "long_route_mode":      False,
            "intra_routes":             6,
            "relocate_pairs":           8,
            "two_opt_pairs":            6,
            "cross_pairs":              5,
            "or_opt_pairs":             5,
            "max_cuts_per_route":       5,
            "max_cross_starts":         5,
            "path_customers":          20,
            "path_steps":               6,
            "ls_rounds":                3,
            "route_elimination_tries":  2,
        },
    },
}


# ==============================================================================
#  VERİ YAPILARI
# ==============================================================================

@dataclass
class Vehicle:
    vehicle_id:  int
    capacity:    float
    cost_per_km: float
    fixed_cost:  float = 0.0
    speed:       float = 1.0


@dataclass
class VehicleType:
    type_id:     int
    capacity:    float
    cost_per_km: float
    fixed_cost:  float = 0.0
    speed:       float = 1.0
    max_count:   int   = 1


def _auto_build_vehicle_types(vehicles: List[Vehicle]) -> List[VehicleType]:
    groups: Dict[Tuple, int] = {}
    order:  List[Tuple]      = []
    for v in vehicles:
        key = (v.capacity, v.cost_per_km, v.fixed_cost, v.speed)
        if key not in groups:
            groups[key] = 0
            order.append(key)
        groups[key] += 1
    result: List[VehicleType] = []
    for type_id, key in enumerate(order):
        cap, cpm, fc, spd = key
        result.append(VehicleType(
            type_id=type_id, capacity=cap, cost_per_km=cpm,
            fixed_cost=fc, speed=spd, max_count=groups[key]
        ))
    return result


def _route_to_numpy(route: Route):
    if np is None:
        return route
    if isinstance(route, np.ndarray):
        return route
    return np.asarray(route, dtype=np.int64)


def _routes_to_numpy(routes: Route_matrix):
    if np is None:
        return routes
    return [_route_to_numpy(route) for route in routes]


@dataclass
class SolutionState:
    routes:          Route_matrix
    vehicle_ids:     List[int]
    route_loads:     List[float]
    route_distances: List[float]
    route_times:     List[float]
    route_costs:     List[float]
    total_cost:      float
    feasible:        bool
    # SO: Kapasite dahil TÜM hard kısıtların sağlandığını gösterir.
    # RELAX fazında feasible=True ama hard_feasible=False olabilir.
    # elite_pool ve best_state yalnız hard_feasible=True çözümleri kabul eder.
    hard_feasible:   bool = field(default=True)
    _route_arrays:   Optional[List[object]] = field(default=None, init=False, repr=False)
    _route_cores:    Optional[Dict[int, List[int]]] = field(default=None, init=False, repr=False)
    _route_core_sets: Optional[Dict[int, Set[int]]] = field(default=None, init=False, repr=False)
    _route_centroids: Optional[List[Point]] = field(default=None, init=False, repr=False)
    _route_spreads:  Optional[Dict[int, float]] = field(default=None, init=False, repr=False)
    _route_outliers: Optional[Dict[Tuple[int, int], List[int]]] = field(default=None, init=False, repr=False)
    _route_badness:  Optional[Dict[int, float]] = field(default=None, init=False, repr=False)
    _pathology_flag: Optional[bool] = field(default=None, init=False, repr=False)


@dataclass
class HCVRPProblem:
    coords:        List[Point]
    demands:       List[float]
    vehicles:      List[Vehicle]
    time_windows:  Optional[List[Tuple[float, float]]] = None
    service_times: Optional[List[float]]               = None
    distance_matrix: Optional[Distance_matrix]         = None
    time_matrix: Optional[Distance_matrix]             = None
    max_route_time_min: Optional[float]                = None
    dist:          Distance_matrix                     = field(init=False)
    n_nodes:       int                                 = field(init=False)
    customer_ids:  List[int]                           = field(init=False)
    vehicle_types: List[VehicleType]                   = field(init=False)

    def __post_init__(self):
        self.n_nodes      = len(self.coords)
        self.customer_ids = list(range(1, self.n_nodes))

        if len(self.demands) != self.n_nodes:
            raise ValueError("Demands Coords ile aynı uzunlukta olmalı")
        if self.demands[0] != 0:
            raise ValueError("Depot demand 0 olmalı")
        if len(self.vehicles) == 0:
            raise ValueError("En az 1 araç tanımlanmalı")

        if self.time_windows is None:
            self.time_windows = [(0.0, float("inf")) for _ in range(self.n_nodes)]
        elif len(self.time_windows) != self.n_nodes:
            raise ValueError("time_windows uzunlugu node sayisi ile ayni olmali")

        if self.service_times is None:
            self.service_times = [0.0 for _ in range(self.n_nodes)]
        elif len(self.service_times) != self.n_nodes:
            raise ValueError("service_times uzunlugu node sayisi ile ayni olmali")

        self.dist = (
            [[float(x) for x in row] for row in self.distance_matrix]
            if self.distance_matrix is not None
            else self.build_tsplib_euc2d_matrix(self.coords)
        )
        self.granular_neighbors = self._build_granular_neighbors(
            int(ALGO_CONFIG["granular_neighbor_k"])
        )
        if np is not None:
            self.coords_np           = np.asarray(self.coords,        dtype=np.float64)
            self.dist_np             = np.asarray(self.dist,          dtype=np.float64)
            self.demands_np          = np.asarray(self.demands,       dtype=np.float64)
            self.service_times_np    = np.asarray(self.service_times, dtype=np.float64)
            self.time_window_open_np = np.asarray([tw[0] for tw in self.time_windows], dtype=np.float64)
            self.time_window_close_np= np.asarray([tw[1] for tw in self.time_windows], dtype=np.float64)
            gk = int(ALGO_CONFIG["granular_neighbor_k"])
            self.granular_neighbors_np = np.full((self.n_nodes, gk), -1, dtype=np.int64)
            self.granular_neighbor_counts_np = np.zeros(self.n_nodes, dtype=np.int64)
            for customer in range(self.n_nodes):
                neigh = self.granular_neighbors[customer]
                count = min(len(neigh), gk)
                self.granular_neighbor_counts_np[customer] = count
                for idx in range(count):
                    self.granular_neighbors_np[customer, idx] = neigh[idx]

        self.vehicle_types = _auto_build_vehicle_types(self.vehicles)
        self.max_vehicle_capacity = max(vt.capacity for vt in self.vehicle_types)

        self._has_tight_time_windows = any(
            tw[0] > 0.0 or tw[1] < float("inf") for tw in self.time_windows
        )

        if np is not None:
            self.vehicle_type_capacities_np  = np.asarray([vt.capacity    for vt in self.vehicle_types], dtype=np.float64)
            self.vehicle_type_cost_per_km_np = np.asarray([vt.cost_per_km for vt in self.vehicle_types], dtype=np.float64)
            self.vehicle_type_fixed_costs_np = np.asarray([vt.fixed_cost  for vt in self.vehicle_types], dtype=np.float64)
            self.vehicle_type_speeds_np      = np.asarray([vt.speed       for vt in self.vehicle_types], dtype=np.float64)
            self.vehicle_type_max_counts_np  = np.asarray([vt.max_count   for vt in self.vehicle_types], dtype=np.int64)

    def _build_granular_neighbors(self, k: int) -> List[List[int]]:
        neighbors: List[List[int]] = [[] for _ in range(self.n_nodes)]
        for customer in range(1, self.n_nodes):
            ranked = sorted(
                (self.dist[customer][other], other)
                for other in range(1, self.n_nodes)
                if other != customer
            )
            neighbors[customer] = [other for _, other in ranked[:k]]
        return neighbors

    @staticmethod
    def build_tsplib_euc2d_matrix(coords: List[Point]) -> Distance_matrix:
        n    = len(coords)
        dist = [[0.0] * n for _ in range(n)]
        for i in range(n):
            x1, y1 = coords[i]
            for j in range(n):
                x2, y2 = coords[j]
                dx = x1 - x2; dy = y1 - y2
                dist[i][j] = int(math.sqrt(dx * dx + dy * dy) + 0.5)
        return dist

    def route_distance(self, route: Route) -> float:
        if NUMBA_AVAILABLE and np is not None:
            return float(_route_distance_numba(_route_to_numpy(route), self.dist_np))
        total = 0.0
        for i in range(len(route) - 1):
            total += self.dist[route[i]][route[i + 1]]
        return total

    def travel_time(self, from_node: int, to_node: int, vehicle: VehicleType) -> float:
        if self.time_matrix is not None:
            return float(self.time_matrix[from_node][to_node])
        if vehicle.speed <= 0:
            raise ValueError("Vehicle speed pozitif olmali")
        if NUMBA_AVAILABLE and np is not None:
            return float(_travel_time_numba(from_node, to_node, self.dist_np, vehicle.speed))
        return self.dist[from_node][to_node] / vehicle.speed

    def route_load(self, route: Route) -> float:
        if NUMBA_AVAILABLE and np is not None:
            return float(_route_load_numba(_route_to_numpy(route), self.demands_np))
        total = 0.0
        for node in route:
            total += self.demands[node]
        return total

    def customers_covered_once(self, routes: Route_matrix) -> bool:
        seen = [node for route in routes for node in route if node != 0]
        return sorted(seen) == self.customer_ids


# ==============================================================================
#  VRPLIB PARSE
# ==============================================================================

def tsplib_distance_from_coords(a: Point, b: Point, edge_weight_type: str) -> float:
    x1, y1 = a; x2, y2 = b
    dx = x1 - x2; dy = y1 - y2
    if edge_weight_type == "EUC_2D":   return int(math.sqrt(dx*dx + dy*dy) + 0.5)
    if edge_weight_type == "CEIL_2D":  return math.ceil(math.sqrt(dx*dx + dy*dy))
    if edge_weight_type == "FLOOR_2D": return math.floor(math.sqrt(dx*dx + dy*dy))
    if edge_weight_type == "MAN_2D":   return abs(dx) + abs(dy)
    if edge_weight_type == "MAX_2D":   return max(abs(dx), abs(dy))
    raise ValueError(f"Desteklenmeyen EDGE_WEIGHT_TYPE: {edge_weight_type}")


def build_distance_matrix_from_coords(coords: List[Point], edge_weight_type: str) -> Distance_matrix:
    n    = len(coords)
    dist = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            dist[i][j] = tsplib_distance_from_coords(coords[i], coords[j], edge_weight_type)
    return dist


def parse_explicit_edge_weight_matrix(
        flat_values: List[float], dimension: int, edge_weight_format: str
) -> Distance_matrix:
    fmt  = edge_weight_format.upper()
    dist = [[0.0] * dimension for _ in range(dimension)]
    idx  = 0

    def take() -> float:
        nonlocal idx
        if idx >= len(flat_values): raise ValueError("EDGE_WEIGHT_SECTION beklenenden kisa")
        v = flat_values[idx]; idx += 1; return v

    if fmt == "FULL_MATRIX":
        for i in range(dimension):
            for j in range(dimension): dist[i][j] = take()
    elif fmt == "UPPER_ROW":
        for i in range(dimension):
            for j in range(i+1, dimension): v = take(); dist[i][j] = dist[j][i] = v
    elif fmt == "LOWER_ROW":
        for i in range(dimension):
            for j in range(0, i): v = take(); dist[i][j] = dist[j][i] = v
    elif fmt == "UPPER_DIAG_ROW":
        for i in range(dimension):
            for j in range(i, dimension): v = take(); dist[i][j] = dist[j][i] = v
    elif fmt == "LOWER_DIAG_ROW":
        for i in range(dimension):
            for j in range(0, i+1): v = take(); dist[i][j] = dist[j][i] = v
    else:
        raise ValueError(f"Desteklenmeyen EDGE_WEIGHT_FORMAT: {edge_weight_format}")
    return dist


def _parse_vrplib_lines(
        lines: List[str], source_name: str, benchmark_compatible_hfvrp_costs: bool
) -> "HCVRPProblem":
    sections: Dict[str, List[str]] = {
        "NODE_COORD_SECTION": [], "DEMAND_SECTION": [], "EDGE_WEIGHT_SECTION": [],
        "CAPACITY_SECTION": [], "VEHICLES_FIXED_COST_SECTION": [],
        "VEHICLES_UNIT_DISTANCE_COST_SECTION": [], "DEPOT_SECTION": [],
    }
    metadata: Dict[str, str] = {}
    current_section: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line: continue
        if line in sections: current_section = line; continue
        if line == "EOF": break
        if current_section is not None: sections[current_section].append(line); continue
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()

    edge_weight_type   = metadata.get("EDGE_WEIGHT_TYPE", "").upper()
    edge_weight_format = metadata.get("EDGE_WEIGHT_FORMAT", "").upper()

    if "DIMENSION" not in metadata:
        raise ValueError(f"DIMENSION alani bulunamadi: {source_name}")

    dimension        = int(metadata["DIMENSION"])
    depot_vrplib_id  = int(sections["DEPOT_SECTION"][0])
    depot_zero_based = depot_vrplib_id - 1

    raw_coords: Dict[int, Point] = {}
    for entry in sections["NODE_COORD_SECTION"]:
        parts = entry.split()
        if len(parts) >= 3:
            raw_coords[int(parts[0]) - 1] = (float(parts[1]), float(parts[2]))

    raw_demands: Dict[int, float] = {}
    for entry in sections["DEMAND_SECTION"]:
        node_id_str, demand_str = entry.split()
        raw_demands[int(node_id_str) - 1] = float(demand_str)

    capacities:     List[float] = [float(e.split()[1]) for e in sections["CAPACITY_SECTION"]]
    variable_costs: List[float] = [float(e.split()[1]) for e in sections["VEHICLES_UNIT_DISTANCE_COST_SECTION"]]
    fixed_cost_entries = sections["VEHICLES_FIXED_COST_SECTION"]
    fixed_costs:    List[float] = [float(e.split()[1]) for e in fixed_cost_entries] \
                                  or [0.0] * len(capacities)
    has_explicit_fixed_costs = len(fixed_cost_entries) > 0
    uses_scaled_fixed_costs = (
        has_explicit_fixed_costs
        and "FSMF" in metadata.get("NAME", source_name).upper()
        and len(variable_costs) > 0
        and min(variable_costs) >= 10.0
        and min(fixed_costs) >= 1000.0
    )
    cost_scale_factor = 100.0 if uses_scaled_fixed_costs else 1.0
    if cost_scale_factor != 1.0:
        variable_costs = [v / cost_scale_factor for v in variable_costs]
        fixed_costs = [f / cost_scale_factor for f in fixed_costs]

    if len(raw_demands) != dimension:
        raise ValueError("DEMAND_SECTION ile DIMENSION uyusmuyor")
    if len(capacities) != len(variable_costs):
        raise ValueError("Kapasite ve maliyet satir sayilari ayni olmali")
    if len(capacities) != len(fixed_costs):
        raise ValueError("Kapasite ve fixed cost satir sayilari ayni olmali")

    order      = [depot_zero_based] + [i for i in range(dimension) if i != depot_zero_based]
    old_to_new = {old: new for new, old in enumerate(order)}

    if edge_weight_type == "EXPLICIT":
        flat_values: List[float] = []
        for entry in sections["EDGE_WEIGHT_SECTION"]:
            flat_values.extend(float(t) for t in entry.split())
        raw_dist = parse_explicit_edge_weight_matrix(flat_values, dimension, edge_weight_format)
        coords   = [(0.0, 0.0)] * dimension
    else:
        if len(raw_coords) != dimension:
            raise ValueError("NODE_COORD_SECTION ile DIMENSION uyusmuyor")
        raw_coord_list = [raw_coords[i] for i in range(dimension)]
        raw_dist       = build_distance_matrix_from_coords(raw_coord_list, edge_weight_type)
        coords         = [raw_coords[old] for old in order]

    demands    = [raw_demands[old] for old in order]; demands[0] = 0.0
    dist       = [[raw_dist[oi][oj] for oj in order] for oi in order]

    use_benchmark_compatible_hd_costs = benchmark_compatible_hfvrp_costs and not has_explicit_fixed_costs

    if use_benchmark_compatible_hd_costs:
        vehicles = [
            Vehicle(vehicle_id=i, capacity=capacities[i], cost_per_km=1.0,
                    fixed_cost=variable_costs[i], speed=1.0)
            for i in range(len(capacities))
        ]
        cost_model_name = "benchmark_compatible_hd"
    else:
        vehicles = [
            Vehicle(vehicle_id=i, capacity=capacities[i], cost_per_km=variable_costs[i],
                    fixed_cost=fixed_costs[i], speed=1.0)
            for i in range(len(capacities))
        ]
        cost_model_name = "explicit_fixed_and_distance"

    problem = HCVRPProblem(
        coords=coords, demands=demands, vehicles=vehicles,
        time_windows=[(0.0, float("inf"))] * dimension,
        service_times=[0.0] * dimension,
    )
    problem.dist = dist
    problem.original_vrplib_name      = metadata.get("NAME", source_name)  # type: ignore
    problem.original_vrplib_depot_id  = depot_vrplib_id                    # type: ignore
    problem.original_to_internal_node = old_to_new                         # type: ignore
    problem.cost_model_name           = cost_model_name                    # type: ignore
    problem.has_explicit_fixed_costs  = has_explicit_fixed_costs           # type: ignore
    problem.cost_scale_factor         = cost_scale_factor                  # type: ignore
    return problem


def load_hfvrp_instance_from_vrplib(
        file_path: "str | Path",
        benchmark_compatible_hfvrp_costs: bool = True
) -> "HCVRPProblem":
    path = Path(file_path)
    if not path.exists():        raise FileNotFoundError(f"Dataset bulunamadi: {path}")
    if path.stat().st_size == 0: raise ValueError(f"Dataset bos: {path}")
    return _parse_vrplib_lines(path.read_text(encoding="utf-8").splitlines(),
                                path.stem, benchmark_compatible_hfvrp_costs)


# ==============================================================================
#  YARDIMCI FONKSİYONLAR
# ==============================================================================

def normalize_route(route: Route) -> Route:
    if route and route[0] == 0 and route[-1] == 0 and 0 not in route[1:-1]:
        return route[:]
    return [0] + [n for n in route if n != 0] + [0]


def _ensure_normalized(route: Route) -> Route:
    if route and route[0] == 0 and route[-1] == 0 and 0 not in route[1:-1]:
        return route
    return [0] + [n for n in route if n != 0] + [0]


def clone_routes(routes: Route_matrix) -> Route_matrix:
    return [r[:] for r in routes]

def extract_customers(routes: Route_matrix) -> List[int]:
    return [n for route in routes for n in route if n != 0]

def route_core(route: Route) -> List[int]:
    return [n for n in route if n != 0]


def internal_node_to_original(problem: HCVRPProblem, node: int) -> int:
    if node == 0:
        return int(getattr(problem, "original_vrplib_depot_id", 1))
    mapping = getattr(problem, "original_to_internal_node", None)
    if not mapping:
        return node + 1
    for original, internal in mapping.items():
        if internal == node:
            return int(original) + 1
    return node + 1


def route_to_original_ids(problem: HCVRPProblem, route: Route) -> Route:
    return [internal_node_to_original(problem, n) for n in route]


def materialize_vehicle_ids(problem: HCVRPProblem, type_ids: List[int]) -> List[int]:
    grouped: Dict[Tuple[float, float, float, float], List[int]] = {}
    order: List[Tuple[float, float, float, float]] = []
    for vehicle in problem.vehicles:
        key = (vehicle.capacity, vehicle.cost_per_km, vehicle.fixed_cost, vehicle.speed)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(vehicle.vehicle_id)
    type_to_vehicle_ids: Dict[int, List[int]] = {
        idx: grouped[key][:]
        for idx, key in enumerate(order)
    }
    used_counts: Dict[int, int] = {}
    realized: List[int] = []
    for type_id in type_ids:
        idx = used_counts.get(type_id, 0)
        used_counts[type_id] = idx + 1
        candidates = type_to_vehicle_ids.get(type_id, [])
        realized.append(candidates[idx] if idx < len(candidates) else type_id)
    return realized


def build_bloodhound_vrp_style_output(problem: HCVRPProblem, best_state: "SolutionState") -> Dict:
    output_node_ids = getattr(problem, "output_node_ids", None)
    routes = [route[:] for route in best_state.routes]
    if isinstance(output_node_ids, list) and len(output_node_ids) == problem.n_nodes:
        routes = [[int(output_node_ids[node]) for node in route] for route in best_state.routes]
    return {
        "Feasible": bool(best_state.feasible),
        "Total cost": round(float(best_state.total_cost), 4),
        "Vehicle IDs": materialize_vehicle_ids(problem, best_state.vehicle_ids),
        "Route loads": best_state.route_loads[:],
        "Route distances": best_state.route_distances[:],
        "Route times": best_state.route_times[:],
        "Route costs": best_state.route_costs[:],
        "Routes": routes,
    }


def build_problem_from_app_payload(payload: Dict) -> Tuple[HCVRPProblem, Dict]:
    locations = payload.get("locations")
    distance_matrix = payload.get("distance_matrix")
    time_matrix = payload.get("time_matrix")
    demands_rows = payload.get("demands", [])
    fleet_rows = payload.get("fleet", [])

    if not isinstance(locations, list) or not locations:
        raise ValueError("locations gerekli.")
    if not isinstance(distance_matrix, list) or not distance_matrix:
        raise ValueError("distance_matrix gerekli.")
    if not isinstance(time_matrix, list) or not time_matrix:
        raise ValueError("time_matrix gerekli.")
    if not isinstance(fleet_rows, list) or not fleet_rows:
        raise ValueError("fleet gerekli.")

    n_nodes = len(locations)
    if len(distance_matrix) != n_nodes or any(len(row) != n_nodes for row in distance_matrix):
        raise ValueError("distance_matrix boyutu locations ile ayni olmali.")
    if len(time_matrix) != n_nodes or any(len(row) != n_nodes for row in time_matrix):
        raise ValueError("time_matrix boyutu locations ile ayni olmali.")

    coords: List[Point] = []
    node_ids: List[int] = []
    for idx, row in enumerate(locations):
        node_ids.append(int(row.get("node_id", idx)))
        lat = row.get("lat")
        lon = row.get("lon")
        coords.append((float(lat) if lat is not None else float(idx), float(lon) if lon is not None else 0.0))

    demand_map = {int(row.get("node_id")): float(row.get("demand", 0.0)) for row in demands_rows}
    demands = [0.0] * n_nodes
    for idx, row in enumerate(locations):
        if bool(row.get("is_depot", False)):
            demands[idx] = 0.0
        else:
            demands[idx] = float(demand_map.get(node_ids[idx], row.get("demand", 0.0)))
    if demands:
        demands[0] = 0.0

    tw_map = {
        int(row.get("node_id")): (float(row.get("start_min", 0.0)), float(row.get("end_min", float("inf"))))
        for row in payload.get("time_windows", [])
    }
    time_windows: List[Tuple[float, float]] = []
    for idx, row in enumerate(locations):
        if node_ids[idx] in tw_map:
            time_windows.append(tw_map[node_ids[idx]])
        else:
            time_windows.append((float(row.get("time_window_start_min", 0.0)),
                                 float(row.get("time_window_end_min", float("inf")))))

    service_map = {
        int(row.get("node_id")): float(row.get("duration_min", 0.0))
        for row in payload.get("service_times", [])
    }
    service_times = [
        float(service_map.get(node_ids[idx], row.get("service_time_min", 0.0)))
        for idx, row in enumerate(locations)
    ]

    vehicles: List[Vehicle] = []
    vehicle_id = 0
    output_fleet: List[Dict] = []
    for row in fleet_rows:
        count = int(row.get("count", 1))
        capacity = float(row.get("capacity", 0.0))
        fixed_cost = float(row.get("fixed_cost", 0.0))
        cost_per_km = float(row.get("cost_per_km", 0.0))
        speed = float(row.get("speed_kmh", 1.0) or 1.0)
        for _ in range(count):
            vehicles.append(
                Vehicle(
                    vehicle_id=vehicle_id,
                    capacity=capacity,
                    cost_per_km=cost_per_km,
                    fixed_cost=fixed_cost,
                    speed=speed,
                )
            )
            vehicle_id += 1
        output_fleet.append(
            {
                "vehicle_type_id": row.get("vehicle_type_id"),
                "label": row.get("label"),
                "count": count,
                "capacity": capacity,
                "fixed_cost": fixed_cost,
                "cost_per_km": cost_per_km,
                "speed_kmh": speed,
            }
        )

    solver_config = payload.get("solver_config") or {}
    solver_params = solver_config.get("params") if isinstance(solver_config, dict) else {}
    max_route_time_min = None
    if isinstance(solver_params, dict):
        raw_limit = solver_params.get("max_route_time_min")
        if raw_limit is not None:
            max_route_time_min = float(raw_limit)

    problem = HCVRPProblem(
        coords=coords,
        demands=demands,
        vehicles=vehicles,
        time_windows=time_windows,
        service_times=service_times,
        distance_matrix=[[float(x) for x in row] for row in distance_matrix],
        time_matrix=[[float(x) for x in row] for row in time_matrix],
        max_route_time_min=max_route_time_min,
    )
    problem.output_node_ids = node_ids  # type: ignore[attr-defined]
    return problem, {"locations": locations, "fleet": output_fleet, "solver_config": solver_config}

def route_has_duplicate_customer(route: Route) -> bool:
    customers = route_core(route)
    return len(customers) != len(set(customers))

def build_edge_signature_from_routes(routes: Route_matrix) -> Set[Edge]:
    sig: Set[Edge] = set()
    for route in routes:
        nr = _ensure_normalized(route)
        for i in range(len(nr) - 1):
            a, b = nr[i], nr[i + 1]
            sig.add((a, b) if a < b else (b, a))
    return sig

def max_region_similarity_routes(routes: Route_matrix, closed_regions: List[Set[Edge]]) -> float:
    if not closed_regions: return 0.0
    current_sig = build_edge_signature_from_routes(routes)
    best_sim = 0.0
    for sig in closed_regions:
        if not sig: continue
        sim = len(current_sig & sig) / len(sig)
        if sim > best_sim: best_sim = sim
    return best_sim


# ==============================================================================
#  ARAÇ TİPİ ERİŞİMİ
# ==============================================================================

def get_vehicle_type_by_id(problem: HCVRPProblem, type_id: int) -> VehicleType:
    return problem.vehicle_types[type_id]


def _type_usage_from_ids(vehicle_ids: List[int]) -> Dict[int, int]:
    usage: Dict[int, int] = {}
    for t_id in vehicle_ids:
        usage[t_id] = usage.get(t_id, 0) + 1
    return usage


def _can_open_more(type_usage: Dict[int, int], vt: VehicleType) -> bool:
    return type_usage.get(vt.type_id, 0) < vt.max_count


# ==============================================================================
#  SO: STRATEGIC OSCILLATION CONTROLLER
# ==============================================================================

@dataclass
class OscillationController:
    """
    Strategic Oscillation — sadece kapasite kısıtını soft yapar.
    Zaman pencereleri her zaman hard kalır.

    Faz mantığı:
      ENFORCE → normal hard kapasite (orijinal davranış)
      RELAX   → kapasite aşımı = ceza (infeasible bölge keşfi)

    free_search_phase içinde her adımda .step() çağrılır;
    periyot dolunca faz otomatik değişir.
    """
    cap_penalty_weight: float = field(default_factory=lambda: float(ALGO_CONFIG["so_cap_penalty_weight"]))
    relax_period:       int   = field(default_factory=lambda: int(ALGO_CONFIG["so_relax_period"]))
    enforce_period:     int   = field(default_factory=lambda: int(ALGO_CONFIG["so_enforce_period"]))
    phase:              str   = field(default="ENFORCE", init=False)
    _steps:             int   = field(default=0,         init=False, repr=False)
    _relax_entered:     int   = field(default=0,         init=False, repr=False)  # istatistik
    _enforce_entered:   int   = field(default=0,         init=False, repr=False)  # istatistik

    def is_relax(self) -> bool:
        return self.phase == "RELAX"

    def set_phase(self, phase: str) -> None:
        """Faz zorla değiştirilir; sayaç sıfırlanır."""
        if phase not in ("RELAX", "ENFORCE"):
            raise ValueError(f"Geçersiz faz: {phase}")
        self.phase  = phase
        self._steps = 0
        if phase == "RELAX":
            self._relax_entered += 1
        else:
            self._enforce_entered += 1

    def toggle(self) -> None:
        """Fazı tersine çevirir."""
        new_phase = "RELAX" if self.phase == "ENFORCE" else "ENFORCE"
        self.set_phase(new_phase)

    def step(self) -> None:
        """
        free_search_phase her iterasyonunun başında çağrılır.
        Aktif periyot dolduğunda faz otomatik değişir.
        """
        self._steps += 1
        period = self.relax_period if self.phase == "RELAX" else self.enforce_period
        if self._steps >= period:
            self.toggle()

    def stats(self) -> Dict[str, object]:
        return {
            "phase":           self.phase,
            "steps_in_phase":  self._steps,
            "relax_entered":   self._relax_entered,
            "enforce_entered": self._enforce_entered,
            "cap_pw":          self.cap_penalty_weight,
        }


# SO: Modül düzeyinde aktif oscillation — None ise devre dışı (hard constraints).
# free_search_phase sırasında set_active_oscillation() ile aktifleştirilir,
# hunt ve LS aşamalarında None yapılır.
_ACTIVE_OSCILLATION: Optional[OscillationController] = None


def set_active_oscillation(ctrl: Optional[OscillationController]) -> None:
    """Aktif oscillation controller'ı ayarla (None → hard mod)."""
    global _ACTIVE_OSCILLATION
    _ACTIVE_OSCILLATION = ctrl


def get_active_oscillation() -> Optional[OscillationController]:
    return _ACTIVE_OSCILLATION


# ==============================================================================
#  ROTA DEĞERLENDIRME
# ==============================================================================

def evaluate_route_for_vehicle(
        problem: HCVRPProblem,
        route: Route,
        vehicle: VehicleType
) -> Tuple[bool, float, float, float, float]:
    nr  = _ensure_normalized(route)
    # SO: aktif oscillation varsa ve RELAX fazındaysa soft cap kullan
    osc      = _ACTIVE_OSCILLATION
    use_soft = (osc is not None and osc.is_relax())

    if NUMBA_AVAILABLE and np is not None:
        nr_np = _route_to_numpy(nr)
        max_route_time_min = getattr(problem, "max_route_time_min", None)
        mrm = -1.0 if max_route_time_min is None else float(max_route_time_min)

        if use_soft:
            # SO: soft-cap numba kernel
            route_ok, load, dist, route_time, cost = _evaluate_route_kernel_soft_cap_numba(
                nr_np,
                problem.dist_np, problem.demands_np,
                problem.time_window_open_np, problem.time_window_close_np,
                problem.service_times_np,
                vehicle.capacity, vehicle.cost_per_km, vehicle.fixed_cost, vehicle.speed,
                mrm,
                osc.cap_penalty_weight,
            )
        else:
            route_ok, load, dist, route_time, cost = _evaluate_route_kernel_numba(
                nr_np,
                problem.dist_np, problem.demands_np,
                problem.time_window_open_np, problem.time_window_close_np,
                problem.service_times_np,
                vehicle.capacity, vehicle.cost_per_km, vehicle.fixed_cost, vehicle.speed,
                mrm,
            )
        return bool(route_ok), float(load), float(dist), float(route_time), float(cost)

    # Python yolu
    load = problem.route_load(nr)
    dist = problem.route_distance(nr)
    cost = vehicle.fixed_cost + dist * vehicle.cost_per_km

    if use_soft:
        # SO: kapasite aşımı → ceza, False dönme
        if load > vehicle.capacity:
            cost += osc.cap_penalty_weight * (load - vehicle.capacity)
    else:
        if load > vehicle.capacity:
            return False, load, dist, 0.0, cost

    # Zaman pencereleri her zaman hard
    current_time = 0.0
    for i in range(1, len(nr) - 1):
        prev_node = nr[i - 1]; node = nr[i]
        current_time += problem.travel_time(prev_node, node, vehicle)
        window_open, window_close = problem.time_windows[node]
        if current_time < window_open:  current_time = window_open
        if current_time > window_close: return False, load, dist, current_time, cost
        if node != 0: current_time += problem.service_times[node]
    if len(nr) >= 2:
        current_time += problem.travel_time(nr[-2], nr[-1], vehicle)
    max_route_time_min = getattr(problem, "max_route_time_min", None)
    if max_route_time_min is not None and current_time > max_route_time_min:
        return False, load, dist, current_time, cost
    return True, load, dist, current_time, cost


def evaluate_solution(
        problem: HCVRPProblem,
        routes: Route_matrix,
        vehicle_ids: List[int],
        infeasible_penalty: float = 1e12
) -> "SolutionState":
    if len(routes) != len(vehicle_ids):
        raise ValueError("Routes ve vehicle_ids uzunluğu aynı olmalı")

    normalized_routes = [_ensure_normalized(r) for r in routes]
    normalized_route_arrays = None
    covered_customers = None
    if NUMBA_AVAILABLE and np is not None:
        normalized_route_arrays = _routes_to_numpy(normalized_routes)
        covered_customers = np.zeros(problem.n_nodes, dtype=np.uint8)

    # SO: aktif oscillation → soft cap ağırlığı belirle
    _osc  = _ACTIVE_OSCILLATION
    cap_pw = _osc.cap_penalty_weight if (_osc is not None and _osc.is_relax()) else 0.0
    max_route_time_min = getattr(problem, "max_route_time_min", None)
    mrm = -1.0 if max_route_time_min is None else float(max_route_time_min)

    route_loads:     List[float] = []
    route_distances: List[float] = []
    route_times:     List[float] = []
    route_costs:     List[float] = []
    feasible = True

    type_counts = Counter(vehicle_ids)
    for type_id, count in type_counts.items():
        if type_id < 0 or type_id >= len(problem.vehicle_types):
            feasible = False
        elif count > problem.vehicle_types[type_id].max_count:
            feasible = False

    for route_idx, (route, v_id) in enumerate(zip(normalized_routes, vehicle_ids)):
        if v_id < 0 or v_id >= len(problem.vehicle_types):
            raise ValueError(f"Gecersiz type_id: {v_id}")
        vt = problem.vehicle_types[v_id]

        if NUMBA_AVAILABLE and np is not None:
            route_arr = normalized_route_arrays[route_idx]
            if _route_has_duplicate_customer_numba(route_arr, problem.n_nodes):
                feasible = False
            _mark_covered_customers_numba(route_arr, covered_customers)

            # SO: RELAX modunda soft-cap kernel
            if cap_pw > 0.0:
                route_ok, load, dist, route_time, cost = _evaluate_route_kernel_soft_cap_numba(
                    route_arr,
                    problem.dist_np, problem.demands_np,
                    problem.time_window_open_np, problem.time_window_close_np,
                    problem.service_times_np,
                    vt.capacity, vt.cost_per_km, vt.fixed_cost, vt.speed,
                    mrm, cap_pw,
                )
            else:
                route_ok, load, dist, route_time, cost = _evaluate_route_kernel_numba(
                    route_arr,
                    problem.dist_np, problem.demands_np,
                    problem.time_window_open_np, problem.time_window_close_np,
                    problem.service_times_np,
                    vt.capacity, vt.cost_per_km, vt.fixed_cost, vt.speed,
                    mrm,
                )
            route_ok   = bool(route_ok)
            load       = float(load)
            dist       = float(dist)
            route_time = float(route_time)
            cost       = float(cost)
        else:
            if route_has_duplicate_customer(route):
                feasible = False
            route_ok, load, dist, route_time, cost = evaluate_route_for_vehicle(problem, route, vt)

        if not route_ok:
            feasible = False
        route_loads.append(load); route_distances.append(dist)
        route_times.append(route_time); route_costs.append(cost)

    if NUMBA_AVAILABLE and np is not None:
        if not bool(np.all(covered_customers[1:])):
            feasible = False
    elif sorted(extract_customers(normalized_routes)) != problem.customer_ids:
        feasible = False

    total_cost = sum(route_costs)
    if not feasible: total_cost += infeasible_penalty

    # SO: hard_feasible — kapasite dahil TÜM hard kısıtlar (oscillation bağımsız).
    # RELAX modunda feasible=True olabilir ama cap aşımı varsa hard_feasible=False.
    hard_feasible = feasible
    if hard_feasible and cap_pw > 0.0:
        for rl, v_id_chk in zip(route_loads, vehicle_ids):
            if 0 <= v_id_chk < len(problem.vehicle_types):
                if rl > problem.vehicle_types[v_id_chk].capacity + 1e-9:
                    hard_feasible = False
                    break

    state = SolutionState(
        routes=normalized_routes, vehicle_ids=vehicle_ids[:],
        route_loads=route_loads, route_distances=route_distances,
        route_times=route_times, route_costs=route_costs,
        total_cost=total_cost, feasible=feasible,
        hard_feasible=hard_feasible,   # SO
    )
    state._route_arrays = normalized_route_arrays
    return state


# ==============================================================================
#  ARAÇ ATAma (her zaman hard cap — _ACTIVE_OSCILLATION None olduğunda çağrılır)
# ==============================================================================

def cheapest_feasible_vehicle_type(
        problem: HCVRPProblem,
        required_load: float,
        type_usage: Dict[int, int],
        route: Optional[Route] = None
) -> Optional[int]:
    candidates = []
    for vt in problem.vehicle_types:
        if not _can_open_more(type_usage, vt): continue
        if vt.capacity < required_load:        continue
        if route is not None:
            route_ok, _, _, _, _ = evaluate_route_for_vehicle(problem, route, vt)
            if not route_ok: continue
        candidates.append(vt)
    if not candidates: return None
    best = min(candidates, key=lambda v: (v.fixed_cost, v.cost_per_km, v.capacity))
    return best.type_id


def assign_best_feasible_vehicle_for_tour(
        problem: HCVRPProblem,
        route: Route,
        type_usage: Dict[int, int]
) -> Optional[int]:
    nr = _ensure_normalized(route)
    if NUMBA_AVAILABLE and np is not None:
        usage_counts = np.zeros(len(problem.vehicle_types), dtype=np.int64)
        for type_id, count in type_usage.items():
            usage_counts[type_id] = count
        # Araç ataması her zaman hard — numba kernel doğrudan çağrılır
        best_type_id, _, _ = _best_vehicle_type_for_route_numba(
            _route_to_numpy(nr),
            problem.dist_np, problem.demands_np,
            problem.time_window_open_np, problem.time_window_close_np,
            problem.service_times_np,
            problem.vehicle_type_capacities_np, problem.vehicle_type_cost_per_km_np,
            problem.vehicle_type_fixed_costs_np, problem.vehicle_type_speeds_np,
            problem.vehicle_type_max_counts_np, usage_counts,
            -1, False,
            -1.0 if getattr(problem, "max_route_time_min", None) is None
                 else float(problem.max_route_time_min),
        )
        return None if best_type_id < 0 else int(best_type_id)

    load = problem.route_load(nr)
    candidates = []
    for vt in problem.vehicle_types:
        if not _can_open_more(type_usage, vt): continue
        if vt.capacity < load:                  continue
        route_ok, _, rd, _, rc = evaluate_route_for_vehicle(problem, nr, vt)
        if route_ok: candidates.append((rc, rd, vt.capacity, vt.type_id))
    if not candidates: return None
    return min(candidates)[3]


def assign_best_vehicle_for_existing_route(
        problem: HCVRPProblem,
        route: Route,
        current_type_id: int,
        type_usage: Dict[int, int]
) -> Optional[Tuple[int, float, float]]:
    nr = _ensure_normalized(route)
    if NUMBA_AVAILABLE and np is not None:
        usage_counts = np.zeros(len(problem.vehicle_types), dtype=np.int64)
        for type_id, count in type_usage.items():
            usage_counts[type_id] = count
        best_type_id, best_cost, best_dist = _best_vehicle_type_for_route_numba(
            _route_to_numpy(nr),
            problem.dist_np, problem.demands_np,
            problem.time_window_open_np, problem.time_window_close_np,
            problem.service_times_np,
            problem.vehicle_type_capacities_np, problem.vehicle_type_cost_per_km_np,
            problem.vehicle_type_fixed_costs_np, problem.vehicle_type_speeds_np,
            problem.vehicle_type_max_counts_np, usage_counts,
            current_type_id, True,
            -1.0 if getattr(problem, "max_route_time_min", None) is None
                 else float(problem.max_route_time_min),
        )
        if best_type_id < 0:
            return None
        return int(best_type_id), float(best_cost), float(best_dist)

    candidates = []
    for vt in problem.vehicle_types:
        if vt.type_id != current_type_id:
            if not _can_open_more(type_usage, vt): continue
        route_ok, _, rd, _, rc = evaluate_route_for_vehicle(problem, nr, vt)
        if route_ok: candidates.append((rc, rd, vt.capacity, vt.type_id))
    if not candidates: return None
    bc, bd, _, bt = min(candidates)
    return bt, bc, bd


def can_append_customer_to_route(
        problem: HCVRPProblem, route: Route, customer: int, vehicle: VehicleType
) -> bool:
    nr = _ensure_normalized(route)
    if problem.route_load(nr) + problem.demands[customer] > vehicle.capacity:
        return False
    pos = best_append_position_by_distance(problem, nr, customer)
    candidate = nr[:]
    candidate.insert(pos, customer)
    route_ok, _, _, _, _ = evaluate_route_for_vehicle(problem, candidate, vehicle)
    return route_ok


def best_append_position_by_distance(
        problem: HCVRPProblem, route: Route, customer: int
) -> int:
    nr = _ensure_normalized(route)
    best_pos = 1; best_delta = float("inf")
    for i in range(len(nr) - 1):
        a = nr[i]; b = nr[i + 1]
        delta = problem.dist[a][customer] + problem.dist[customer][b] - problem.dist[a][b]
        if delta < best_delta: best_delta = delta; best_pos = i + 1
    return best_pos


def find_best_route_insertion(
        problem: HCVRPProblem,
        routes: Route_matrix,
        vehicle_ids: List[int],
        type_usage: Dict[int, int],
        customer: int
) -> Optional[Tuple]:
    best_choice = None
    route_centroids = compute_route_centroids(problem, routes) if routes else []
    route_arrays = _routes_to_numpy(routes) if (routes and NUMBA_AVAILABLE and np is not None) else None
    for r_idx in select_candidate_route_indices(
            problem, routes, customer,
            max_candidates=max(1, min(len(routes), int(ALGO_CONFIG["granular_neighbor_k"]) // 2 or 1)),
            route_centroids=route_centroids,
            route_arrays=route_arrays) if routes else []:
        route = routes[r_idx]
        current_type_id = vehicle_ids[r_idx]
        current_type    = get_vehicle_type_by_id(problem, current_type_id)
        route_ok, _, _, _, current_cost = evaluate_route_for_vehicle(problem, route, current_type)
        if not route_ok: continue
        pos, _          = choose_best_insertion_position(problem, route, customer)
        candidate_route = _ensure_normalized(route)[:]; candidate_route.insert(pos, customer)
        best_vehicle    = assign_best_vehicle_for_existing_route(
            problem, candidate_route, current_type_id=current_type_id, type_usage=type_usage
        )
        if best_vehicle is None: continue
        new_type_id, new_cost, _ = best_vehicle
        delta_cost = new_cost - current_cost
        choice_key = (delta_cost, new_cost, r_idx, pos, new_type_id)
        if best_choice is None or choice_key < best_choice[0]:
            best_choice = (choice_key, (r_idx, pos, new_type_id, delta_cost))
    return None if best_choice is None else best_choice[1]


# ==============================================================================
#  FEASIBLE ÇÖZÜM ÜRETME
# ==============================================================================

def generate_feasible_solution(
        problem: HCVRPProblem,
        sort_by_demands_desc: bool = True,
        randomize_ties: bool = True,
        max_attempts: int = 50
) -> "SolutionState":
    customer_list = problem.customer_ids[:]
    for _ in range(max_attempts):
        customers = customer_list[:]
        if sort_by_demands_desc:
            if randomize_ties: random.shuffle(customers)
            customers.sort(key=lambda c: problem.demands[c], reverse=True)
        else:
            random.shuffle(customers)

        routes:      Route_matrix   = []
        vehicle_ids: List[int]      = []
        type_usage:  Dict[int, int] = {}
        success = True

        for customer in customers:
            placed      = False
            best_choice = find_best_route_insertion(
                problem, routes, vehicle_ids, type_usage, customer
            )
            if best_choice is not None:
                r_idx, pos, new_type_id, _ = best_choice
                old_type_id = vehicle_ids[r_idx]
                nr = _ensure_normalized(routes[r_idx])[:]
                nr.insert(pos, customer)
                routes[r_idx] = nr
                vehicle_ids[r_idx] = new_type_id
                if old_type_id != new_type_id:
                    type_usage[old_type_id] -= 1
                    if type_usage[old_type_id] <= 0:
                        del type_usage[old_type_id]
                    type_usage[new_type_id] = type_usage.get(new_type_id, 0) + 1
                placed = True

            if not placed:
                new_type_id = cheapest_feasible_vehicle_type(
                    problem, required_load=problem.demands[customer],
                    type_usage=type_usage, route=[0, customer, 0]
                )
                if new_type_id is None: success = False; break
                routes.append([0, customer, 0])
                vehicle_ids.append(new_type_id)
                type_usage[new_type_id] = type_usage.get(new_type_id, 0) + 1

        if not success: continue
        state = evaluate_solution(problem, routes, vehicle_ids)
        if state.feasible: return state

    raise RuntimeError("Initial feasible solution uretilemedi")


# ==============================================================================
#  WOLF
# ==============================================================================

@dataclass
class Wolf:
    problem:            HCVRPProblem
    state:              "SolutionState"
    best_state:         "SolutionState"
    blood:              float = 0.0
    quality_score:      float = 0.0
    best_quality_score: float = 0.0
    delta_history:      List[float] = field(default_factory=list)

    @classmethod
    def create_random(cls, problem: HCVRPProblem) -> "Wolf":
        init_state = generate_feasible_solution(problem)
        return cls(problem=problem, state=init_state, best_state=init_state,
                   blood=0.0, quality_score=0.0, best_quality_score=0.0, delta_history=[])

    def clone_state(self, state: "SolutionState") -> "SolutionState":
        return clone_solution_state(state)

    def update_if_better(self, candidate_state: "SolutionState"):
        if candidate_state.total_cost < self.state.total_cost:
            self.state = self.clone_state(candidate_state)
        # SO: best_state yalnız hard_feasible (kapasite dahil) çözümler alır.
        # RELAX sırasında üretilen cap-ihlalli çözümler best_state'e girmez.
        if candidate_state.hard_feasible and candidate_state.total_cost < self.best_state.total_cost:
            self.best_state = self.clone_state(candidate_state)


def initialize_wolves(problem: HCVRPProblem, num_wolves: int) -> List[Wolf]:
    return [Wolf.create_random(problem) for _ in range(num_wolves)]


# ==============================================================================
#  KALİTE / PUAN
# ==============================================================================

def minmax_normalize_costs_to_quality(costs: List[float]) -> List[float]:
    if not costs: return []
    c_min = min(costs); c_max = max(costs)
    if abs(c_max - c_min) < 1e-12: return [1.0] * len(costs)
    return [max(0.0, min(1.0, (c_max - c) / (c_max - c_min))) for c in costs]

def minmax_normalize_values(values: List[float]) -> List[float]:
    if not values: return []
    v_min = min(values); v_max = max(values)
    if abs(v_max - v_min) < 1e-12: return [1.0] * len(values)
    return [(v - v_min) / (v_max - v_min) for v in values]

def update_population_quality_scores(wolves: List[Wolf]):
    cq = minmax_normalize_costs_to_quality([w.state.total_cost for w in wolves])
    for w, q in zip(wolves, cq): w.quality_score = q
    bq = minmax_normalize_costs_to_quality([w.best_state.total_cost for w in wolves])
    for w, q in zip(wolves, bq): w.best_quality_score = q

def population_cost_stats(wolves: List[Wolf]) -> Tuple[float, float, float]:
    costs = [w.state.total_cost for w in wolves]
    return min(costs), sum(costs) / len(costs), max(costs)

def robust_scale_from_history(values: List[float], fallback: float = 1.0) -> float:
    if not values: return fallback
    vals = sorted(abs(v) for v in values)
    m    = len(vals)
    med  = vals[m // 2] if m % 2 == 1 else 0.5 * (vals[m//2-1] + vals[m//2])
    return max(med, 1e-9)

def register_delta_and_get_scaled_delta(wolf: Wolf, raw_delta: float, max_history: int = 50) -> float:
    wolf.delta_history.append(raw_delta)
    if len(wolf.delta_history) > max_history: wolf.delta_history.pop(0)
    return raw_delta / robust_scale_from_history(wolf.delta_history)

def clone_solution_state(state: "SolutionState") -> "SolutionState":
    candidate = SolutionState(
        routes=clone_routes(state.routes), vehicle_ids=state.vehicle_ids[:],
        route_loads=state.route_loads[:], route_distances=state.route_distances[:],
        route_times=state.route_times[:], route_costs=state.route_costs[:],
        total_cost=state.total_cost, feasible=state.feasible,
        hard_feasible=state.hard_feasible,   # SO
    )
    if state._route_centroids is not None:
        candidate._route_centroids = state._route_centroids[:]
    if state._route_cores is not None:
        candidate._route_cores = {k: v[:] for k, v in state._route_cores.items()}
    if state._route_core_sets is not None:
        candidate._route_core_sets = {k: set(v) for k, v in state._route_core_sets.items()}
    if state._route_spreads is not None:
        candidate._route_spreads = state._route_spreads.copy()
    if state._route_outliers is not None:
        candidate._route_outliers = {k: v[:] for k, v in state._route_outliers.items()}
    if state._route_badness is not None:
        candidate._route_badness = state._route_badness.copy()
    candidate._pathology_flag = state._pathology_flag
    return candidate


def _invalidate_state_route_caches(state: "SolutionState", route_indices: Optional[List[int]] = None) -> None:
    state._route_arrays = None
    if route_indices is None:
        state._route_cores = None
        state._route_core_sets = None
        state._route_centroids = None
        state._route_spreads = None
        state._route_outliers = None
        state._route_badness = None
        state._pathology_flag = None
        return
    touched = set(route_indices)
    if state._route_cores is not None:
        for idx in touched:
            state._route_cores.pop(idx, None)
    if state._route_core_sets is not None:
        for idx in touched:
            state._route_core_sets.pop(idx, None)
    if state._route_centroids is not None:
        state._route_centroids = None
    if state._route_spreads is not None:
        for idx in touched:
            state._route_spreads.pop(idx, None)
    if state._route_outliers is not None:
        for key in list(state._route_outliers.keys()):
            if key[0] in touched:
                del state._route_outliers[key]
    if state._route_badness is not None:
        for idx in touched:
            state._route_badness.pop(idx, None)
    state._pathology_flag = None


def _state_route_arrays(state: "SolutionState"):
    if state._route_arrays is None:
        state._route_arrays = _routes_to_numpy(state.routes)
    return state._route_arrays


def _state_route_core(state: "SolutionState", route_idx: int) -> List[int]:
    if state._route_cores is None:
        state._route_cores = {}
    cached = state._route_cores.get(route_idx)
    if cached is None:
        cached = route_core(state.routes[route_idx])
        state._route_cores[route_idx] = cached
    return cached


def _state_route_core_set(state: "SolutionState", route_idx: int) -> Set[int]:
    if state._route_core_sets is None:
        state._route_core_sets = {}
    cached = state._route_core_sets.get(route_idx)
    if cached is None:
        cached = set(_state_route_core(state, route_idx))
        state._route_core_sets[route_idx] = cached
    return cached


def _state_route_centroids(problem: HCVRPProblem, state: "SolutionState") -> List[Point]:
    if state._route_centroids is None:
        route_arrays = _state_route_arrays(state)
        centroids: List[Point] = []
        for route, route_arr in zip(state.routes, route_arrays):
            core = route_core(route)
            if not core:
                centroids.append(problem.coords[0])
                continue
            if NUMBA_AVAILABLE and np is not None:
                depot_x, depot_y = problem.coords[0]
                cx, cy = _compute_route_centroid_numba(route_arr, problem.coords_np, depot_x, depot_y)
                centroids.append((float(cx), float(cy)))
            else:
                sx = sy = 0.0
                for customer in core:
                    x, y = problem.coords[customer]
                    sx += x; sy += y
                inv = 1.0 / len(core)
                centroids.append((sx * inv, sy * inv))
        state._route_centroids = centroids
    return state._route_centroids


def _state_route_spread(problem: HCVRPProblem, state: "SolutionState", route_idx: int) -> float:
    if state._route_spreads is None:
        state._route_spreads = {}
    cached = state._route_spreads.get(route_idx)
    if cached is None:
        route_arr = None
        if NUMBA_AVAILABLE and np is not None:
            route_arr = _state_route_arrays(state)[route_idx]
        cached = route_spread_value(problem, state.routes[route_idx], route_arr=route_arr)
        state._route_spreads[route_idx] = cached
    return cached


def _state_route_outliers(
        problem: HCVRPProblem, state: "SolutionState", route_idx: int, max_customers: int
) -> List[int]:
    if state._route_outliers is None:
        state._route_outliers = {}
    key = (route_idx, max_customers)
    cached = state._route_outliers.get(key)
    if cached is None:
        route_arr = None
        if NUMBA_AVAILABLE and np is not None:
            route_arr = _state_route_arrays(state)[route_idx]
        cached = rank_route_outliers(problem, state.routes[route_idx], max_customers, route_arr=route_arr)
        state._route_outliers[key] = cached
    return cached


def _state_route_badness(problem: HCVRPProblem, state: "SolutionState", route_idx: int) -> float:
    if state._route_badness is None:
        state._route_badness = {}
    cached = state._route_badness.get(route_idx)
    if cached is None:
        route = state.routes[route_idx]
        core = route_core(route)
        if not core:
            cached = 0.0
        else:
            spread = _state_route_spread(problem, state, route_idx)
            outlier_customers = _state_route_outliers(problem, state, route_idx, min(3, len(core)))
            outlier_sum = 0.0
            route_arr = None
            if NUMBA_AVAILABLE and np is not None:
                route_arr = _state_route_arrays(state)[route_idx]
            for customer in outlier_customers:
                outlier_sum += customer_outlier_score(problem, route, customer, route_arr=route_arr)
            avg_edge = state.route_distances[route_idx] / max(1, len(core))
            fill_ratio = state.route_loads[route_idx] / max(1e-9, problem.vehicle_types[state.vehicle_ids[route_idx]].capacity)
            underfill_penalty = max(0.0, 0.85 - fill_ratio)
            cached = (
                1.85 * spread
                + 0.30 * state.route_distances[route_idx]
                + 0.14 * avg_edge
                + 0.12 * outlier_sum
                + 85.0 * underfill_penalty
            )
        state._route_badness[route_idx] = cached
    return cached


def _state_has_route_pathology(problem: HCVRPProblem, state: "SolutionState") -> bool:
    if state._pathology_flag is None:
        active = [i for i, route in enumerate(state.routes) if route_core(route)]
        if not active:
            state._pathology_flag = False
        else:
            spreads = [_state_route_spread(problem, state, i) for i in active]
            dists = [state.route_distances[i] for i in active]
            mean_spread = sum(spreads) / len(spreads)
            mean_dist = sum(dists) / len(dists)
            spread_var = sum((x - mean_spread) ** 2 for x in spreads) / len(spreads)
            dist_var = sum((x - mean_dist) ** 2 for x in dists) / len(dists)
            spread_limit = mean_spread + float(ALGO_CONFIG["targeted_cleanup_spread_sigma"]) * math.sqrt(spread_var)
            dist_limit = mean_dist + float(ALGO_CONFIG["targeted_cleanup_distance_sigma"]) * math.sqrt(dist_var)
            state._pathology_flag = max(spreads) > spread_limit or max(dists) > dist_limit
    return bool(state._pathology_flag)

def clone_state_with_updated_route(
        state: "SolutionState",
        route_idx: int,
        new_route: Route,
        route_load: float,
        route_dist: float,
        route_time: float,
        route_cost: float
) -> "SolutionState":
    candidate = clone_solution_state(state)
    candidate.routes[route_idx]          = normalize_route(new_route)
    candidate.route_loads[route_idx]     = route_load
    candidate.route_distances[route_idx] = route_dist
    candidate.route_times[route_idx]     = route_time
    candidate.route_costs[route_idx]     = route_cost
    candidate.total_cost = state.total_cost - state.route_costs[route_idx] + route_cost
    candidate.feasible   = state.feasible
    # SO: hard_feasible da devralınır (rota güncellemesi sonrası yeniden hesaplamak gerekirse
    # tam evaluate_solution çağrılmalı; burada incremental update için orijinal değer korunur)
    candidate.hard_feasible = state.hard_feasible
    _invalidate_state_route_caches(candidate, [route_idx])
    return candidate


def clone_state_with_updated_routes(
        state: "SolutionState",
        route_updates: List[Tuple[int, Route, float, float, float, float]]
) -> "SolutionState":
    candidate = clone_solution_state(state)
    total_cost = state.total_cost
    for route_idx, new_route, route_load, route_dist, route_time, route_cost in route_updates:
        candidate.routes[route_idx] = _ensure_normalized(new_route)
        candidate.route_loads[route_idx] = route_load
        candidate.route_distances[route_idx] = route_dist
        candidate.route_times[route_idx] = route_time
        candidate.route_costs[route_idx] = route_cost
        total_cost += route_cost - state.route_costs[route_idx]
    candidate.total_cost = total_cost
    candidate.feasible = state.feasible
    candidate.hard_feasible = state.hard_feasible
    _invalidate_state_route_caches(candidate, [route_idx for route_idx, *_ in route_updates])
    return candidate


def evaluate_fixed_vehicle_route_delta(
        problem: HCVRPProblem,
        state: "SolutionState",
        route_updates: Dict[int, Route]
) -> Optional["SolutionState"]:
    hard_feasible = state.hard_feasible
    evaluated_updates: List[Tuple[int, Route, float, float, float, float]] = []
    for route_idx, new_route in route_updates.items():
        vt = get_vehicle_type_by_id(problem, state.vehicle_ids[route_idx])
        route_ok, route_load, route_dist, route_time, route_cost = evaluate_route_for_vehicle(
            problem, new_route, vt
        )
        if not route_ok:
            return None
        if route_load > vt.capacity + 1e-9:
            hard_feasible = False
        evaluated_updates.append(
            (route_idx, new_route, route_load, route_dist, route_time, route_cost)
        )
    candidate = clone_state_with_updated_routes(state, evaluated_updates)
    candidate.feasible = state.feasible
    candidate.hard_feasible = hard_feasible
    return candidate

def state_edge_similarity(a: "SolutionState", b: "SolutionState") -> float:
    sa = build_edge_signature_from_routes(a.routes)
    sb = build_edge_signature_from_routes(b.routes)
    if not sa and not sb: return 1.0
    if not sa or not sb:  return 0.0
    union = len(sa | sb)
    return 0.0 if union == 0 else len(sa & sb) / union

def update_elite_pool(
        elite_pool: List["SolutionState"],
        candidate_states: List["SolutionState"],
        max_size: Optional[int] = None,
        max_similarity: Optional[float] = None
) -> List["SolutionState"]:
    if max_size is None:       max_size       = int(ALGO_CONFIG["elite_pool_max_size"])
    if max_similarity is None: max_similarity = float(ALGO_CONFIG["elite_max_similarity"])
    combined = [clone_solution_state(s) for s in elite_pool]
    # SO: elite pool'a yalnız hard_feasible çözümler girer
    combined.extend(clone_solution_state(s) for s in candidate_states if s.hard_feasible)
    combined.sort(key=lambda s: s.total_cost)
    new_pool: List["SolutionState"] = []
    for candidate in combined:
        if any(state_edge_similarity(candidate, ex) > max_similarity for ex in new_pool): continue
        new_pool.append(candidate)
        if len(new_pool) >= max_size: break
    if not new_pool and combined: new_pool.append(clone_solution_state(combined[0]))
    return new_pool

def choose_elite_guide(
        elite_pool: List["SolutionState"], reference_state: "SolutionState"
) -> Optional["SolutionState"]:
    if not elite_pool: return None
    ranked = [(state_edge_similarity(s, reference_state), s.total_cost, s) for s in elite_pool]
    ranked.sort(key=lambda x: (x[0], x[1]))
    return clone_solution_state(ranked[0][2])

def route_count(state: "SolutionState") -> int:
    return len(state.routes)

def remove_empty_routes(
        routes: Route_matrix, vehicle_ids: List[int]
) -> Tuple[Route_matrix, List[int]]:
    new_routes = []; new_vehicle_ids = []
    for route, v_id in zip(routes, vehicle_ids):
        nr = _ensure_normalized(route)
        if route_core(nr): new_routes.append(nr); new_vehicle_ids.append(v_id)
    return new_routes, new_vehicle_ids


# ==============================================================================
#  DESTROY BANDIT
# ==============================================================================

class DestroyBandit:
    _MODES: Tuple[str, ...] = ("shaw", "worst", "targeted", "route")

    def __init__(self, eps: float = 0.15):
        self.eps = eps
        self.reaction = float(ALGO_CONFIG["bandit_reaction_factor"])
        self._scores: Dict[str, float] = {m: 1.0 for m in self._MODES}
        self._counts: Dict[str, int]   = {m: 1   for m in self._MODES}
        self._priors: Dict[str, float] = {
            "shaw": float(ALGO_CONFIG["bandit_prior_shaw"]),
            "worst": float(ALGO_CONFIG["bandit_prior_worst"]),
            "targeted": float(ALGO_CONFIG["bandit_prior_targeted"]),
            "route": float(ALGO_CONFIG["bandit_prior_route"]),
        }
        self.last_mode: Optional[str] = None

    def select(self) -> str:
        if random.random() < self.eps:
            self.last_mode = random.choice(self._MODES)
            return self.last_mode
        total = sum(max(1e-9, self._scores[m]) * self._priors.get(m, 1.0) for m in self._MODES)
        roll = random.random() * total
        acc = 0.0
        for mode in self._MODES:
            acc += max(1e-9, self._scores[mode]) * self._priors.get(mode, 1.0)
            if roll <= acc:
                self.last_mode = mode
                return mode
        self.last_mode = self._MODES[-1]
        return self._MODES[-1]

    def reward_value(self, outcome: str, improvement: float = 0.0) -> float:
        scaled_improvement = math.sqrt(max(0.0, improvement))
        if outcome == "global_best":
            return float(ALGO_CONFIG["bandit_reward_global_best"]) + scaled_improvement
        if outcome == "improving":
            return float(ALGO_CONFIG["bandit_reward_improving"]) + 0.5 * scaled_improvement
        if outcome == "feasible":
            return float(ALGO_CONFIG["bandit_reward_feasible"])
        return float(ALGO_CONFIG["bandit_reward_fail"])

    def update(self, mode: str, reward: float) -> None:
        floor = float(ALGO_CONFIG["bandit_mode_score_floor"])
        self._scores[mode] = max(
            floor,
            (1.0 - self.reaction) * self._scores[mode] + self.reaction * max(0.0, reward),
        )
        self._counts[mode] += 1

    def stats(self) -> Dict[str, float]:
        return {m: round(self._scores[m], 4) for m in self._MODES}


def choose_bandit_mode_for_state(
        problem: HCVRPProblem, state: "SolutionState", bandit: DestroyBandit
) -> str:
    mode = bandit.select()
    if state_has_route_pathology(problem, state):
        if random.random() < float(ALGO_CONFIG["bandit_pathology_bias_prob"]):
            worst_idx = max(
                (i for i, route in enumerate(state.routes) if route_core(route)),
                key=lambda i: route_badness_score(problem, state, i),
                default=-1,
            )
            if worst_idx >= 0 and len(route_core(state.routes[worst_idx])) >= 6:
                mode = "targeted"
            else:
                mode = "route"
    return mode


# ==============================================================================
#  NEIGHBORHOOD OPERATÖRLERİ
# ==============================================================================

def random_intra_route_2opt(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    candidate = clone_solution_state(state)
    eligible  = [r for r, route in enumerate(candidate.routes) if len(route_core(route)) >= 4]
    if not eligible: return candidate
    r_idx = random.choice(eligible); core = route_core(candidate.routes[r_idx])
    i = random.randint(0, len(core) - 2); k = random.randint(i + 1, len(core) - 1)
    candidate.routes[r_idx] = [0] + core[:i] + core[i:k+1][::-1] + core[k+1:] + [0]
    return evaluate_solution(problem, candidate.routes, candidate.vehicle_ids)

def random_inter_route_relocate(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    candidate = clone_solution_state(state)
    non_empty = [i for i, r in enumerate(candidate.routes) if route_core(r)]
    if len(non_empty) < 1: return candidate
    from_idx    = random.choice(non_empty)
    possible_to = [i for i in range(len(candidate.routes)) if i != from_idx]
    if not possible_to: return candidate
    to_idx    = random.choice(possible_to)
    from_core = route_core(candidate.routes[from_idx])
    to_core   = route_core(candidate.routes[to_idx])
    if not from_core: return candidate
    cust_pos  = random.randint(0, len(from_core) - 1)
    customer  = from_core.pop(cust_pos)
    to_core.insert(random.randint(0, len(to_core)), customer)
    candidate.routes[from_idx] = [0] + from_core + [0]
    candidate.routes[to_idx]   = [0] + to_core   + [0]
    candidate.routes, candidate.vehicle_ids = remove_empty_routes(candidate.routes, candidate.vehicle_ids)
    return evaluate_solution(problem, candidate.routes, candidate.vehicle_ids)


def random_safe_inter_route_relocate(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    candidate = clone_solution_state(state)
    non_empty = [i for i, r in enumerate(candidate.routes) if len(route_core(r)) >= 2]
    if not non_empty:
        return candidate

    route_centroids = compute_route_centroids(problem, candidate.routes)
    route_arrays = _routes_to_numpy(candidate.routes) if (NUMBA_AVAILABLE and np is not None) else None
    source_order = non_empty[:]
    random.shuffle(source_order)

    for from_idx in source_order:
        from_route = candidate.routes[from_idx]
        from_core = route_core(from_route)
        if not from_core:
            continue
        customer = random.choice(from_core)
        reduced_core = [n for n in from_core if n != customer]
        candidate_targets = [
            r_idx for r_idx in select_candidate_route_indices(
                problem,
                candidate.routes,
                customer,
                max_candidates=min(4, max(1, len(candidate.routes) - 1)),
                route_centroids=route_centroids,
                route_arrays=route_arrays,
            )
            if r_idx != from_idx
        ]
        random.shuffle(candidate_targets)
        for to_idx in candidate_targets:
            if state.route_loads[to_idx] + problem.demands[customer] > problem.max_vehicle_capacity:
                continue
            to_route = candidate.routes[to_idx]
            insert_pos, _ = choose_best_insertion_position(problem, to_route, customer)
            to_core = route_core(to_route)
            to_core.insert(insert_pos - 1, customer)
            new_to_route = [0] + to_core + [0]
            if reduced_core:
                delta_candidate = evaluate_fixed_vehicle_route_delta(
                    problem,
                    state,
                    {
                        from_idx: [0] + reduced_core + [0],
                        to_idx: new_to_route,
                    },
                )
            else:
                cr = clone_routes(state.routes)
                cr[from_idx] = [0] + reduced_core + [0]
                cr[to_idx] = new_to_route
                cr, cv = remove_empty_routes(cr, state.vehicle_ids[:])
                delta_candidate = evaluate_solution(problem, cr, cv)
            if delta_candidate is not None and delta_candidate.feasible:
                return delta_candidate
    return candidate

def random_inter_route_2opt_star(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    candidate = clone_solution_state(state)
    eligible  = [i for i, r in enumerate(candidate.routes) if len(route_core(r)) >= 2]
    if len(eligible) < 2: return candidate
    r1, r2 = random.sample(eligible, 2)
    core1  = route_core(candidate.routes[r1]); core2 = route_core(candidate.routes[r2])
    cut1   = random.randint(1, len(core1) - 1); cut2 = random.randint(1, len(core2) - 1)
    candidate.routes[r1] = [0] + core1[:cut1] + core2[cut2:] + [0]
    candidate.routes[r2] = [0] + core2[:cut2] + core1[cut1:] + [0]
    return evaluate_solution(problem, candidate.routes, candidate.vehicle_ids)

def random_vehicle_reassignment(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    candidate  = clone_solution_state(state)
    if not candidate.routes: return candidate
    type_usage = _type_usage_from_ids(candidate.vehicle_ids)
    route_indices = list(range(len(candidate.routes)))
    random.shuffle(route_indices)
    best_move = None
    for r_idx in route_indices:
        route           = candidate.routes[r_idx]
        current_type_id = candidate.vehicle_ids[r_idx]
        current_type    = get_vehicle_type_by_id(problem, current_type_id)
        route_ok, _, _, _, current_cost = evaluate_route_for_vehicle(problem, route, current_type)
        if not route_ok: continue
        best_vehicle = assign_best_vehicle_for_existing_route(
            problem, route, current_type_id=current_type_id, type_usage=type_usage
        )
        if best_vehicle is None: continue
        new_type_id, new_cost, _ = best_vehicle
        if new_type_id == current_type_id: continue
        move_key = (new_cost - current_cost, new_cost, r_idx, new_type_id)
        if best_move is None or move_key < best_move[0]:
            best_move = (move_key, (r_idx, current_type_id, new_type_id))
    if best_move is None: return candidate
    r_idx, _, new_type_id = best_move[1]
    candidate.vehicle_ids[r_idx] = new_type_id
    return evaluate_solution(problem, candidate.routes, candidate.vehicle_ids)

def propose_random_neighbor(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    profile = get_problem_scale_profile(problem, active_route_count=max(1, len(state.routes)))
    if profile.get("long_route_mode", False):
        operators = [
            random_intra_route_2opt,
            random_safe_inter_route_relocate,
            random_vehicle_reassignment,
        ]
    else:
        operators = [
            random_intra_route_2opt,
            random_inter_route_relocate,
            random_inter_route_2opt_star,
            random_vehicle_reassignment,
        ]

    fallback = clone_solution_state(state)
    for _ in range(3):
        candidate = random.choice(operators)(problem, state)
        if candidate.feasible:
            return candidate
        fallback = candidate
    return fallback


# ==============================================================================
#  PROBLEM ÖLÇEK PROFİLİ
# ==============================================================================

def evenly_spaced_positions(start: int, stop_exclusive: int, max_count: int) -> List[int]:
    values = list(range(start, stop_exclusive))
    if max_count <= 0 or not values: return []
    if len(values) <= max_count: return values
    if max_count == 1: return [values[len(values) // 2]]
    step = (len(values) - 1) / (max_count - 1)
    seen = set(); selected = []
    for idx in range(max_count):
        v = values[int(round(idx * step))]
        if v not in seen: selected.append(v); seen.add(v)
    return selected

def get_problem_scale_profile(
        problem: HCVRPProblem, active_route_count: Optional[int] = None
) -> Dict[str, float]:
    n_customers = len(problem.customer_ids)
    if active_route_count is None:
        active_route_count = min(
            len(problem.vehicle_types),
            max(1, int(round(math.sqrt(max(n_customers, 1)))))
        )
    route_density = n_customers / max(active_route_count, 1)
    if (active_route_count <= int(ALGO_CONFIG["adaptive_small_route_count"])
            or route_density >= float(ALGO_CONFIG["adaptive_dense_route_threshold"])):
        return dict(ALGO_CONFIG["adaptive_profiles"]["dense"])
    if (active_route_count <= int(ALGO_CONFIG["adaptive_medium_route_count"])
            or route_density >= float(ALGO_CONFIG["adaptive_medium_route_threshold"])):
        return dict(ALGO_CONFIG["adaptive_profiles"]["medium"])
    return dict(ALGO_CONFIG["adaptive_profiles"]["light"])

def get_local_search_limits(state: "SolutionState") -> Dict[str, float]:
    route_lengths = [len(route_core(r)) for r in state.routes if route_core(r)]
    if not route_lengths: return dict(ALGO_CONFIG["adaptive_profiles"]["light"])
    avg_len = sum(route_lengths) / len(route_lengths)
    max_len = max(route_lengths)
    if avg_len >= 8.0 or max_len >= 12: return dict(ALGO_CONFIG["adaptive_profiles"]["dense"])
    if avg_len >= 6.0 or max_len >= 9:  return dict(ALGO_CONFIG["adaptive_profiles"]["medium"])
    return dict(ALGO_CONFIG["adaptive_profiles"]["light"])


# ==============================================================================
#  LOCAL SEARCH (best-improving)
# ==============================================================================

def compute_single_route_centroid(problem: HCVRPProblem, route: Route) -> Point:
    if NUMBA_AVAILABLE and np is not None:
        depot_x, depot_y = problem.coords[0]
        cx, cy = _compute_route_centroid_numba(
            _route_to_numpy(route), problem.coords_np, depot_x, depot_y
        )
        return (float(cx), float(cy))
    core = route_core(route)
    if not core: return problem.coords[0]
    sx = sum(problem.coords[n][0] for n in core)
    sy = sum(problem.coords[n][1] for n in core)
    m  = float(len(core))
    return (sx / m, sy / m)


def select_promising_route_pairs(
        problem: HCVRPProblem, routes: Route_matrix, max_pairs: int = 10,
        centroids: Optional[List[Point]] = None
) -> List[Tuple[int, int]]:
    non_empty = [i for i, r in enumerate(routes) if route_core(r)]
    if len(non_empty) < 2: return []
    if centroids is None:
        centroids = compute_route_centroids(problem, routes)
    scored = []
    for idx_i in range(len(non_empty)):
        i = non_empty[idx_i]; xi, yi = centroids[i]
        for idx_j in range(idx_i + 1, len(non_empty)):
            j = non_empty[idx_j]; xj, yj = centroids[j]
            dx = xi - xj; dy = yi - yj
            scored.append((dx*dx + dy*dy, i, j))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [(i, j) for _, i, j in scored[:max_pairs]]


def compute_route_centroids(problem: HCVRPProblem, routes: Route_matrix) -> List[Point]:
    if NUMBA_AVAILABLE and np is not None:
        depot_x, depot_y = problem.coords[0]
        route_arrays = _routes_to_numpy(routes)
        return [
            _compute_route_centroid_numba(
                route_arr, problem.coords_np, depot_x, depot_y
            )
            for route_arr in route_arrays
        ]
    centroids: List[Point] = []
    for route in routes:
        core = route_core(route)
        if not core: centroids.append(problem.coords[0]); continue
        sx = sum(problem.coords[n][0] for n in core)
        sy = sum(problem.coords[n][1] for n in core)
        m  = float(len(core))
        centroids.append((sx / m, sy / m))
    return centroids


def route_spread_value(problem: HCVRPProblem, route: Route, route_arr=None) -> float:
    core = route_core(route)
    if not core:
        return 0.0
    if NUMBA_AVAILABLE and np is not None:
        depot_x, depot_y = problem.coords[0]
        if route_arr is None:
            route_arr = _route_to_numpy(route)
        return float(_route_spread_numba(route_arr, problem.coords_np, depot_x, depot_y))
    cx, cy = compute_single_route_centroid(problem, route)
    return max(math.hypot(problem.coords[n][0] - cx, problem.coords[n][1] - cy) for n in core)


def customer_outlier_score(problem: HCVRPProblem, route: Route, customer: int, route_arr=None) -> float:
    core = route_core(route)
    if customer not in core or len(core) <= 1:
        return 0.0
    if NUMBA_AVAILABLE and np is not None:
        depot_x, depot_y = problem.coords[0]
        if route_arr is None:
            route_arr = _route_to_numpy(route)
        return float(_customer_outlier_score_numba(
            route_arr,
            customer,
            problem.coords_np,
            problem.dist_np,
            problem.granular_neighbors_np,
            problem.granular_neighbor_counts_np,
            depot_x,
            depot_y,
        ))
    cx, cy = compute_single_route_centroid(problem, route)
    radial = math.hypot(problem.coords[customer][0] - cx, problem.coords[customer][1] - cy)
    nearest = min(problem.dist[customer][other] for other in core if other != customer)
    granular_neighbors = set(problem.granular_neighbors[customer]) if customer < len(problem.granular_neighbors) else set()
    overlap = sum(1 for other in core if other != customer and other in granular_neighbors)
    return radial + 0.45 * nearest - 55.0 * overlap


def rank_route_outliers(problem: HCVRPProblem, route: Route, max_customers: int = 3, route_arr=None) -> List[int]:
    if NUMBA_AVAILABLE and np is not None:
        depot_x, depot_y = problem.coords[0]
        if route_arr is None:
            route_arr = _route_to_numpy(route)
        ranked = _rank_route_outliers_numba(
            route_arr,
            problem.coords_np,
            problem.dist_np,
            problem.granular_neighbors_np,
            problem.granular_neighbor_counts_np,
            depot_x,
            depot_y,
            max_customers,
        )
        return [int(x) for x in ranked]
    core = route_core(route)
    scored = [
        (customer_outlier_score(problem, route, customer), customer)
        for customer in core
    ]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [customer for _, customer in scored[:max_customers]]


def best_improving_intra_route_2opt(
        problem: HCVRPProblem, state: "SolutionState", max_routes: int = 6
) -> "SolutionState":
    best_state = clone_solution_state(state)
    candidates = [
        (state.route_costs[r], r)
        for r, route in enumerate(state.routes) if len(route_core(route)) >= 4
    ]
    candidates.sort(key=lambda x: (-x[0], x[1]))

    for _, r_idx in candidates[:max_routes]:
        route           = _ensure_normalized(state.routes[r_idx])
        core            = route_core(route)
        vt              = get_vehicle_type_by_id(problem, state.vehicle_ids[r_idx])
        base_other_cost = state.total_cost - state.route_costs[r_idx]
        best_route_total = best_state.total_cost
        best_imp: Optional[Tuple] = None
        has_hard_route_constraints = bool(
            getattr(problem, "_has_tight_time_windows", False)
            or getattr(problem, "max_route_time_min", None) is not None
        )

        if NUMBA_AVAILABLE and np is not None and not has_hard_route_constraints:
            route_arr = _route_to_numpy(route)
            best_i, best_k, best_delta = _best_two_opt_move_numba(route_arr, problem.dist_np)
            if best_i >= 0 and best_delta < -1e-9:
                new_route = route[:best_i] + route[best_i:best_k + 1][::-1] + route[best_k + 1:]
                new_dist = state.route_distances[r_idx] + float(best_delta)
                route_cost = vt.fixed_cost + new_dist * vt.cost_per_km
                candidate_total = base_other_cost + route_cost
                if candidate_total < best_route_total:
                    route_time = state.route_times[r_idx] + float(best_delta) / max(vt.speed, 1e-9)
                    best_state = clone_state_with_updated_route(
                        state, r_idx, new_route, state.route_loads[r_idx], new_dist, route_time, route_cost
                    )
            continue

        for i in range(len(core) - 2):
            for k in range(i + 1, len(core) - 1):
                new_core  = core[:i] + core[i:k+1][::-1] + core[k+1:]
                new_route = [0] + new_core + [0]
                route_ok, load, dist, route_time, route_cost = evaluate_route_for_vehicle(
                    problem, new_route, vt
                )
                if not route_ok:
                    continue
                candidate_total = base_other_cost + route_cost
                if candidate_total < best_route_total:
                    best_route_total = candidate_total
                    best_imp = (new_route, load, dist, route_time, route_cost)

        if best_imp is not None:
            new_route, load, dist, route_time, route_cost = best_imp
            best_state = clone_state_with_updated_route(
                state, r_idx, new_route, load, dist, route_time, route_cost
            )

    if best_state.feasible and best_state.total_cost <= state.total_cost:
        return best_state
    return clone_solution_state(state)


def best_improving_inter_route_relocate(
        problem: HCVRPProblem, state: "SolutionState", max_pairs: int = 8
) -> "SolutionState":
    best_state = clone_solution_state(state)
    for from_idx, to_idx in select_promising_route_pairs(problem, state.routes, max_pairs=max_pairs):
        from_core = route_core(state.routes[from_idx])
        to_route  = state.routes[to_idx]
        for pos_from, customer in enumerate(from_core):
            reduced_core = from_core[:pos_from] + from_core[pos_from+1:]
            insert_pos, _ = choose_best_insertion_position(problem, to_route, customer)
            to_core = route_core(to_route); to_core.insert(insert_pos - 1, customer)
            new_to_route = [0] + to_core + [0]
            if reduced_core:
                candidate = evaluate_fixed_vehicle_route_delta(
                    problem, state,
                    {
                        from_idx: [0] + reduced_core + [0],
                        to_idx: new_to_route,
                    },
                )
            else:
                cr = clone_routes(state.routes)
                cr[from_idx] = [0] + reduced_core + [0]
                cr[to_idx] = new_to_route
                cr, cv = remove_empty_routes(cr, state.vehicle_ids[:])
                candidate = evaluate_solution(problem, cr, cv)
            if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                best_state = candidate
    if best_state.feasible and best_state.total_cost <= state.total_cost:
        return best_state
    return clone_solution_state(state)


def best_improving_outlier_relocate(
        problem: HCVRPProblem, state: "SolutionState",
        max_source_routes: int = 6, max_target_routes: int = 6,
        max_outliers_per_route: int = 3
) -> "SolutionState":
    best_state = clone_solution_state(state)
    route_centroids = _state_route_centroids(problem, state)
    route_arrays = _state_route_arrays(state) if (NUMBA_AVAILABLE and np is not None) else None
    source_scores = []
    for r_idx, route in enumerate(state.routes):
        core = route_core(route)
        if len(core) < 3:
            continue
        route_arr = route_arrays[r_idx] if route_arrays is not None else None
        source_scores.append((_state_route_spread(problem, state, r_idx), state.route_costs[r_idx], r_idx))
    source_scores.sort(key=lambda x: (-x[0], -x[1], x[2]))

    for _, _, from_idx in source_scores[:max_source_routes]:
        from_route = state.routes[from_idx]
        from_route_arr = route_arrays[from_idx] if route_arrays is not None else None
        outliers = rank_route_outliers(problem, from_route, max_outliers_per_route, route_arr=from_route_arr)
        for customer in outliers:
            candidate_targets = [
                r_idx for r_idx in select_candidate_route_indices(
                    problem, state.routes, customer, max_candidates=max_target_routes,
                    route_centroids=route_centroids, route_arrays=route_arrays
                )
                if r_idx != from_idx
            ]
            for to_idx in candidate_targets:
                from_core = route_core(state.routes[from_idx])
                if customer not in from_core:
                    continue
                reduced_core = [n for n in from_core if n != customer]
                to_route = state.routes[to_idx]
                insert_pos, _ = choose_best_insertion_position(problem, to_route, customer)
                to_core = route_core(to_route)
                to_core.insert(insert_pos - 1, customer)
                new_to_route = [0] + to_core + [0]
                if reduced_core:
                    candidate = evaluate_fixed_vehicle_route_delta(
                        problem, state,
                        {
                            from_idx: [0] + reduced_core + [0],
                            to_idx: new_to_route,
                        },
                    )
                else:
                    cr = clone_routes(state.routes)
                    cr[from_idx] = [0] + reduced_core + [0]
                    cr[to_idx] = new_to_route
                    cr, cv = remove_empty_routes(cr, state.vehicle_ids[:])
                    candidate = evaluate_solution(problem, cr, cv)
                if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                    best_state = candidate
    if best_state.feasible and best_state.total_cost <= state.total_cost:
        return best_state
    return clone_solution_state(state)


def best_improving_two_customer_relocate(
        problem: HCVRPProblem, state: "SolutionState", max_pairs: int = 6
) -> "SolutionState":
    best_state = clone_solution_state(state)
    for from_idx, to_idx in select_promising_route_pairs(problem, state.routes, max_pairs=max_pairs):
        from_core = route_core(state.routes[from_idx])
        if len(from_core) < 3:
            continue
        for start in range(len(from_core) - 1):
            block = from_core[start:start + 2]
            reduced_core = from_core[:start] + from_core[start + 2:]
            candidate_to = _ensure_normalized(state.routes[to_idx])[:]
            for customer in block:
                pos, _ = choose_best_insertion_position(problem, candidate_to, customer)
                candidate_to.insert(pos, customer)
            candidate = evaluate_fixed_vehicle_route_delta(
                problem, state,
                {
                    from_idx: [0] + reduced_core + [0],
                    to_idx: candidate_to,
                },
            )
            if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                best_state = candidate
    return best_state


def best_improving_inter_route_2opt_star(
        problem: HCVRPProblem, state: "SolutionState",
        max_pairs: int = 6, max_cuts_per_route: int = 5
) -> "SolutionState":
    best_state = clone_solution_state(state)
    for r1, r2 in select_promising_route_pairs(problem, state.routes, max_pairs=max_pairs):
        core1 = route_core(state.routes[r1]); core2 = route_core(state.routes[r2])
        if len(core1) < 2 or len(core2) < 2: continue
        for cut1 in evenly_spaced_positions(1, len(core1), max_cuts_per_route):
            for cut2 in evenly_spaced_positions(1, len(core2), max_cuts_per_route):
                candidate = evaluate_fixed_vehicle_route_delta(
                    problem, state,
                    {
                        r1: [0] + core1[:cut1] + core2[cut2:] + [0],
                        r2: [0] + core2[:cut2] + core1[cut1:] + [0],
                    },
                )
                if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                    best_state = candidate
    return best_state


def best_improving_cross_exchange(
        problem: HCVRPProblem, state: "SolutionState",
        max_pairs: int = 5, max_block_size: int = 2, max_start_positions: int = 5
) -> "SolutionState":
    best_state = clone_solution_state(state)
    for r1, r2 in select_promising_route_pairs(problem, state.routes, max_pairs=max_pairs):
        core1 = route_core(state.routes[r1]); core2 = route_core(state.routes[r2])
        if not core1 or not core2: continue
        for len1 in range(1, min(max_block_size, len(core1)) + 1):
            for len2 in range(1, min(max_block_size, len(core2)) + 1):
                sp1 = evenly_spaced_positions(0, len(core1) - len1 + 1, max_start_positions)
                sp2 = evenly_spaced_positions(0, len(core2) - len2 + 1, max_start_positions)
                for start1 in sp1:
                    block1 = core1[start1:start1+len1]; rest1 = core1[:start1] + core1[start1+len1:]
                    for start2 in sp2:
                        block2 = core2[start2:start2+len2]; rest2 = core2[:start2] + core2[start2+len2:]
                        candidate = evaluate_fixed_vehicle_route_delta(
                            problem, state,
                            {
                                r1: [0] + rest1[:start1] + block2 + rest1[start1:] + [0],
                                r2: [0] + rest2[:start2] + block1 + rest2[start2:] + [0],
                            },
                        )
                        if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                            best_state = candidate
    return best_state


def best_improving_or_opt(
        problem: HCVRPProblem, state: "SolutionState",
        max_routes: int = 5, max_block_size: int = 3
) -> "SolutionState":
    best_state = clone_solution_state(state)
    candidates = [
        (state.route_costs[r], r)
        for r, route in enumerate(state.routes) if len(route_core(route)) >= 4
    ]
    candidates.sort(key=lambda x: (-x[0], x[1]))
    for _, r_idx in candidates[:max_routes]:
        core = route_core(state.routes[r_idx])
        vt = get_vehicle_type_by_id(problem, state.vehicle_ids[r_idx])
        for block_size in range(1, min(max_block_size + 1, len(core))):
            for start in range(len(core) - block_size + 1):
                block = core[start:start + block_size]
                reduced = core[:start] + core[start + block_size:]
                for ins_pos in range(len(reduced) + 1):
                    if ins_pos == start or ins_pos == start + 1:
                        continue
                    new_core = reduced[:ins_pos] + block + reduced[ins_pos:]
                    new_route = [0] + new_core + [0]
                    rok, load, dist, route_time, route_cost = evaluate_route_for_vehicle(
                        problem, new_route, vt
                    )
                    if not rok:
                        continue
                    candidate = clone_state_with_updated_route(
                        state, r_idx, new_route, load, dist, route_time, route_cost
                    )
                    if candidate.feasible and candidate.total_cost < best_state.total_cost:
                        best_state = candidate
    return best_state


def intensify_local_search(
        problem: HCVRPProblem, state: "SolutionState", max_rounds: int = 3
) -> "SolutionState":
    current = clone_solution_state(state)
    limits  = get_local_search_limits(current)
    for _ in range(min(max_rounds, int(limits["ls_rounds"]))):
        improved = False
        for op, kwargs in [
            (best_improving_intra_route_2opt,     {"max_routes":          int(limits["intra_routes"])}),
            (best_improving_or_opt,               {"max_routes":          int(limits["intra_routes"]),
                                                   "max_block_size":      3}),
            (best_improving_outlier_relocate,     {"max_source_routes":   int(ALGO_CONFIG["outlier_source_routes"]),
                                                   "max_target_routes":   int(ALGO_CONFIG["outlier_target_routes"]),
                                                   "max_outliers_per_route": int(ALGO_CONFIG["outlier_customers_per_route"])}),
            (best_improving_inter_route_relocate,  {"max_pairs":           int(limits["relocate_pairs"])}),
            (best_improving_two_customer_relocate, {"max_pairs":           max(1, int(limits["relocate_pairs"]) // 2)}),
            (best_improving_inter_route_2opt_star, {"max_pairs":           int(limits["two_opt_pairs"]),
                                                    "max_cuts_per_route":  int(limits["max_cuts_per_route"])}),
            (best_improving_cross_exchange,        {"max_pairs":           int(limits["cross_pairs"]),
                                                    "max_start_positions": int(limits["max_cross_starts"])}),
        ]:
            candidate = op(problem, current, **kwargs)
            if candidate.feasible and candidate.total_cost < current.total_cost:
                current = candidate; improved = True
        for op in (
            random_vehicle_reassignment,
            targeted_cleanup_phase,
            lambda p, s: route_elimination_phase(p, s, int(limits["route_elimination_tries"])),
        ):
            candidate = op(problem, current)
            if candidate.feasible and candidate.total_cost < current.total_cost:
                current = candidate; improved = True
        if not improved: break
    return current


def stagnation_kick(
        problem: HCVRPProblem, state: "SolutionState",
        ruin_frac: float = 0.35,
        bandit: Optional["DestroyBandit"] = None
) -> "SolutionState":
    kicked = ruin_and_rebuild_routes(
        problem, state, ruin_frac=ruin_frac,
        destroy_mode="route", bandit=bandit, use_bandit=False
    )
    kicked = focused_cluster_rebuild(
        problem, kicked,
        max_bad_routes=int(ALGO_CONFIG["cluster_rebuild_bad_routes"]),
        max_neighbor_routes=int(ALGO_CONFIG["cluster_rebuild_neighbor_routes"]),
        max_routes_to_rebuild=int(ALGO_CONFIG["cluster_rebuild_max_routes"]),
    )
    kicked = worst_route_outlier_purge_phase(
        problem, kicked,
        max_routes=int(ALGO_CONFIG["outlier_purge_routes"]),
        outliers_per_route=int(ALGO_CONFIG["outlier_purge_customers_per_route"]),
    )
    kicked = worst_route_surgery_phase(
        problem, kicked,
        max_targets=int(ALGO_CONFIG["route_surgery_max_targets"]),
        neighbor_routes=int(ALGO_CONFIG["route_surgery_neighbor_routes"]),
        max_routes_to_rebuild=int(ALGO_CONFIG["route_surgery_max_routes"]),
    )
    return intensify_local_search(problem, kicked, max_rounds=3)


# ==============================================================================
#  REGRET INSERT
# ==============================================================================

def choose_best_insertion_position(
        problem: HCVRPProblem, route: Route, customer: int
) -> Tuple[int, float]:
    nr = _ensure_normalized(route)
    if NUMBA_AVAILABLE and np is not None:
        best_pos, best_delta = _best_insertion_position_numba(
            _route_to_numpy(nr), customer, problem.dist_np
        )
        return int(best_pos), float(best_delta)
    best_pos = 1; best_delta = float("inf")
    for i in range(len(nr) - 1):
        a = nr[i]; b = nr[i+1]
        delta = problem.dist[a][customer] + problem.dist[customer][b] - problem.dist[a][b]
        if delta < best_delta: best_delta = delta; best_pos = i + 1
    return best_pos, best_delta


def select_candidate_route_indices(
        problem: HCVRPProblem,
        routes: Route_matrix,
        customer: int,
        max_candidates: int = 8,
        route_centroids: Optional[List[Point]] = None,
        route_arrays=None
) -> List[int]:
    if len(routes) <= max_candidates: return list(range(len(routes)))
    cx, cy = problem.coords[customer]
    granular_neighbors = set(problem.granular_neighbors[customer]) if customer < len(problem.granular_neighbors) else set()
    if route_centroids is None:
        route_centroids = compute_route_centroids(problem, routes)
    if NUMBA_AVAILABLE and np is not None:
        if route_arrays is None:
            route_arrays = _routes_to_numpy(routes)
        centroid_arr = np.asarray(route_centroids, dtype=np.float64)
        base = list(_select_candidate_route_indices_numba(
            cx, cy, centroid_arr[:, 0], centroid_arr[:, 1], min(len(routes), max_candidates * 2)
        ))
        gcount = int(problem.granular_neighbor_counts_np[customer]) if hasattr(problem, "granular_neighbor_counts_np") else 0
        if gcount <= 0:
            return base[:max_candidates]
        boost_weight = float(ALGO_CONFIG["granular_route_boost_weight"])
        scored = []
        for r_idx in base:
            overlap = int(_count_granular_overlap_numba(
                route_arrays[r_idx],
                problem.granular_neighbors_np[customer],
                gcount,
            ))
            dx = cx - route_centroids[r_idx][0]
            dy = cy - route_centroids[r_idx][1]
            scored.append((-overlap, (dx * dx + dy * dy) / max(boost_weight, 1.0), r_idx))
        scored.sort(key=lambda x: (x[0], x[1], x[2]))
        return [r for _, _, r in scored[:max_candidates]]
    scored = []
    for r_idx, centroid in enumerate(route_centroids):
        dx = cx - centroid[0]; dy = cy - centroid[1]
        overlap = sum(1 for n in route_core(routes[r_idx]) if n in granular_neighbors)
        scored.append((-overlap, dx * dx + dy * dy, r_idx))
    scored.sort(key=lambda x: (x[0], x[1], x[2]))
    return [r for _, _, r in scored[:max_candidates]]


def build_insertion_options_for_customer(
        problem: HCVRPProblem,
        routes: Route_matrix,
        vehicle_ids: List[int],
        type_usage: Dict[int, int],
        customer: int,
        current_route_costs: Optional[List[Optional[float]]] = None,
        current_route_loads: Optional[List[float]] = None,
        candidate_route_limit: int = 8,
        route_centroids: Optional[List[Point]] = None,
        route_arrays=None,
        max_options: Optional[int] = None,
        allow_new_route: bool = True
) -> List[Tuple]:
    options: List[Tuple] = []
    customer_demand = problem.demands[customer]
    centroid_weight = float(ALGO_CONFIG["insertion_centroid_penalty_weight"])
    outlier_weight  = float(ALGO_CONFIG["insertion_outlier_penalty_weight"])
    load_threshold  = float(ALGO_CONFIG["insertion_load_penalty_threshold"])
    load_weight     = float(ALGO_CONFIG["insertion_load_penalty_weight"])
    for r_idx in select_candidate_route_indices(
            problem, routes, customer,
            max_candidates=candidate_route_limit,
            route_centroids=route_centroids,
            route_arrays=route_arrays):
        if (current_route_loads is not None
                and current_route_loads[r_idx] + customer_demand > problem.max_vehicle_capacity):
            continue
        route           = routes[r_idx]
        current_type_id = vehicle_ids[r_idx]
        current_type    = get_vehicle_type_by_id(problem, current_type_id)
        if current_route_costs is not None and current_route_costs[r_idx] is not None:
            current_cost = current_route_costs[r_idx]
        else:
            route_ok, _, _, _, current_cost = evaluate_route_for_vehicle(problem, route, current_type)
            if not route_ok: continue
        pos, _          = choose_best_insertion_position(problem, route, customer)
        candidate_route = route[:]
        candidate_route.insert(pos, customer)
        best_vehicle    = assign_best_vehicle_for_existing_route(
            problem, candidate_route, current_type_id=current_type_id, type_usage=type_usage
        )
        if best_vehicle is None: continue
        new_type_id, new_cost, _ = best_vehicle
        geo_penalty = 0.0
        if route_centroids is not None and r_idx < len(route_centroids):
            cx, cy = problem.coords[customer]
            rx, ry = route_centroids[r_idx]
            geo_penalty += centroid_weight * math.hypot(cx - rx, cy - ry)
        if len(candidate_route) >= 5:
            geo_penalty += outlier_weight * customer_outlier_score(problem, candidate_route, customer)
        new_type = get_vehicle_type_by_id(problem, new_type_id)
        projected_load = (current_route_loads[r_idx] if current_route_loads is not None else problem.route_load(route)) + customer_demand
        load_ratio = projected_load / max(new_type.capacity, 1.0)
        if load_ratio > load_threshold:
            geo_penalty += load_weight * ((load_ratio - load_threshold) ** 2)
        options.append(((new_cost - current_cost) + geo_penalty, ("existing", r_idx, pos, new_type_id, new_cost)))
    if allow_new_route:
        new_route   = [0, customer, 0]
        new_type_id = assign_best_feasible_vehicle_for_tour(problem, new_route, type_usage)
        if new_type_id is not None:
            new_type = get_vehicle_type_by_id(problem, new_type_id)
            _, _, _, _, nrc = evaluate_route_for_vehicle(problem, new_route, new_type)
            options.append((nrc, ("new", -1, -1, new_type_id, nrc)))
    if max_options is not None and len(options) > max_options:
        options = heapq.nsmallest(
            max_options, options, key=lambda x: (x[0], x[1][0], x[1][1], x[1][2], x[1][3])
        )
    else:
        options.sort(key=lambda x: (x[0], x[1][0], x[1][1], x[1][2], x[1][3]))
    return options


def choose_regret_customer_insertion(
        problem: HCVRPProblem,
        routes: Route_matrix,
        vehicle_ids: List[int],
        type_usage: Dict[int, int],
        candidate_customers: List[int],
        regret_k: int = 3,
        current_route_costs: Optional[List[Optional[float]]] = None,
        current_route_loads: Optional[List[float]] = None,
        candidate_customer_limit: Optional[int] = None,
        candidate_route_limit: Optional[int] = None,
        allow_new_route: bool = True,
        route_centroids: Optional[List[Point]] = None,
        route_arrays=None
) -> Optional[Tuple]:
    best_customer_choice = None
    if current_route_costs is None:
        current_route_costs = []
        for route, type_id in zip(routes, vehicle_ids):
            vt = get_vehicle_type_by_id(problem, type_id)
            route_ok, _, _, _, rc = evaluate_route_for_vehicle(problem, route, vt)
            current_route_costs.append(rc if route_ok else None)
    if route_centroids is None:
        route_centroids = compute_route_centroids(problem, routes)
    if route_arrays is None and NUMBA_AVAILABLE and np is not None:
        route_arrays = _routes_to_numpy(routes)
    profile = get_problem_scale_profile(problem, active_route_count=max(1, len(routes)))
    if candidate_customer_limit is None: candidate_customer_limit = int(profile["regret_customer_limit"])
    if candidate_route_limit    is None: candidate_route_limit    = int(profile["regret_route_limit"])
    prioritized = (random.sample(candidate_customers, candidate_customer_limit)
                   if len(candidate_customers) > candidate_customer_limit else candidate_customers)
    for customer in prioritized:
        options = build_insertion_options_for_customer(
            problem, routes, vehicle_ids, type_usage, customer,
            current_route_costs=current_route_costs,
            current_route_loads=current_route_loads,
            candidate_route_limit=candidate_route_limit,
            route_centroids=route_centroids,
            route_arrays=route_arrays,
            max_options=max(regret_k, 2),
            allow_new_route=allow_new_route
        )
        if not options: continue
        best_delta, best_action = options[0]
        k = min(regret_k, len(options))
        regret_score = sum(options[i][0] - best_delta for i in range(1, k)) if k > 1 else 1e9
        choice_key   = (-regret_score, best_delta, customer)
        if best_customer_choice is None or choice_key < best_customer_choice[0]:
            best_customer_choice = (choice_key, (customer, best_action, best_delta, regret_score))
    return None if best_customer_choice is None else best_customer_choice[1]


def sample_regret_k() -> int:
    return 3 if random.random() < float(ALGO_CONFIG["regret3_probability"]) else 2


# ==============================================================================
#  DESTROY / REPAIR
# ==============================================================================

def flatten_customers_from_routes(routes: Route_matrix) -> List[int]:
    return [n for route in routes for n in route if n != 0]

def build_customer_to_route_map(routes: Route_matrix) -> Dict[int, int]:
    return {n: r_idx for r_idx, route in enumerate(routes) for n in route if n != 0}


def targeted_destroy_customers(
        problem: HCVRPProblem, state: "SolutionState", remove_count: int
) -> Set[int]:
    active = [i for i, route in enumerate(state.routes) if route_core(route)]
    if not active:
        return set()
    ranked = sorted(
        ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
        key=lambda x: (-x[0], x[1])
    )
    centroids = _state_route_centroids(problem, state)
    anchor_idx = ranked[0][1]
    selected_routes = [anchor_idx]
    xi, yi = centroids[anchor_idx]
    neighbors = []
    for _, r_idx in ranked[1:]:
        xj, yj = centroids[r_idx]
        dx = xi - xj
        dy = yi - yj
        neighbors.append((dx * dx + dy * dy, -route_badness_score(problem, state, r_idx), r_idx))
    neighbors.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, r_idx in neighbors[:int(ALGO_CONFIG["targeted_destroy_neighbor_routes"])]:
        if r_idx not in selected_routes:
            selected_routes.append(r_idx)

    removed: List[int] = []
    seen: Set[int] = set()
    for r_idx in selected_routes + [r for _, r in ranked if r not in selected_routes]:
        route = state.routes[r_idx]
        core = route_core(route)
        if not core:
            continue
        remaining = remove_count - len(removed)
        if remaining <= 0:
            break
        take = min(max(1, remaining), max(1, len(core) // 2))
        ranked_outliers = rank_route_outliers(problem, route, take)
        # Outlier'ları önceliklendir ama sadece uç düğümlere kilitlenme:
        # yüksek badness'lı komşu rotalardan biraz daha geniş müşteri sök.
        extras = sorted(
            core,
            key=lambda c: (
                -customer_outlier_score(problem, route, c),
                -problem.demands[c],
                c,
            ),
        )
        merged = []
        for customer in ranked_outliers + extras:
            if customer not in merged:
                merged.append(customer)
        for customer in merged[:take]:
            if customer not in seen:
                seen.add(customer)
                removed.append(customer)
            if len(removed) >= remove_count:
                return set(removed)
    return set(removed)

def customer_relatedness(problem: HCVRPProblem, a: int, b: int) -> float:
    return problem.dist[a][b] + 0.25 * abs(problem.demands[a] - problem.demands[b])

def shaw_destroy_customers(problem: HCVRPProblem, routes: Route_matrix, remove_count: int) -> Set[int]:
    customers = flatten_customers_from_routes(routes)
    if not customers: return set()
    seed    = random.choice(customers); removed = {seed}
    while len(removed) < min(remove_count, len(customers)):
        scores = [(min(customer_relatedness(problem, c, p) for p in removed), c)
                  for c in customers if c not in removed]
        if not scores: break
        scores.sort(key=lambda x: (x[0], x[1]))
        _, chosen = random.choice(scores[:max(1, min(5, len(scores)))])
        removed.add(chosen)
    return removed

def worst_destroy_customers(problem: HCVRPProblem, state: "SolutionState", remove_count: int) -> Set[int]:
    route_map = build_customer_to_route_map(state.routes)
    scored    = []
    for customer in flatten_customers_from_routes(state.routes):
        r_idx = route_map[customer]; route = state.routes[r_idx]; rc = state.route_costs[r_idx]
        r_core = [n for n in route_core(route) if n != customer]
        vt     = get_vehicle_type_by_id(problem, state.vehicle_ids[r_idx])
        _, _, _, _, reduced_cost = evaluate_route_for_vehicle(problem, [0] + r_core + [0], vt)
        scored.append((rc - reduced_cost, customer))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top    = scored[:max(remove_count * 3, remove_count)]
    chosen = random.sample(top, remove_count) if len(top) > remove_count else top
    return {c for _, c in chosen}

def route_destroy_customers(state: "SolutionState", remove_count: int) -> Set[int]:
    non_empty = [i for i, r in enumerate(state.routes) if route_core(r)]
    if not non_empty: return set()
    route_scores = [(len(route_core(state.routes[i])), -state.route_costs[i], i) for i in non_empty]
    route_scores.sort(key=lambda x: (x[0], x[1], x[2]))
    removed: Set[int] = set()
    for _, _, r_idx in route_scores:
        for customer in route_core(state.routes[r_idx]):
            removed.add(customer)
            if len(removed) >= remove_count: return removed
    return removed

def choose_destroy_customers(
        problem: HCVRPProblem, state: "SolutionState",
        remove_count: int, destroy_mode: str
) -> Set[int]:
    if destroy_mode == "shaw":  return shaw_destroy_customers(problem, state.routes, remove_count)
    if destroy_mode == "worst": return worst_destroy_customers(problem, state, remove_count)
    if destroy_mode == "targeted": return targeted_destroy_customers(problem, state, remove_count)
    if destroy_mode == "route": return route_destroy_customers(state, remove_count)
    return set(random.sample(flatten_customers_from_routes(state.routes), remove_count))

def sample_destroy_mode() -> str:
    p_shaw  = max(0.0, min(1.0, float(ALGO_CONFIG["destroy_prob_shaw"])))
    p_worst = max(0.0, min(1.0 - p_shaw, float(ALGO_CONFIG["destroy_prob_worst"])))
    p_targeted = max(0.0, min(1.0 - p_shaw - p_worst, float(ALGO_CONFIG["destroy_prob_targeted"])))
    roll    = random.random()
    if roll < p_shaw:             return "shaw"
    if roll < p_shaw + p_worst:   return "worst"
    if roll < p_shaw + p_worst + p_targeted: return "targeted"
    return "route"

def remove_customers_from_routes(routes: Route_matrix, customers_to_remove: Set[int]) -> Route_matrix:
    return [
        [0] + [n for n in route if n != 0 and n not in customers_to_remove] + [0]
        for route in routes
        if any(n not in customers_to_remove for n in route if n != 0)
    ]


def _apply_regret_insertion(
        problem: HCVRPProblem,
        routes: Route_matrix,
        vehicle_ids: List[int],
        type_usage: Dict[int, int],
        pending_customers: List[int],
        allow_new_route: bool = True,
        route_centroids: Optional[List[Point]] = None
) -> bool:
    if route_centroids is None:
        route_centroids = compute_route_centroids(problem, routes)
    route_arrays = _routes_to_numpy(routes) if (NUMBA_AVAILABLE and np is not None) else None

    current_route_costs: List[Optional[float]] = []
    current_route_loads: List[float] = []
    for route, type_id in zip(routes, vehicle_ids):
        vt = get_vehicle_type_by_id(problem, type_id)
        route_ok, route_load, _, _, rc = evaluate_route_for_vehicle(problem, route, vt)
        current_route_costs.append(rc if route_ok else None)
        current_route_loads.append(route_load)

    while pending_customers:
        rc = choose_regret_customer_insertion(
            problem, routes, vehicle_ids, type_usage,
            pending_customers, regret_k=sample_regret_k(),
            current_route_costs=current_route_costs,
            current_route_loads=current_route_loads,
            allow_new_route=allow_new_route,
            route_centroids=route_centroids,
            route_arrays=route_arrays
        )
        if rc is None: return False
        customer, best_action, _, _ = rc
        action_type, r_idx, pos, new_type_id, new_cost = best_action

        if action_type == "existing":
            old_type_id = vehicle_ids[r_idx]
            nr = _ensure_normalized(routes[r_idx])[:]; nr.insert(pos, customer)
            routes[r_idx] = nr; vehicle_ids[r_idx] = new_type_id
            current_route_costs[r_idx] = new_cost
            current_route_loads[r_idx] += problem.demands[customer]
            route_centroids[r_idx] = compute_single_route_centroid(problem, nr)
            if route_arrays is not None:
                route_arrays[r_idx] = _route_to_numpy(nr)
            if old_type_id != new_type_id:
                type_usage[old_type_id] -= 1
                if type_usage[old_type_id] <= 0: del type_usage[old_type_id]
                type_usage[new_type_id] = type_usage.get(new_type_id, 0) + 1
        else:
            if not allow_new_route: return False
            new_route = [0, customer, 0]
            routes.append(new_route); vehicle_ids.append(new_type_id)
            type_usage[new_type_id] = type_usage.get(new_type_id, 0) + 1
            current_route_costs.append(new_cost)
            current_route_loads.append(problem.demands[customer])
            route_centroids.append(compute_single_route_centroid(problem, new_route))
            if route_arrays is not None:
                route_arrays.append(_route_to_numpy(new_route))

        pending_customers.remove(customer)
    return True


def ruin_and_rebuild_routes(
        problem: HCVRPProblem, state: "SolutionState",
        ruin_frac: float = 0.20,
        destroy_mode: str = "shaw",
        bandit: Optional["DestroyBandit"] = None,
        use_bandit: bool = True
) -> "SolutionState":
    customers = flatten_customers_from_routes(state.routes)
    n = len(customers)
    if n <= 2: return clone_solution_state(state)
    q       = max(1, int(ruin_frac * n))
    mode    = bandit.select() if (bandit is not None and use_bandit) else destroy_mode
    if bandit is not None and use_bandit and state_has_route_pathology(problem, state):
        if random.random() < float(ALGO_CONFIG["bandit_pathology_bias_prob"]):
            worst_idx = max(
                (i for i, route in enumerate(state.routes) if route_core(route)),
                key=lambda i: route_badness_score(problem, state, i),
                default=-1,
            )
            if worst_idx >= 0 and len(route_core(state.routes[worst_idx])) >= 6:
                mode = "targeted"
            else:
                mode = "route"
    removed = choose_destroy_customers(problem, state, q, mode)
    routes  = remove_customers_from_routes(state.routes, removed)
    vehicle_ids: List[int] = []; type_usage: Dict[int, int] = {}
    for route in routes:
        v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
        if v_id is None: return clone_solution_state(state)
        vehicle_ids.append(v_id); type_usage[v_id] = type_usage.get(v_id, 0) + 1
    pending = list(removed)
    if not _apply_regret_insertion(problem, routes, vehicle_ids, type_usage, pending):
        if bandit is not None and use_bandit:
            bandit.update(mode, bandit.reward_value("fail", 0.0))
        return clone_solution_state(state)
    raw_result = evaluate_solution(problem, routes, vehicle_ids)
    if bandit is not None and use_bandit:
        improvement = max(0.0, state.total_cost - raw_result.total_cost)
        base_bad = max(
            (route_badness_score(problem, state, i) for i, r in enumerate(state.routes) if route_core(r)),
            default=0.0,
        )
        cand_bad = max(
            (route_badness_score(problem, raw_result, i) for i, r in enumerate(raw_result.routes) if route_core(r)),
            default=0.0,
        )
        badness_drop = max(0.0, base_bad - cand_bad)
        if raw_result.hard_feasible and improvement > 1e-9:
            reward = bandit.reward_value("improving", improvement)
        elif raw_result.feasible:
            reward = bandit.reward_value("feasible", improvement)
        else:
            reward = bandit.reward_value("fail", 0.0)
        if raw_result.feasible and badness_drop > 1e-9:
            reward += float(ALGO_CONFIG["bandit_pathology_bonus_weight"]) * math.sqrt(badness_drop)
            if mode == "targeted":
                reward *= float(ALGO_CONFIG["bandit_targeted_bonus_mult"])
            elif mode == "route":
                reward *= float(ALGO_CONFIG["bandit_route_bonus_mult"])
        bandit.update(mode, reward)
    result = maybe_targeted_cleanup(problem, raw_result)
    return result


def route_elimination_phase(
        problem: HCVRPProblem, state: "SolutionState",
        max_routes_to_try: Optional[int] = None
) -> "SolutionState":
    if max_routes_to_try is None:
        max_routes_to_try = int(ALGO_CONFIG["route_elimination_max_routes"])
    if len(state.routes) <= 1: return clone_solution_state(state)
    route_scores = []
    for r_idx, (route, v_id, rc, rl) in enumerate(zip(
            state.routes, state.vehicle_ids, state.route_costs, state.route_loads)):
        vt = get_vehicle_type_by_id(problem, v_id)
        load_ratio = rl / max(vt.capacity, 1.0)
        route_scores.append((load_ratio, rc, len(route_core(route)), r_idx))
    route_scores.sort(key=lambda x: (x[0], -x[1], x[2], x[3]))
    best_state = clone_solution_state(state)
    for target_idx in [r for _, _, _, r in route_scores[:max_routes_to_try]]:
        target_customers = route_core(state.routes[target_idx])
        if not target_customers: continue
        routes      = clone_routes(state.routes); vehicle_ids = state.vehicle_ids[:]
        del routes[target_idx]; del vehicle_ids[target_idx]
        type_usage  = _type_usage_from_ids(vehicle_ids)
        pending     = target_customers[:]
        if not _apply_regret_insertion(
                problem, routes, vehicle_ids, type_usage, pending, allow_new_route=False
        ):
            continue
        cs = evaluate_solution(problem, routes, vehicle_ids)
        if cs.feasible and cs.total_cost < best_state.total_cost: best_state = cs
    return best_state


def route_badness_score(problem: HCVRPProblem, state: "SolutionState", route_idx: int) -> float:
    return _state_route_badness(problem, state, route_idx)


def farthest_customer_seeds(problem: HCVRPProblem, customers: List[int], k: int) -> List[int]:
    if not customers or k <= 0:
        return []
    unique = list(dict.fromkeys(customers))
    first = max(unique, key=lambda c: problem.dist[0][c])
    seeds = [first]
    while len(seeds) < min(k, len(unique)):
        best_customer = None
        best_score = -1.0
        for customer in unique:
            if customer in seeds:
                continue
            score = min(problem.dist[customer][seed] for seed in seeds)
            if score > best_score:
                best_score = score
                best_customer = customer
        if best_customer is None:
            break
        seeds.append(best_customer)
    return seeds


def build_customer_pool_orderings(
        problem: HCVRPProblem, customers: List[int], attempts: int = 4
) -> List[List[int]]:
    unique = list(dict.fromkeys(customers))
    if not unique:
        return [[]]
    cx = sum(problem.coords[c][0] for c in unique) / len(unique)
    cy = sum(problem.coords[c][1] for c in unique) / len(unique)
    orders: List[List[int]] = [
        sorted(unique, key=lambda c: (-problem.demands[c], c)),
        sorted(unique, key=lambda c: (-((problem.coords[c][0] - cx) ** 2 + (problem.coords[c][1] - cy) ** 2), c)),
        sorted(unique, key=lambda c: (problem.coords[c][0], problem.coords[c][1], c)),
    ]
    while len(orders) < max(1, attempts):
        shuffled = unique[:]
        random.shuffle(shuffled)
        orders.append(shuffled)

    deduped: List[List[int]] = []
    seen: Set[Tuple[int, ...]] = set()
    for order in orders:
        key = tuple(order)
        if key not in seen:
            seen.add(key)
            deduped.append(order)
    return deduped


def rebuild_customer_pool_into_routes(
        problem: HCVRPProblem,
        customers: List[int],
        target_route_count: int,
        attempts: int = 4
) -> Optional[Tuple[Route_matrix, List[int]]]:
    if not customers:
        return [], []
    target_route_count = max(1, target_route_count)
    orderings = build_customer_pool_orderings(problem, customers, attempts=attempts)
    attempt_items = list(enumerate(orderings[:max(1, attempts)]))

    def run_attempt(attempt_idx: int, ordering: List[int]) -> Optional[Tuple[Route_matrix, List[int], float]]:
        if attempt_idx == 0:
            seeds = farthest_customer_seeds(problem, customers, target_route_count)
        else:
            head = ordering[:target_route_count]
            seeds = list(dict.fromkeys(head))
            if len(seeds) < target_route_count:
                extra = farthest_customer_seeds(problem, customers, target_route_count)
                for customer in extra:
                    if customer not in seeds:
                        seeds.append(customer)
                    if len(seeds) >= target_route_count:
                        break
        if not seeds:
            return None

        routes: Route_matrix = []
        vehicle_ids: List[int] = []
        type_usage: Dict[int, int] = {}
        seed_set = set(seeds)
        feasible_seeding = True
        for seed in seeds:
            route = [0, seed, 0]
            v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
            if v_id is None:
                feasible_seeding = False
                break
            routes.append(route)
            vehicle_ids.append(v_id)
            type_usage[v_id] = type_usage.get(v_id, 0) + 1
        if not feasible_seeding:
            return None

        pending = [c for c in ordering if c not in seed_set]
        route_centroids = compute_route_centroids(problem, routes)
        best_local: Optional[Tuple[Route_matrix, List[int], float]] = None
        for allow_new in (False, True):
            routes_try = clone_routes(routes)
            vehicle_ids_try = vehicle_ids[:]
            usage_try = dict(type_usage)
            pending_try = pending[:]
            if _apply_regret_insertion(
                    problem, routes_try, vehicle_ids_try, usage_try, pending_try,
                    allow_new_route=allow_new, route_centroids=route_centroids[:]):
                candidate = evaluate_solution(problem, routes_try, vehicle_ids_try)
                if candidate.feasible:
                    score = candidate.total_cost
                    if best_local is None or score < best_local[2]:
                        best_local = (routes_try, vehicle_ids_try, score)
                break
        return best_local

    best: Optional[Tuple[Route_matrix, List[int], float]] = None
    parallel_workers = min(4, len(attempt_items))
    if parallel_workers > 1:
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            future_map = {
                executor.submit(run_attempt, attempt_idx, ordering): attempt_idx
                for attempt_idx, ordering in attempt_items
            }
            for future in as_completed(future_map):
                result = future.result()
                if result is not None and (best is None or result[2] < best[2]):
                    best = result
    else:
        for attempt_idx, ordering in attempt_items:
            result = run_attempt(attempt_idx, ordering)
            if result is not None and (best is None or result[2] < best[2]):
                best = result

    if best is None:
        return None
    return best[0], best[1]


def focused_cluster_rebuild(
        problem: HCVRPProblem, state: "SolutionState",
        max_bad_routes: int = 3, max_neighbor_routes: int = 2,
        max_routes_to_rebuild: int = 5
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if route_core(route)]
    if len(active) < 2:
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    scored = []
    for r_idx in active:
        route = state.routes[r_idx]
        core = route_core(route)
        if len(core) < 3:
            continue
        spread = _state_route_spread(problem, state, r_idx)
        route_arr = _state_route_arrays(state)[r_idx] if (NUMBA_AVAILABLE and np is not None) else None
        outlier_sum = sum(customer_outlier_score(problem, route, c, route_arr=route_arr) for c in _state_route_outliers(
            problem, state, r_idx, min(3, len(core))
        ))
        score = 2.0 * spread + 0.35 * state.route_distances[r_idx] + 0.10 * outlier_sum
        scored.append((score, r_idx))
    if not scored:
        return clone_solution_state(state)

    scored.sort(key=lambda x: (-x[0], x[1]))
    selected: List[int] = []
    for _, r_idx in scored[:max_bad_routes]:
        if r_idx not in selected:
            selected.append(r_idx)

    for r_idx in selected[:]:
        if len(selected) >= max_routes_to_rebuild:
            break
        pairs = []
        xi, yi = centroids[r_idx]
        route_set = _state_route_core_set(state, r_idx)
        for other in active:
            if other == r_idx or other in selected:
                continue
            xj, yj = centroids[other]
            dx = xi - xj
            dy = yi - yj
            overlap = len(route_set & _state_route_core_set(state, other))
            pairs.append((-(overlap), dx * dx + dy * dy, other))
        pairs.sort(key=lambda x: (x[0], x[1], x[2]))
        for _, _, other in pairs[:max_neighbor_routes]:
            if other not in selected:
                selected.append(other)
            if len(selected) >= max_routes_to_rebuild:
                break

    selected = selected[:max_routes_to_rebuild]
    if len(selected) < 2:
        return clone_solution_state(state)

    rebuild_customers: List[int] = []
    kept_routes: Route_matrix = []
    kept_vehicle_ids: List[int] = []
    selected_set = set(selected)
    for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
        if idx in selected_set:
            rebuild_customers.extend(route_core(route))
        else:
            kept_routes.append(normalize_route(route))
            kept_vehicle_ids.append(v_id)

    if not rebuild_customers:
        return clone_solution_state(state)

    best_candidate: Optional[SolutionState] = None
    attempts = int(ALGO_CONFIG["targeted_rebuild_attempts"])
    for pending in build_customer_pool_orderings(problem, rebuild_customers, attempts=attempts):
        routes_try = clone_routes(kept_routes)
        vehicle_ids_try = kept_vehicle_ids[:]
        type_usage = _type_usage_from_ids(vehicle_ids_try)
        route_centroids = compute_route_centroids(problem, routes_try) if routes_try else []
        pending_try = pending[:]
        if not _apply_regret_insertion(
                problem, routes_try, vehicle_ids_try, type_usage, pending_try,
                allow_new_route=True, route_centroids=route_centroids):
            continue
        candidate = evaluate_solution(problem, routes_try, vehicle_ids_try)
        if candidate.feasible and (best_candidate is None or candidate.total_cost < best_candidate.total_cost):
            best_candidate = candidate
    if best_candidate is not None and best_candidate.total_cost < state.total_cost:
        return best_candidate
    return clone_solution_state(state)


def worst_route_surgery_phase(
        problem: HCVRPProblem, state: "SolutionState",
        max_targets: int = 2, neighbor_routes: int = 2, max_routes_to_rebuild: int = 4
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if route_core(route)]
    if len(active) < 2:
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    ranked = sorted(
        ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
        key=lambda x: (-x[0], x[1])
    )
    best_state = clone_solution_state(state)

    for _, target_idx in ranked[:max_targets]:
        selected = [target_idx]
        xi, yi = centroids[target_idx]
        neighbors = []
        target_set = _state_route_core_set(state, target_idx)
        for other in active:
            if other == target_idx:
                continue
            xj, yj = centroids[other]
            overlap = len(target_set & _state_route_core_set(state, other))
            neighbors.append((-(overlap), (xi - xj) ** 2 + (yi - yj) ** 2, other))
        neighbors.sort(key=lambda x: (x[0], x[1], x[2]))
        for _, _, other in neighbors[:neighbor_routes]:
            selected.append(other)
        selected = selected[:max_routes_to_rebuild]

        pooled_customers: List[int] = []
        kept_routes: Route_matrix = []
        kept_vehicle_ids: List[int] = []
        selected_set = set(selected)
        for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
            if idx in selected_set:
                pooled_customers.extend(route_core(route))
            else:
                kept_routes.append(normalize_route(route))
                kept_vehicle_ids.append(v_id)

        rebuilt = rebuild_customer_pool_into_routes(problem, pooled_customers, len(selected))
        if rebuilt is None:
            continue
        rebuilt_routes, rebuilt_vehicle_ids = rebuilt
        candidate_routes = kept_routes + rebuilt_routes
        candidate_vehicle_ids = kept_vehicle_ids + rebuilt_vehicle_ids
        candidate = evaluate_solution(problem, candidate_routes, candidate_vehicle_ids)
        if candidate.feasible and candidate.total_cost < best_state.total_cost:
            best_state = candidate

    return best_state


def worst_route_outlier_purge_phase(
        problem: HCVRPProblem, state: "SolutionState",
        max_routes: int = 3, outliers_per_route: int = 3
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if len(route_core(route)) >= 4]
    if not active:
        return clone_solution_state(state)

    ranked = sorted(
        ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
        key=lambda x: (-x[0], x[1])
    )
    removed: List[int] = []
    seen: Set[int] = set()
    for _, r_idx in ranked[:max_routes]:
        core = route_core(state.routes[r_idx])
        if len(core) <= 2:
            continue
        take = min(outliers_per_route, max(1, len(core) - 2))
        for customer in _state_route_outliers(problem, state, r_idx, take):
            if customer not in seen:
                seen.add(customer)
                removed.append(customer)

    if not removed:
        return clone_solution_state(state)

    routes = remove_customers_from_routes(state.routes, removed)
    vehicle_ids: List[int] = []
    type_usage: Dict[int, int] = {}
    for route in routes:
        v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
        if v_id is None:
            return clone_solution_state(state)
        vehicle_ids.append(v_id)
        type_usage[v_id] = type_usage.get(v_id, 0) + 1

    pending = removed[:]
    if not _apply_regret_insertion(problem, routes, vehicle_ids, type_usage, pending):
        return clone_solution_state(state)

    candidate = evaluate_solution(problem, routes, vehicle_ids)
    if cleanup_candidate_is_better(problem, state, candidate):
        return candidate
    return clone_solution_state(state)


def state_has_route_pathology(problem: HCVRPProblem, state: "SolutionState") -> bool:
    return _state_has_route_pathology(problem, state)


def cleanup_candidate_is_better(
        problem: HCVRPProblem, base_state: "SolutionState", candidate: "SolutionState"
) -> bool:
    if not candidate.feasible:
        return False
    if candidate.total_cost < base_state.total_cost:
        return True
    base_bad = max(route_badness_score(problem, base_state, i) for i, r in enumerate(base_state.routes) if route_core(r))
    cand_bad = max(route_badness_score(problem, candidate, i) for i, r in enumerate(candidate.routes) if route_core(r))
    cost_slack = float(ALGO_CONFIG["targeted_cleanup_cost_slack"])
    badness_gain = float(ALGO_CONFIG["targeted_cleanup_badness_gain"])
    return candidate.total_cost <= base_state.total_cost + cost_slack and cand_bad + badness_gain < base_bad


def worst_route_shatter_phase(
        problem: HCVRPProblem, state: "SolutionState",
        neighbor_routes: int = 1, extra_routes: int = 1
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if len(route_core(route)) >= 4]
    if not active:
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    target_idx = max(active, key=lambda r_idx: route_badness_score(problem, state, r_idx))
    selected = [target_idx]
    xi, yi = centroids[target_idx]
    neighbors = []
    for other in active:
        if other == target_idx:
            continue
        xj, yj = centroids[other]
        neighbors.append((((xi - xj) ** 2 + (yi - yj) ** 2), other))
    neighbors.sort(key=lambda x: (x[0], x[1]))
    for _, other in neighbors[:neighbor_routes]:
        selected.append(other)

    pooled_customers: List[int] = []
    kept_routes: Route_matrix = []
    kept_vehicle_ids: List[int] = []
    selected_set = set(selected)
    for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
        if idx in selected_set:
            pooled_customers.extend(route_core(route))
        else:
            kept_routes.append(normalize_route(route))
            kept_vehicle_ids.append(v_id)
    if not pooled_customers:
        return clone_solution_state(state)

    rebuilt = rebuild_customer_pool_into_routes(
        problem,
        pooled_customers,
        target_route_count=max(1, len(selected) + extra_routes),
        attempts=max(2, int(ALGO_CONFIG["targeted_rebuild_attempts"])),
    )
    if rebuilt is None:
        return clone_solution_state(state)
    rebuilt_routes, rebuilt_vehicle_ids = rebuilt
    candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
    if cleanup_candidate_is_better(problem, state, candidate):
        return candidate
    return clone_solution_state(state)


def worst_route_micro_lns_phase(
        problem: HCVRPProblem, state: "SolutionState",
        neighbor_routes: int = 2, extra_routes: int = 1, attempts: int = 6
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if len(route_core(route)) >= 4]
    if len(active) < 2:
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    target_idx = max(active, key=lambda r_idx: route_badness_score(problem, state, r_idx))
    selected = [target_idx]
    xi, yi = centroids[target_idx]
    neighbors = []
    target_set = _state_route_core_set(state, target_idx)
    for other in active:
        if other == target_idx:
            continue
        xj, yj = centroids[other]
        overlap = len(target_set & _state_route_core_set(state, other))
        neighbors.append((-(overlap), (xi - xj) ** 2 + (yi - yj) ** 2, other))
    neighbors.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, _, other in neighbors[:neighbor_routes]:
        selected.append(other)

    pooled_customers: List[int] = []
    kept_routes: Route_matrix = []
    kept_vehicle_ids: List[int] = []
    selected_set = set(selected)
    for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
        if idx in selected_set:
            pooled_customers.extend(route_core(route))
        else:
            kept_routes.append(normalize_route(route))
            kept_vehicle_ids.append(v_id)

    if not pooled_customers:
        return clone_solution_state(state)

    best_candidate: Optional[SolutionState] = None
    for target_route_count in (
            max(1, len(selected)),
            max(1, len(selected) + extra_routes),
    ):
        rebuilt = rebuild_customer_pool_into_routes(
            problem,
            pooled_customers,
            target_route_count=target_route_count,
            attempts=max(2, attempts),
        )
        if rebuilt is None:
            continue
        rebuilt_routes, rebuilt_vehicle_ids = rebuilt
        candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
        if not candidate.feasible:
            continue
        if best_candidate is None or candidate.total_cost < best_candidate.total_cost:
            best_candidate = candidate

    if best_candidate is not None and cleanup_candidate_is_better(problem, state, best_candidate):
        return best_candidate
    return clone_solution_state(state)


def full_moon_phase(
        problem: HCVRPProblem, state: "SolutionState",
        max_bad_routes: int = 2, neighbor_routes: int = 2,
        max_routes_to_rebuild: int = 4, attempts: int = 5,
        post_ls_rounds: int = 1
) -> "SolutionState":
    if not _state_has_route_pathology(problem, state):
        return clone_solution_state(state)
    active = [i for i, route in enumerate(state.routes) if len(route_core(route)) >= 3]
    if len(active) < 2:
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    ranked = sorted(
        ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
        key=lambda x: (-x[0], x[1])
    )

    selected: List[int] = []
    for _, r_idx in ranked[:max_bad_routes]:
        if r_idx not in selected:
            selected.append(r_idx)

    for r_idx in selected[:]:
        if len(selected) >= max_routes_to_rebuild:
            break
        xi, yi = centroids[r_idx]
        target_set = _state_route_core_set(state, r_idx)
        neighbors = []
        for other in active:
            if other == r_idx or other in selected:
                continue
            xj, yj = centroids[other]
            overlap = len(target_set & _state_route_core_set(state, other))
            neighbors.append((-(overlap), (xi - xj) ** 2 + (yi - yj) ** 2, other))
        neighbors.sort(key=lambda x: (x[0], x[1], x[2]))
        for _, _, other in neighbors[:neighbor_routes]:
            if other not in selected:
                selected.append(other)
            if len(selected) >= max_routes_to_rebuild:
                break

    selected = selected[:max_routes_to_rebuild]
    if len(selected) < 2:
        return clone_solution_state(state)

    pooled_customers: List[int] = []
    kept_routes: Route_matrix = []
    kept_vehicle_ids: List[int] = []
    selected_set = set(selected)
    for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
        if idx in selected_set:
            pooled_customers.extend(route_core(route))
        else:
            kept_routes.append(_ensure_normalized(route))
            kept_vehicle_ids.append(v_id)

    if not pooled_customers:
        return clone_solution_state(state)

    rebuilt = rebuild_customer_pool_into_routes(
        problem,
        pooled_customers,
        target_route_count=len(selected),
        attempts=max(2, attempts),
    )
    if rebuilt is None:
        return clone_solution_state(state)

    rebuilt_routes, rebuilt_vehicle_ids = rebuilt
    candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
    if not candidate.feasible:
        return clone_solution_state(state)

    if post_ls_rounds > 0:
        candidate = intensify_local_search(problem, candidate, max_rounds=post_ls_rounds)

    if candidate.feasible and candidate.total_cost < state.total_cost:
        return candidate
    return clone_solution_state(state)


def maybe_targeted_cleanup(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    if not _state_has_route_pathology(problem, state):
        return state
    if random.random() >= float(ALGO_CONFIG["targeted_cleanup_prob"]):
        return state
    return targeted_cleanup_phase(problem, state)


def targeted_cleanup_phase(problem: HCVRPProblem, state: "SolutionState") -> "SolutionState":
    if not state_has_route_pathology(problem, state):
        return clone_solution_state(state)

    best_state = clone_solution_state(state)
    candidate = worst_route_outlier_purge_phase(problem, best_state, max_routes=1, outliers_per_route=2)
    if cleanup_candidate_is_better(problem, best_state, candidate):
        best_state = candidate

    if state_has_route_pathology(problem, best_state):
        candidate = worst_route_micro_lns_phase(
            problem, best_state,
            neighbor_routes=int(ALGO_CONFIG["micro_lns_neighbor_routes"]),
            extra_routes=int(ALGO_CONFIG["micro_lns_extra_routes"]),
            attempts=int(ALGO_CONFIG["micro_lns_attempts"]),
        )
        if cleanup_candidate_is_better(problem, best_state, candidate):
            best_state = candidate

    if state_has_route_pathology(problem, best_state):
        candidate = worst_route_shatter_phase(
            problem, best_state,
            neighbor_routes=int(ALGO_CONFIG["targeted_cleanup_neighbor_routes"]),
            extra_routes=int(ALGO_CONFIG["targeted_cleanup_extra_routes"]),
        )
        if cleanup_candidate_is_better(problem, best_state, candidate):
            best_state = candidate

    if state_has_route_pathology(problem, best_state):
        candidate = focused_cluster_rebuild(
            problem, best_state,
            max_bad_routes=1,
            max_neighbor_routes=2,
            max_routes_to_rebuild=3,
        )
        if cleanup_candidate_is_better(problem, best_state, candidate):
            best_state = candidate

    if state_has_route_pathology(problem, best_state):
        candidate = worst_route_surgery_phase(
            problem, best_state,
            max_targets=1,
            neighbor_routes=1,
            max_routes_to_rebuild=2,
        )
        if cleanup_candidate_is_better(problem, best_state, candidate):
            best_state = candidate

    if best_state.feasible and best_state.total_cost <= state.total_cost:
        return best_state
    return clone_solution_state(state)


# ==============================================================================
#  PATH RELINK / ALPHA GUIDED REBUILD
# ==============================================================================

def build_route_customer_sets(routes: Route_matrix) -> List[Set[int]]:
    return [set(route_core(r)) for r in routes]

def select_path_relink_customers(
        current_state: "SolutionState", target_state: "SolutionState", max_customers: int = 20
) -> List[int]:
    current_sets = build_route_customer_sets(current_state.routes)
    target_sets  = build_route_customer_sets(target_state.routes)
    current_map  = build_customer_to_route_map(current_state.routes)
    target_map   = build_customer_to_route_map(target_state.routes)
    scored = []
    for customer in flatten_customers_from_routes(current_state.routes):
        cidx = current_map[customer]; tidx = target_map.get(customer)
        if tidx is None: continue
        overlap  = len(current_sets[cidx] & target_sets[tidx])
        mismatch = len(target_sets[tidx]) - overlap
        if mismatch > 0: scored.append((mismatch, len(target_sets[tidx]), customer))
    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return [c for _, _, c in scored[:max_customers]]

def guided_customer_relocation(
        problem: HCVRPProblem, current_state: "SolutionState",
        target_state: "SolutionState", customer: int, max_target_routes: int = 4
) -> Optional["SolutionState"]:
    current_routes      = clone_routes(current_state.routes)
    current_vehicle_ids = current_state.vehicle_ids[:]
    current_map         = build_customer_to_route_map(current_routes)
    target_route_sets   = build_route_customer_sets(target_state.routes)
    target_map          = build_customer_to_route_map(target_state.routes)
    from_idx  = current_map.get(customer); target_idx = target_map.get(customer)
    if from_idx is None or target_idx is None: return None
    target_group = target_route_sets[target_idx]
    route_scores = []
    for r_idx, route in enumerate(current_routes):
        if r_idx == from_idx: continue
        overlap = len(set(route_core(route)) & target_group)
        if overlap > 0: route_scores.append((overlap, -current_state.route_costs[r_idx], r_idx))
    if not route_scores: return None
    route_scores.sort(key=lambda x: (-x[0], x[1], x[2]))
    best_state = None
    for _, _, to_idx in route_scores[:max_target_routes]:
        from_core = route_core(current_routes[from_idx])
        if customer not in from_core: continue
        reduced_core = [n for n in from_core if n != customer]
        to_route     = current_routes[to_idx]
        insert_pos, _ = choose_best_insertion_position(problem, to_route, customer)
        to_core      = route_core(to_route); to_core.insert(insert_pos - 1, customer)
        cr = clone_routes(current_routes)
        cr[from_idx] = [0] + reduced_core + [0]; cr[to_idx] = [0] + to_core + [0]
        cr, cv = remove_empty_routes(cr, current_vehicle_ids[:])
        cs     = evaluate_solution(problem, cr, cv)
        if cs.feasible and (best_state is None or cs.total_cost < best_state.total_cost):
            best_state = cs
    return best_state

def elite_path_relink(
        problem: HCVRPProblem, start_state: "SolutionState",
        target_state: "SolutionState", max_steps: int = 8
) -> "SolutionState":
    current = clone_solution_state(start_state)
    best    = clone_solution_state(start_state)
    limits  = get_local_search_limits(start_state)
    for _ in range(min(max_steps, int(limits["path_steps"]))):
        candidates = []
        for customer in select_path_relink_customers(current, target_state, int(limits["path_customers"])):
            candidate = guided_customer_relocation(problem, current, target_state, customer)
            if candidate is not None: candidates.append(candidate)
        if not candidates: break
        candidates.sort(key=lambda s: s.total_cost)
        current = candidates[0]
        if current.feasible and current.total_cost < best.total_cost:
            best = clone_solution_state(current)
    return best

def alpha_guided_rebuild(
        problem: HCVRPProblem, base_state: "SolutionState",
        alpha_state: "SolutionState", inherit_frac: float = 0.35
) -> "SolutionState":
    base_routes     = clone_routes(base_state.routes)
    alpha_customers = flatten_customers_from_routes(alpha_state.routes)
    n_customers     = len(alpha_customers)
    if n_customers == 0: return clone_solution_state(base_state)
    q                  = max(1, int(inherit_frac * n_customers))
    selected_customers = set(random.sample(alpha_customers, q))
    reduced_routes     = remove_customers_from_routes(base_routes, selected_customers)
    reduced_vehicle_ids: List[int] = []; type_usage: Dict[int, int] = {}
    for route in reduced_routes:
        v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
        if v_id is None: return clone_solution_state(base_state)
        reduced_vehicle_ids.append(v_id); type_usage[v_id] = type_usage.get(v_id, 0) + 1
    pending = list(selected_customers)
    if not _apply_regret_insertion(problem, reduced_routes, reduced_vehicle_ids, type_usage, pending):
        return clone_solution_state(base_state)
    rebuilt = evaluate_solution(problem, reduced_routes, reduced_vehicle_ids)
    rebuilt = maybe_targeted_cleanup(problem, rebuilt)
    return rebuilt


# ==============================================================================
#  ALPHA / HUNT MEKANİZMASI
# ==============================================================================

def select_alpha_index(wolves: List[Wolf]) -> int:
    cq = minmax_normalize_costs_to_quality([w.best_state.total_cost for w in wolves])
    bq = minmax_normalize_values([w.blood for w in wolves])
    hq = minmax_normalize_values([w.best_quality_score for w in wolves])
    cw = float(ALGO_CONFIG["alpha_cost_weight"])
    bw = float(ALGO_CONFIG["alpha_blood_weight"])
    hw = float(ALGO_CONFIG["alpha_history_weight"])
    total = cw + bw + hw; cw /= total; bw /= total; hw /= total
    best_idx = 0; best_score = cw * cq[0] + bw * bq[0] + hw * hq[0]
    for i in range(1, len(wolves)):
        score = cw * cq[i] + bw * bq[i] + hw * hq[i]
        if score > best_score: best_score = score; best_idx = i
    return best_idx

def try_accept_neighbor(
        wolf: Wolf, candidate_state: "SolutionState",
        closed_regions: Optional[List[Set[Edge]]] = None,
        lambda_reg: float = 0.0,
        a: float = 1.5, b: float = 2.0, c: float = 1.0, b_par: float = 1.2,
        min_improve_gain: float = 0.10, quality_gain_weight: float = 0.50
) -> bool:
    old_cost = wolf.state.total_cost; new_cost = candidate_state.total_cost
    raw_delta    = new_cost - old_cost
    scaled_delta = register_delta_and_get_scaled_delta(wolf, raw_delta)
    region_pen   = 0.0
    if closed_regions and lambda_reg > 0.0:
        sim        = max_region_similarity_routes(candidate_state.routes, closed_regions)
        region_pen = lambda_reg * sim
    effective_delta = scaled_delta + region_pen
    if raw_delta <= 0:
        prev_quality  = wolf.quality_score
        wolf.state    = wolf.clone_state(candidate_state)
        # SO: best_state güncellemesi hard_feasible ile korunur
        if candidate_state.hard_feasible and candidate_state.total_cost < wolf.best_state.total_cost:
            wolf.best_state = wolf.clone_state(candidate_state)
        standardized_improve = max(0.0, -scaled_delta)
        wolf.blood += min_improve_gain + standardized_improve + quality_gain_weight * prev_quality
        return True
    d       = max(0.0, effective_delta)
    p_allow = math.exp(-a * (d ** b))
    if random.random() > p_allow: return False
    penalty = c * (math.exp(b_par * d) - 1.0)
    if wolf.blood >= penalty:
        wolf.blood = max(0.0, wolf.blood - penalty)
        wolf.state = wolf.clone_state(candidate_state)
        return True
    return False

def explore_one_step(
        wolf: Wolf, closed_regions: Optional[List[Set[Edge]]] = None,
        lambda_reg: float = 0.0, a: float = 1.5, b: float = 2.0,
        c: float = 1.0, b_par: float = 1.2
):
    candidate_state = propose_random_neighbor(wolf.problem, wolf.state)
    try_accept_neighbor(wolf=wolf, candidate_state=candidate_state,
                        closed_regions=closed_regions, lambda_reg=lambda_reg,
                        a=a, b=b, c=c, b_par=b_par)

def free_search_phase(
        wolves: List[Wolf], iterations_per_wolf: int = 200,
        closed_regions: Optional[List[Set[Edge]]] = None,
        lambda_reg: float = 0.0, a: float = 1.5, b: float = 2.0,
        c: float = 1.0, b_par: float = 1.2,
        oscillation: Optional[OscillationController] = None   # SO: faz kontrolü
):
    update_interval = int(ALGO_CONFIG["free_search_quality_update_interval"])
    for step in range(iterations_per_wolf):
        # SO: her iterasyonda oscillation adımı — periyot dolunca faz değişir.
        # Faz değişikliği _ACTIVE_OSCILLATION üzerinden evaluate fonksiyonlarını etkiler.
        if oscillation is not None:
            oscillation.step()

        for wolf in wolves:
            explore_one_step(wolf=wolf, closed_regions=closed_regions,
                             lambda_reg=lambda_reg, a=a, b=b, c=c, b_par=b_par)
        if (step + 1) % update_interval == 0:
            update_population_quality_scores(wolves)
    update_population_quality_scores(wolves)

def reset_wolves_for_new_hunt(wolves: List[Wolf], reserve_blood: float = 2.0, clear_history: bool = True):
    for wolf in wolves:
        wolf.blood = reserve_blood
        if clear_history: wolf.delta_history.clear()

def hunt_one_wolf_towards_alpha(
        wolf: Wolf, guide_state: "SolutionState",
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, rr_repeats: int = 2,
        bandit: Optional["DestroyBandit"] = None,
        destroy_modes: Optional[List[str]] = None,
) -> "SolutionState":
    current  = alpha_guided_rebuild(wolf.problem, wolf.state, guide_state, inherit_frac)
    current  = intensify_local_search(wolf.problem, current, max_rounds=3)
    current  = maybe_targeted_cleanup(wolf.problem, current)
    relinked = elite_path_relink(wolf.problem, current, guide_state, max_steps=6)
    relinked = intensify_local_search(wolf.problem, relinked, max_rounds=2)
    relinked = maybe_targeted_cleanup(wolf.problem, relinked)
    if relinked.feasible and relinked.total_cost < current.total_cost: current = relinked
    best = current
    for rr_idx in range(rr_repeats):
        destroy_mode = (
            destroy_modes[rr_idx]
            if destroy_modes is not None and rr_idx < len(destroy_modes)
            else sample_destroy_mode()
        )
        candidate = ruin_and_rebuild_routes(
            wolf.problem, best, ruin_frac=ruin_frac,
            destroy_mode=destroy_mode,
            bandit=(None if destroy_modes is not None else bandit),
            use_bandit=(bandit is not None and destroy_modes is None),
        )
        candidate = intensify_local_search(wolf.problem, candidate, max_rounds=3)
        candidate = maybe_targeted_cleanup(wolf.problem, candidate)
        if candidate.total_cost < best.total_cost: best = candidate
    return best

def hunt_around_alpha(
        wolves: List[Wolf], alpha_idx: int,
        elite_pool: Optional[List["SolutionState"]] = None,
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, rr_repeats: int = 2,
        bandit: Optional["DestroyBandit"] = None,
        parallel_workers: int = 1,
) -> Tuple["SolutionState", float]:
    alpha           = wolves[alpha_idx]
    alpha_state     = alpha.best_state
    hunt_best_state = alpha.clone_state(alpha_state)
    hunt_best_cost  = alpha_state.total_cost
    tasks: List[Tuple[int, Wolf, "SolutionState", Optional[List[str]]]] = []
    for i, wolf in enumerate(wolves):
        if i == alpha_idx:
            continue
        guide_states = [alpha_state]
        elite_guide  = choose_elite_guide(elite_pool or [], wolf.state)
        if elite_guide is not None and state_edge_similarity(elite_guide, alpha_state) < 0.98:
            guide_states.append(elite_guide)
        for guide_state in guide_states:
            destroy_modes = None
            if bandit is not None and parallel_workers > 1:
                destroy_modes = [
                    choose_bandit_mode_for_state(wolf.problem, wolf.state, bandit)
                    for _ in range(rr_repeats)
                ]
            tasks.append((i, wolf, guide_state, destroy_modes))

    wolf_best_candidates: Dict[int, "SolutionState"] = {}
    if parallel_workers > 1 and len(tasks) > 1:
        with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            future_map = {
                executor.submit(
                    hunt_one_wolf_towards_alpha,
                    wolf,
                    guide_state,
                    inherit_frac,
                    ruin_frac,
                    rr_repeats,
                    bandit,
                    destroy_modes,
                ): i
                for i, wolf, guide_state, destroy_modes in tasks
            }
            for future in as_completed(future_map):
                i = future_map[future]
                candidate = future.result()
                prev = wolf_best_candidates.get(i)
                if prev is None or candidate.total_cost < prev.total_cost:
                    wolf_best_candidates[i] = candidate
    else:
        for i, wolf, guide_state, destroy_modes in tasks:
            candidate = hunt_one_wolf_towards_alpha(
                wolf, guide_state, inherit_frac, ruin_frac, rr_repeats,
                bandit=bandit, destroy_modes=destroy_modes
            )
            prev = wolf_best_candidates.get(i)
            if prev is None or candidate.total_cost < prev.total_cost:
                wolf_best_candidates[i] = candidate

    for i, candidate in wolf_best_candidates.items():
        wolf = wolves[i]
        wolf.update_if_better(candidate)
        if candidate.hard_feasible and candidate.total_cost < hunt_best_cost:  # SO: hard_feasible
            hunt_best_state = alpha.clone_state(candidate)
            hunt_best_cost = candidate.total_cost
    alpha.update_if_better(hunt_best_state)
    update_population_quality_scores(wolves)
    return hunt_best_state, hunt_best_cost

def get_global_best_state(wolves: List[Wolf]) -> "SolutionState":
    best = wolves[0].clone_state(wolves[0].best_state)
    for w in wolves[1:]:
        if w.best_state.total_cost < best.total_cost: best = w.clone_state(w.best_state)
    return best


# ==============================================================================
#  ANA ÇALIŞMA FONKSİYONU
# ==============================================================================

def run_bloodhound_hcvrp(
        problem: HCVRPProblem,
        num_wolves: int = 12, num_hunts: int = 20, explore_iterations: int = 120,
        reserve_blood: float = 2.0, lambda_reg: float = 0.30,
        a: float = 1.5, b: float = 2.0, c: float = 1.0, b_par: float = 1.2,
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, rr_repeats: int = 2,
        wolf_parallel_workers: int = 1,
        verbose: bool = True, random_seed: Optional[int] = None,
        # SO: Strategic Oscillation parametreleri (None → ALGO_CONFIG'ten alınır)
        so_cap_penalty_weight: Optional[float] = None,
        so_relax_period:       Optional[int]   = None,
        so_enforce_period:     Optional[int]   = None,
) -> "SolutionState":
    if random_seed is not None: random.seed(random_seed)

    # SO: OscillationController — parametreler verilmezse ALGO_CONFIG kullanılır
    oscillation = OscillationController(
        cap_penalty_weight=(so_cap_penalty_weight
                            if so_cap_penalty_weight is not None
                            else float(ALGO_CONFIG["so_cap_penalty_weight"])),
        relax_period=(so_relax_period
                      if so_relax_period is not None
                      else int(ALGO_CONFIG["so_relax_period"])),
        enforce_period=(so_enforce_period
                        if so_enforce_period is not None
                        else int(ALGO_CONFIG["so_enforce_period"])),
    )

    # SO: Başlangıçta oscillation kapalı (hard mod); sadece free_search'te aktif
    set_active_oscillation(None)

    wolves      = initialize_wolves(problem, num_wolves)
    update_population_quality_scores(wolves)
    global_best = get_global_best_state(wolves)
    elite_pool  = update_elite_pool([], [w.best_state for w in wolves] + [global_best])
    closed_regions: List[Set[Edge]] = []
    hunts_without_global_improvement = 0

    bandit = DestroyBandit(eps=float(ALGO_CONFIG["destroy_bandit_eps"]))
    wolf_parallel_workers = max(1, min(int(wolf_parallel_workers), max(1, num_wolves - 1)))

    if verbose:
        n_types = len(problem.vehicle_types)
        print(f"Instance    : {getattr(problem, 'original_vrplib_name', '?')}")
        print(f"Nodes       : {problem.n_nodes}  |  Customers: {len(problem.customer_ids)}")
        print(f"Vehicle types: {n_types}  (toplam araç: {len(problem.vehicles)})")
        print(f"Wolf workers: {wolf_parallel_workers}")
        print(f"Cost model  : {getattr(problem, 'cost_model_name', 'unknown')}")
        print(f"Cost scale  : {getattr(problem, 'cost_scale_factor', 1.0)}")
        for vt in problem.vehicle_types:
            print(f"  Type {vt.type_id}: cap={vt.capacity}  cpm={vt.cost_per_km}  "
                  f"fc={vt.fixed_cost}  max={vt.max_count}")
        print(f"SO cap_pw={oscillation.cap_penalty_weight}  "
              f"relax_period={oscillation.relax_period}  "
              f"enforce_period={oscillation.enforce_period}")
        print(f"Initial best cost: {round(global_best.total_cost, 4)}")
        print(f"Initial routes   : {route_count(global_best)}")

    for hunt_idx in range(num_hunts):
        reset_wolves_for_new_hunt(wolves, reserve_blood=reserve_blood, clear_history=True)

        # SO: free_search başlangıcında oscillation devreye alınır, ENFORCE'tan başlar
        oscillation.set_phase("ENFORCE")
        set_active_oscillation(oscillation)

        free_search_phase(
            wolves=wolves, iterations_per_wolf=explore_iterations,
            closed_regions=closed_regions, lambda_reg=lambda_reg,
            a=a, b=b, c=c, b_par=b_par,
            oscillation=oscillation,    # SO: faz adımlaması için geçilir
        )

        # SO: Hunt ve LS aşamalarına geçmeden önce oscillation kapatılır (hard mod).
        # Bu sayede araç ataması, regret insertion ve intensify_local_search
        # her zaman hard kapasite kısıtı ile çalışır.
        set_active_oscillation(None)

        alpha_idx = select_alpha_index(wolves)
        hunt_best_state, hunt_best_cost = hunt_around_alpha(
            wolves, alpha_idx, elite_pool, inherit_frac, ruin_frac, rr_repeats,
            bandit=bandit, parallel_workers=wolf_parallel_workers
        )
        if hunts_without_global_improvement >= int(ALGO_CONFIG["stagnation_hunt_limit"]):
            kick = stagnation_kick(
                problem, hunt_best_state,
                ruin_frac=min(float(ALGO_CONFIG["stagnation_ruin_cap"]),
                              ruin_frac + float(ALGO_CONFIG["stagnation_ruin_boost"])),
                bandit=bandit
            )
            if kick.feasible and kick.total_cost < hunt_best_cost:
                hunt_best_state = kick; hunt_best_cost = kick.total_cost

        full_moon = full_moon_phase(
            problem, hunt_best_state,
            max_bad_routes=int(ALGO_CONFIG["full_moon_bad_routes"]),
            neighbor_routes=int(ALGO_CONFIG["full_moon_neighbor_routes"]),
            max_routes_to_rebuild=int(ALGO_CONFIG["full_moon_max_routes"]),
            attempts=int(ALGO_CONFIG["full_moon_attempts"]),
            post_ls_rounds=int(ALGO_CONFIG["full_moon_post_ls_rounds"]),
        )
        if full_moon.feasible and full_moon.total_cost < hunt_best_cost:
            hunt_best_state = full_moon
            hunt_best_cost = full_moon.total_cost

        if hunt_best_cost < global_best.total_cost:
            prev_global_best_cost = global_best.total_cost
            global_best = wolves[alpha_idx].clone_state(hunt_best_state)
            if bandit.last_mode is not None:
                bandit.update(
                    bandit.last_mode,
                    bandit.reward_value("global_best", max(0.0, prev_global_best_cost - hunt_best_cost))
                )
            hunts_without_global_improvement = 0
        else:
            hunts_without_global_improvement += 1

        closed_regions.append(build_edge_signature_from_routes(hunt_best_state.routes))
        update_population_quality_scores(wolves)
        elite_pool = update_elite_pool(
            elite_pool, [w.best_state for w in wolves] + [hunt_best_state, global_best]
        )

        if verbose:
            c_min, c_mean, c_max = population_cost_stats(wolves)
            so_s = oscillation.stats()
            print(
                f"Hunt {hunt_idx+1}/{num_hunts} | alpha={alpha_idx} | "
                f"hunt_best={hunt_best_cost:.4f} | global_best={global_best.total_cost:.4f} | "
                f"hunt_routes={route_count(hunt_best_state)} | best_routes={route_count(global_best)} | "
                f"pop_min={c_min:.4f} | pop_mean={c_mean:.4f} | pop_max={c_max:.4f} | "
                f"stagnation={hunts_without_global_improvement} | "
                f"closed_regions={len(closed_regions)} | elite_pool={len(elite_pool)} | "
                f"bandit={bandit.stats()} | "
                f"so_relax={so_s['relax_entered']} so_enforce={so_s['enforce_entered']}"  # SO
            )

    # SO: Çalışma bitti — oscillation kapalı bırakılır
    set_active_oscillation(None)

    return global_best


# ==============================================================================
#  GİRİŞ NOKTASI
# ==============================================================================

if __name__ == "__main__":

    SEARCH_PARAMS = {
        "num_wolves":         8,
        "num_hunts":          5,
        "explore_iterations": 100,
        "reserve_blood":      2.5,
        "lambda_reg":         1,
        "a":                  1.0,
        "b":                  2.0,
        "c":                  1.3,
        "b_par":              1.2,
        "inherit_frac":       0.70,
        "ruin_frac":          0.30,
        "rr_repeats":         5,
        "wolf_parallel_workers": 4,
        "verbose":            True,
        "random_seed":        666,
        # SO: İsteğe bağlı override — None bırakılırsa ALGO_CONFIG değerleri kullanılır
        "so_cap_penalty_weight": None,
        "so_relax_period":       None,
        "so_enforce_period":     None,
    }

    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if input_path is not None and input_path.suffix.lower() == ".json":
        print(f"Veri dosyasi: {input_path.name}")
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        problem, app_meta = build_problem_from_app_payload(payload)
        solver_config = app_meta.get("solver_config", {})
        solver_params = solver_config.get("params") if isinstance(solver_config, dict) else None
        if isinstance(solver_params, dict):
            SEARCH_PARAMS.update(solver_params)
    else:
        DATASET_DIR  = Path(__file__).resolve().parent / "Test_data"
        DATASET_FILE = input_path if input_path is not None else (DATASET_DIR / "X200-HD.txt")

        if (not DATASET_FILE.exists()) or DATASET_FILE.stat().st_size == 0:
            fallback_files = sorted(
                [path for path in DATASET_DIR.glob("*.txt") if path.stat().st_size > 0]
            )
            if not fallback_files:
                raise ValueError("Test_data icinde kullanilabilir dolu bir dataset yok.")
            DATASET_FILE = fallback_files[0]

        print(f"Veri dosyasi: {DATASET_FILE.name}")
        problem = load_hfvrp_instance_from_vrplib(DATASET_FILE)

    best_state = run_bloodhound_hcvrp(problem=problem, **SEARCH_PARAMS)
    final_output = build_bloodhound_vrp_style_output(problem, best_state)

    print("\n===== FINAL BEST =====")
    print("Feasible:", final_output["Feasible"])
    print("Total cost:", final_output["Total cost"])
    print("Vehicle IDs:", final_output["Vehicle IDs"])
    print("Route loads:", final_output["Route loads"])
    print("Route distances:", final_output["Route distances"])
    print("Route times:", final_output["Route times"])
    print("Route costs:", final_output["Route costs"])
    for i, route in enumerate(final_output["Routes"]):
        print(f"Route {i}: {route}")
