import random
import math
import heapq
import sys
import time
import xml.etree.ElementTree as ET
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
NUMBA_CACHE_ENABLED = __name__ not in {"<run_path>", "__main__"}
_REBUILD_EXECUTOR: Optional[ThreadPoolExecutor] = None
_WOLF_EXECUTOR: Optional[ThreadPoolExecutor] = None
_LOCAL_SEARCH_EXECUTOR: Optional[ThreadPoolExecutor] = None
_EXACT_ROUTE_TSP_CACHE: Dict[Tuple[int, int, Tuple[int, ...]], Optional[Tuple[Route, float, float, float, float]]] = {}


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
    "alpha_cost_weight":                     0.72,
    "alpha_blood_weight":                    0.08,
    "alpha_history_weight":                  0.20,
    "elite_pool_max_size":                   3,
    "elite_max_similarity":                  0.82,
    "regret3_probability":                   0.35,
    "destroy_prob_shaw":                     0.35,
    "destroy_prob_worst":                    0.25,
    "destroy_prob_targeted":                 0.25,
    "targeted_destroy_neighbor_routes":      4,
    "route_elimination_max_routes":          2,
    "stagnation_hunt_limit":                 1,
    "stagnation_ruin_boost":                 0.20,
    "stagnation_ruin_cap":                   0.55,
    "plateau_level_step":                    2,
    "plateau_max_level":                     3,
    "plateau_ls_round_bonus":                1,
    "plateau_route_operator_mult":           1.60,
    "plateau_intra_operator_mult":           0.85,
    "plateau_ruin_mult":                     1.25,
    "plateau_hunt_chain_pass_bonus":         1,
    "plateau_cleanup_prob_bonus":            0.25,
    "plateau_accept_a_mult":                 0.78,
    "plateau_accept_c_mult":                 0.82,
    "plateau_accept_b_par_mult":             0.90,
    "plateau_alpha_novelty_weight":          0.12,
    "plateau_elite_guide_similarity_cap":    0.94,
    "route_pressure_avg_route_cost_frac":    0.18,
    "route_pressure_excess_power":           1.35,
    "pack_crossover_parent_count":           3,
    "pack_crossover_seed_routes":            6,
    "pack_crossover_orderings":              4,
    "archive_population_max_size":           16,
    "archive_similarity_cap":                0.90,
    "archive_activation_hunt":               2,
    "archive_injection_interval":            1,
    "archive_offspring_count":               3,
    "archive_injection_wolves":              2,
    "archive_parent_pool_size":              8,
    "archive_injection_rel_slack":           0.10,
    "archive_injection_novelty_min":         0.14,
    "diversification_burst_interval":        2,
    "diversification_burst_wolves":          2,
    "diversification_burst_ruin_mult":       1.45,
    "route_pool_max_entries":                96,
    "route_pool_attempts":                   4,
    "route_pool_parallel_min_attempts":      3,
    "route_pool_parallel_max_workers":       4,
    "pool_rebuild_parallel_min_attempts":    2,
    "pool_rebuild_parallel_min_customers":   48,
    "exact_pool_customer_cap":               12,
    "exact_pool_route_slack":                1,
    "exact_route_polish_enabled":            True,
    "exact_route_polish_customer_cap":       12,
    "exact_route_polish_max_routes":         64,
    "exact_route_polish_min_gain":           1e-7,
    "exact_2route_repartition_enabled":      True,
    "exact_2route_customer_cap":             14,
    "exact_2route_max_pairs":                1,
    "exact_2route_badness_sigma":            1.10,
    "exact_2route_min_gain":                 1e-7,
    "ejection_chain_base_depth":             2,
    "ejection_chain_plateau_depth_bonus":    1,
    "stagnation_reset_rel_improvement":      0.0030,
    "stagnation_reset_abs_improvement":      5.0,
    "stagnation_soft_rel_improvement":       0.0008,
    "stagnation_soft_abs_improvement":       1.0,
    "stagnation_soft_reset_decrement":       1,
    "adaptive_small_route_count":            15,
    "adaptive_medium_route_count":           25,
    "adaptive_dense_route_threshold":        8.5,
    "adaptive_medium_route_threshold":       6.5,
    "free_search_quality_update_interval":   4,
    "wolf_parallel_max_workers":             8,
    "local_search_parallel_enabled":         True,
    "local_search_parallel_min_routes":      6,
    "local_search_parallel_min_ops":         4,
    "local_search_parallel_max_workers":     6,
    "regret_parallel_min_pending":           32,
    "regret_parallel_max_workers":           4,
    "insertion_cache_refresh_every":         4,
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
    "targeted_cleanup_early_severe_sigma":   1.65,
    "targeted_cleanup_legacy_stage_base":    2,
    "targeted_cleanup_legacy_stage_plateau_bonus": 1,
    "targeted_cleanup_neighbor_routes":      2,
    "targeted_cleanup_extra_routes":         2,
    "pulse_hunt_interval":                   3,
    "pulse_pair_multiplier":                 1.75,
    "pulse_intra_multiplier":                1.50,
    "pulse_path_multiplier":                 1.50,
    "pulse_cleanup_prob":                    0.60,
    "pulse_full_moon_attempt_bonus":         2,
    "pulse_full_moon_neighbor_bonus":        1,
    "pulse_full_moon_post_ls_bonus":         1,
    "pulse_micro_hgs_enabled":               True,
    "pulse_micro_hgs_generations":           200,
    "pulse_micro_hgs_tournament_size":       3,
    "pulse_micro_hgs_keep_children":         6,
    "pulse_micro_hgs_inject_wolves":         2,
    "pulse_micro_hgs_mutation_prob":         0.35,
    "pulse_micro_hgs_initial_mutation_prob": 0.70,
    "pulse_micro_hgs_final_mutation_prob":   0.08,
    "pulse_micro_hgs_max_extra_routes":      2,
    "pulse_micro_hgs_decode_variants":       5,
    "pulse_micro_hgs_strong_polish_top":     2,
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
    "operator_bandit_eps":                   0.10,
    "operator_bandit_reaction_factor":       0.28,
    "operator_bandit_score_floor":           0.25,
    "operator_prior_pack":                   1.25,
    "operator_prior_ejection":               1.05,
    "operator_prior_merge":                  1.20,
    "operator_prior_route_pool":             1.10,
    "operator_prior_fallback":               0.90,
    "operator_skip_score_mult":              1.20,
    "delta_scale_cost_floor_ratio":          0.0010,
    "delta_scale_min_abs_floor":             1.0,
    "route_selection_numba_buffer_mult":     2,
    "candidate_route_soft_expand":           4,
    # SO: Strategic Oscillation parametreleri
    "so_cap_penalty_weight":                 20.0,   # birim kapasite aşımı başına ceza
    "so_relax_period":                       25,      # RELAX fazında kalınacak adım sayısı
    "so_enforce_period":                     25,      # ENFORCE fazında kalınacak adım sayısı
    "adaptive_profiles": {
        "dense": {
            "regret_customer_limit":   20,
            "regret_route_limit":       8,
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
            "regret_customer_limit":   25,
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
            "regret_customer_limit":   30,
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

        self.dist = self.build_tsplib_euc2d_matrix(self.coords)
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
        first_type = self.vehicle_types[0]
        self.is_homogeneous_fleet = all(
            abs(vt.capacity - first_type.capacity) <= 1e-9
            and abs(vt.cost_per_km - first_type.cost_per_km) <= 1e-9
            and abs(vt.fixed_cost - first_type.fixed_cost) <= 1e-9
            and abs(vt.speed - first_type.speed) <= 1e-9
            for vt in self.vehicle_types
        )

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


def build_exact_euclidean_distance_matrix(coords: List[Point]) -> Distance_matrix:
    n = len(coords)
    dist = [[0.0] * n for _ in range(n)]
    for i in range(n):
        x1, y1 = coords[i]
        for j in range(n):
            x2, y2 = coords[j]
            dx = x1 - x2
            dy = y1 - y2
            dist[i][j] = math.sqrt(dx * dx + dy * dy)
    return dist


def _refresh_problem_distance_dependent_state(problem: "HCVRPProblem") -> None:
    problem.granular_neighbors = problem._build_granular_neighbors(
        int(ALGO_CONFIG["granular_neighbor_k"])
    )
    if np is not None:
        problem.dist_np = np.asarray(problem.dist, dtype=np.float64)
        gk = int(ALGO_CONFIG["granular_neighbor_k"])
        problem.granular_neighbors_np = np.full((problem.n_nodes, gk), -1, dtype=np.int64)
        problem.granular_neighbor_counts_np = np.zeros(problem.n_nodes, dtype=np.int64)
        for customer in range(problem.n_nodes):
            neigh = problem.granular_neighbors[customer]
            count = min(len(neigh), gk)
            problem.granular_neighbor_counts_np[customer] = count
            for idx in range(count):
                problem.granular_neighbors_np[customer, idx] = neigh[idx]


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
    _refresh_problem_distance_dependent_state(problem)
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


def load_cmt_xml_instance(file_path: "str | Path") -> "HCVRPProblem":
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset bulunamadi: {path}")
    tree = ET.parse(path)
    root = tree.getroot()

    nodes_parent = root.find("./network/nodes")
    if nodes_parent is None:
        raise ValueError(f"XML node listesi bulunamadi: {path.name}")

    raw_nodes: Dict[int, Point] = {}
    depot_original_id: Optional[int] = None
    customer_original_ids: List[int] = []
    for node in nodes_parent.findall("node"):
        original_id = int(node.attrib["id"])
        node_type = node.attrib.get("type", "1")
        cx = float(node.findtext("cx", "0"))
        cy = float(node.findtext("cy", "0"))
        raw_nodes[original_id] = (cx, cy)
        if node_type == "0":
            depot_original_id = original_id
        else:
            customer_original_ids.append(original_id)

    if depot_original_id is None:
        raise ValueError(f"XML depot node bulunamadi: {path.name}")

    requests_parent = root.find("./requests")
    raw_demands: Dict[int, float] = {}
    if requests_parent is not None:
        for request in requests_parent.findall("request"):
            node_id = int(request.attrib["node"])
            quantity = float(request.findtext("quantity", "0"))
            raw_demands[node_id] = quantity

    vehicle_profiles = root.findall("./fleet/vehicle_profile")
    if not vehicle_profiles:
        raise ValueError(f"XML fleet profile bulunamadi: {path.name}")

    capacities: List[float] = []
    for profile in vehicle_profiles:
        capacity = float(profile.findtext("capacity", "0"))
        if capacity <= 0:
            raise ValueError(f"Gecersiz kapasite: {path.name}")
        count = int(profile.attrib.get("count", profile.attrib.get("number", "0")) or 0)
        if count > 0:
            capacities.extend([capacity] * count)
        else:
            capacities.append(capacity)

    ordered_original_ids = [depot_original_id] + sorted(customer_original_ids)
    original_to_internal = {original_id: idx for idx, original_id in enumerate(ordered_original_ids)}
    coords = [raw_nodes[original_id] for original_id in ordered_original_ids]
    demands = [0.0] + [float(raw_demands.get(original_id, 0.0)) for original_id in ordered_original_ids[1:]]
    dist = build_exact_euclidean_distance_matrix(coords)

    customer_count = len(customer_original_ids)
    concrete_capacities = capacities if len(capacities) > 1 else capacities * max(1, customer_count)
    vehicles = [
        Vehicle(
            vehicle_id=i,
            capacity=float(capacity),
            cost_per_km=1.0,
            fixed_cost=0.0,
            speed=1.0,
        )
        for i, capacity in enumerate(concrete_capacities)
    ]

    problem = HCVRPProblem(
        coords=coords,
        demands=demands,
        vehicles=vehicles,
        time_windows=[(0.0, float("inf"))] * len(coords),
        service_times=[0.0] * len(coords),
    )
    problem.dist = dist
    _refresh_problem_distance_dependent_state(problem)
    problem.original_vrplib_name = root.findtext("./info/name", path.stem)  # type: ignore[attr-defined]
    problem.original_vrplib_depot_id = depot_original_id  # type: ignore[attr-defined]
    problem.original_to_internal_node = original_to_internal  # type: ignore[attr-defined]
    problem.cost_model_name = "cmt_exact_euclidean_distance_only"  # type: ignore[attr-defined]
    problem.has_explicit_fixed_costs = False  # type: ignore[attr-defined]
    problem.cost_scale_factor = 1.0  # type: ignore[attr-defined]
    return problem


def load_supported_instance(
        file_path: "str | Path",
        benchmark_compatible_hfvrp_costs: bool = True
) -> "HCVRPProblem":
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return load_cmt_xml_instance(path)
    return load_hfvrp_instance_from_vrplib(path, benchmark_compatible_hfvrp_costs)


def resolve_supported_dataset_path(path: "str | Path") -> Path:
    dataset_path = Path(path)
    if dataset_path.is_file():
        return dataset_path
    if dataset_path.is_dir():
        candidates = sorted([
            p for p in dataset_path.rglob("*")
            if p.is_file() and p.suffix.lower() in {".txt", ".xml"}
        ])
        if not candidates:
            raise ValueError(f"Desteklenen instance bulunamadi: {dataset_path}")
        return candidates[0]
    raise FileNotFoundError(f"Dataset bulunamadi: {dataset_path}")


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


def _resizeable_executor(
        current: Optional[ThreadPoolExecutor],
        max_workers: int,
        prefix: str,
) -> ThreadPoolExecutor:
    requested = max(1, int(max_workers))
    current_workers = getattr(current, "_max_workers", 0) if current is not None else 0
    if current is None or current_workers < requested:
        if current is not None:
            current.shutdown(wait=False, cancel_futures=False)
        current = ThreadPoolExecutor(max_workers=requested, thread_name_prefix=prefix)
    return current


def get_shared_rebuild_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    global _REBUILD_EXECUTOR
    _REBUILD_EXECUTOR = _resizeable_executor(_REBUILD_EXECUTOR, max_workers, "bh-rebuild")
    return _REBUILD_EXECUTOR


def get_shared_wolf_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    global _WOLF_EXECUTOR
    _WOLF_EXECUTOR = _resizeable_executor(_WOLF_EXECUTOR, max_workers, "bh-wolf")
    return _WOLF_EXECUTOR


def get_shared_local_search_executor(max_workers: int = 4) -> ThreadPoolExecutor:
    global _LOCAL_SEARCH_EXECUTOR
    _LOCAL_SEARCH_EXECUTOR = _resizeable_executor(_LOCAL_SEARCH_EXECUTOR, max_workers, "bh-ls")
    return _LOCAL_SEARCH_EXECUTOR


def internal_node_to_original(problem: HCVRPProblem, node: int) -> int:
    if node == 0:
        return int(getattr(problem, "original_vrplib_depot_id", 1))
    mapping = getattr(problem, "original_to_internal_node", None)
    if not mapping:
        return node + 1
    for original, internal in mapping.items():
        if internal == node:
            return int(original)
    return node + 1


def route_to_original_ids(problem: HCVRPProblem, route: Route) -> Route:
    return [internal_node_to_original(problem, n) for n in route]

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
    if getattr(problem, "is_homogeneous_fleet", False) and 0 <= current_type_id < len(problem.vehicle_types):
        current_type = get_vehicle_type_by_id(problem, current_type_id)
        route_ok, _, route_dist, _, route_cost = evaluate_route_for_vehicle(problem, nr, current_type)
        if route_ok:
            return current_type_id, route_cost, route_dist
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

def build_initial_customer_order(
        problem: HCVRPProblem,
        strategy: str = "demand_desc"
) -> List[int]:
    customers = problem.customer_ids[:]
    if not customers:
        return customers

    depot_x, depot_y = problem.coords[0]
    if strategy == "demand_desc":
        random.shuffle(customers)
        customers.sort(key=lambda c: (problem.demands[c], -problem.dist[0][c]), reverse=True)
        return customers
    if strategy == "radial_desc":
        return sorted(
            customers,
            key=lambda c: (((problem.coords[c][0] - depot_x) ** 2 + (problem.coords[c][1] - depot_y) ** 2), problem.demands[c], c),
            reverse=True,
        )
    if strategy == "sweep":
        return sorted(
            customers,
            key=lambda c: (
                math.atan2(problem.coords[c][1] - depot_y, problem.coords[c][0] - depot_x),
                -problem.dist[0][c],
                c,
            ),
        )
    if strategy == "x_then_y":
        return sorted(customers, key=lambda c: (problem.coords[c][0], problem.coords[c][1], -problem.demands[c], c))
    if strategy == "y_then_x":
        return sorted(customers, key=lambda c: (problem.coords[c][1], problem.coords[c][0], -problem.demands[c], c))
    random.shuffle(customers)
    return customers


def perturb_initial_customer_order(order: List[int], attempt_idx: int) -> List[int]:
    customers = order[:]
    if len(customers) <= 2:
        return customers
    if attempt_idx % 3 == 1:
        cut = attempt_idx % len(customers)
        return customers[cut:] + customers[:cut]
    if attempt_idx % 3 == 2:
        block = max(2, min(8, len(customers) // 10 or 2))
        for start in range(0, len(customers), block):
            customers[start:start + block] = reversed(customers[start:start + block])
        return customers
    random.shuffle(customers)
    return customers

def generate_feasible_solution(
        problem: HCVRPProblem,
        sort_by_demands_desc: bool = True,
        randomize_ties: bool = True,
        max_attempts: int = 50,
        customer_order: Optional[List[int]] = None,
) -> "SolutionState":
    customer_list = problem.customer_ids[:]
    for attempt_idx in range(max_attempts):
        if customer_order is not None:
            customers = perturb_initial_customer_order(customer_order, attempt_idx)
        else:
            customers = customer_list[:]
        if customer_order is None and sort_by_demands_desc:
            if randomize_ties: random.shuffle(customers)
            customers.sort(key=lambda c: problem.demands[c], reverse=True)
        elif customer_order is None:
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
    def create_random(cls, problem: HCVRPProblem, strategy_idx: int = 0) -> "Wolf":
        strategies = ("demand_desc", "radial_desc", "sweep", "x_then_y", "y_then_x", "random")
        strategy = strategies[strategy_idx % len(strategies)]
        init_state = generate_feasible_solution(
            problem,
            sort_by_demands_desc=(strategy == "demand_desc"),
            randomize_ties=True,
            customer_order=build_initial_customer_order(problem, strategy),
        )
        return cls(problem=problem, state=init_state, best_state=init_state,
                   blood=0.0, quality_score=0.0, best_quality_score=0.0, delta_history=[])

    def clone_state(self, state: "SolutionState") -> "SolutionState":
        return clone_solution_state(state)

    def update_if_better(self, candidate_state: "SolutionState"):
        if candidate_is_progress(
                self.problem, self.state, candidate_state,
                allow_structural_progress=True):
            self.state = self.clone_state(candidate_state)
        # SO: best_state yalnız hard_feasible (kapasite dahil) çözümler alır.
        # RELAX sırasında üretilen cap-ihlalli çözümler best_state'e girmez.
        if candidate_state.hard_feasible and candidate_state.total_cost < self.best_state.total_cost:
            self.best_state = self.clone_state(candidate_state)


def initialize_wolves(problem: HCVRPProblem, num_wolves: int) -> List[Wolf]:
    return [Wolf.create_random(problem, strategy_idx=i) for i in range(num_wolves)]


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
    vals = sorted(abs(v) for v in values if abs(v) > 1e-9)
    if not vals:
        return fallback
    m    = len(vals)
    med  = vals[m // 2] if m % 2 == 1 else 0.5 * (vals[m//2-1] + vals[m//2])
    q3_idx = min(m - 1, max(0, int(round(0.75 * (m - 1)))))
    q3 = vals[q3_idx]
    return max(med, 0.5 * q3, fallback, 1e-9)

def register_delta_and_get_scaled_delta(wolf: Wolf, raw_delta: float, max_history: int = 50) -> float:
    wolf.delta_history.append(raw_delta)
    if len(wolf.delta_history) > max_history: wolf.delta_history.pop(0)
    cost_floor = max(
        float(ALGO_CONFIG["delta_scale_min_abs_floor"]),
        abs(wolf.state.total_cost) * float(ALGO_CONFIG["delta_scale_cost_floor_ratio"]),
    )
    return raw_delta / robust_scale_from_history(wolf.delta_history, fallback=cost_floor)

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
        candidate._route_cores = {k: v[:] for k, v in list(state._route_cores.items())}
    if state._route_core_sets is not None:
        candidate._route_core_sets = {k: set(v) for k, v in list(state._route_core_sets.items())}
    if state._route_spreads is not None:
        candidate._route_spreads = state._route_spreads.copy()
    if state._route_outliers is not None:
        candidate._route_outliers = {k: v[:] for k, v in list(state._route_outliers.items())}
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


def evaluate_fixed_vehicle_route_delta_allow_removal(
        problem: HCVRPProblem,
        state: "SolutionState",
        route_updates: Dict[int, Route]
) -> Optional["SolutionState"]:
    hard_feasible = state.hard_feasible
    evaluated_by_idx: Dict[int, Tuple[Route, float, float, float, float]] = {}
    has_empty_route = False
    for route_idx, new_route in route_updates.items():
        vt = get_vehicle_type_by_id(problem, state.vehicle_ids[route_idx])
        route_ok, route_load, route_dist, route_time, route_cost = evaluate_route_for_vehicle(
            problem, new_route, vt
        )
        if not route_ok:
            return None
        normalized = _ensure_normalized(new_route)
        if not route_core(normalized):
            has_empty_route = True
        if route_load > vt.capacity + 1e-9:
            hard_feasible = False
        evaluated_by_idx[route_idx] = (normalized, route_load, route_dist, route_time, route_cost)

    if not has_empty_route:
        candidate = clone_state_with_updated_routes(
            state,
            [(idx, *evaluated_by_idx[idx]) for idx in evaluated_by_idx]
        )
        candidate.feasible = state.feasible
        candidate.hard_feasible = hard_feasible
        return candidate

    candidate = clone_solution_state(state)
    new_routes: Route_matrix = []
    new_vehicle_ids: List[int] = []
    new_route_loads: List[float] = []
    new_route_distances: List[float] = []
    new_route_times: List[float] = []
    new_route_costs: List[float] = []

    for idx, route in enumerate(state.routes):
        if idx in evaluated_by_idx:
            nr, rl, rd, rt, rc = evaluated_by_idx[idx]
        else:
            nr = _ensure_normalized(route)
            rl = state.route_loads[idx]
            rd = state.route_distances[idx]
            rt = state.route_times[idx]
            rc = state.route_costs[idx]
        if route_core(nr):
            new_routes.append(nr)
            new_vehicle_ids.append(state.vehicle_ids[idx])
            new_route_loads.append(rl)
            new_route_distances.append(rd)
            new_route_times.append(rt)
            new_route_costs.append(rc)

    candidate.routes = new_routes
    candidate.vehicle_ids = new_vehicle_ids
    candidate.route_loads = new_route_loads
    candidate.route_distances = new_route_distances
    candidate.route_times = new_route_times
    candidate.route_costs = new_route_costs
    candidate.total_cost = sum(new_route_costs)
    candidate.feasible = state.feasible
    candidate.hard_feasible = hard_feasible
    _invalidate_state_route_caches(candidate, None)
    return candidate


def evaluate_vehicle_reassignment_delta(
        problem: HCVRPProblem,
        state: "SolutionState",
        route_idx: int,
        new_type_id: int
) -> Optional["SolutionState"]:
    current_type_id = state.vehicle_ids[route_idx]
    if new_type_id == current_type_id:
        return clone_solution_state(state)
    type_usage = _type_usage_from_ids(state.vehicle_ids)
    type_usage[current_type_id] -= 1
    type_usage[new_type_id] = type_usage.get(new_type_id, 0) + 1
    if type_usage[new_type_id] > problem.vehicle_types[new_type_id].max_count:
        return None
    vt = get_vehicle_type_by_id(problem, new_type_id)
    route = state.routes[route_idx]
    route_ok, route_load, route_dist, route_time, route_cost = evaluate_route_for_vehicle(problem, route, vt)
    if not route_ok:
        return None
    candidate = clone_state_with_updated_route(
        state, route_idx, route, route_load, route_dist, route_time, route_cost
    )
    candidate.vehicle_ids[route_idx] = new_type_id
    candidate.feasible = state.feasible
    candidate.hard_feasible = state.hard_feasible and route_load <= vt.capacity + 1e-9
    return candidate

def state_edge_similarity(a: "SolutionState", b: "SolutionState") -> float:
    sa = build_edge_signature_from_routes(a.routes)
    sb = build_edge_signature_from_routes(b.routes)
    if not sa and not sb: return 1.0
    if not sa or not sb:  return 0.0
    union = len(sa | sb)
    return 0.0 if union == 0 else len(sa & sb) / union


def state_novelty_against_pool(
        state: "SolutionState",
        pool: List["SolutionState"],
) -> float:
    if not pool:
        return 1.0
    return 1.0 - max(state_edge_similarity(state, other) for other in pool)


def compute_plateau_level(stagnation_hunts: int) -> int:
    step = max(1, int(ALGO_CONFIG["plateau_level_step"]))
    max_level = max(0, int(ALGO_CONFIG["plateau_max_level"]))
    return min(max_level, max(0, stagnation_hunts) // step)


def get_plateau_acceptance_params(
        a: float,
        c: float,
        b_par: float,
        plateau_level: int,
) -> Tuple[float, float, float]:
    if plateau_level <= 0:
        return a, c, b_par
    a_mult = float(ALGO_CONFIG["plateau_accept_a_mult"]) ** plateau_level
    c_mult = float(ALGO_CONFIG["plateau_accept_c_mult"]) ** plateau_level
    b_par_mult = float(ALGO_CONFIG["plateau_accept_b_par_mult"]) ** plateau_level
    return a * a_mult, c * c_mult, b_par * b_par_mult


def get_plateau_ruin_frac(base_ruin_frac: float, plateau_level: int) -> float:
    if plateau_level <= 0:
        return base_ruin_frac
    boosted = base_ruin_frac * (float(ALGO_CONFIG["plateau_ruin_mult"]) ** plateau_level)
    return min(float(ALGO_CONFIG["stagnation_ruin_cap"]), boosted)


def get_plateau_hunt_chain_passes(base_hunt_chain_passes: int, plateau_level: int) -> int:
    if plateau_level <= 0:
        return base_hunt_chain_passes
    return max(1, base_hunt_chain_passes + plateau_level * int(ALGO_CONFIG["plateau_hunt_chain_pass_bonus"]))


def classify_improvement_magnitude(
        previous_cost: float,
        new_cost: float,
) -> str:
    improvement = previous_cost - new_cost
    if improvement <= 0.0:
        return "none"
    rel_improvement = improvement / max(abs(previous_cost), 1e-9)
    if (improvement >= float(ALGO_CONFIG["stagnation_reset_abs_improvement"])
            or rel_improvement >= float(ALGO_CONFIG["stagnation_reset_rel_improvement"])):
        return "strong"
    if (improvement >= float(ALGO_CONFIG["stagnation_soft_abs_improvement"])
            or rel_improvement >= float(ALGO_CONFIG["stagnation_soft_rel_improvement"])):
        return "soft"
    return "micro"

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


def update_archive_population(
        archive_population: List["SolutionState"],
        candidate_states: List["SolutionState"],
) -> List["SolutionState"]:
    return update_elite_pool(
        archive_population,
        candidate_states,
        max_size=int(ALGO_CONFIG["archive_population_max_size"]),
        max_similarity=float(ALGO_CONFIG["archive_similarity_cap"]),
    )

def choose_elite_guide(
        problem: HCVRPProblem,
        elite_pool: List["SolutionState"], reference_state: "SolutionState",
        plateau_level: int = 0,
) -> Optional["SolutionState"]:
    if not elite_pool: return None
    similarity_cap = float(ALGO_CONFIG["plateau_elite_guide_similarity_cap"])
    ranked = []
    for candidate in elite_pool:
        sim = state_edge_similarity(candidate, reference_state)
        novelty = state_novelty_against_pool(candidate, [s for s in elite_pool if s is not candidate])
        penalty = 1.0 if sim > similarity_cap else 0.0
        ranked.append((
            penalty,
            sim,
            -novelty,
            pressured_total_cost(problem, candidate, plateau_level),
            candidate.total_cost,
            candidate,
        ))
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))
    return clone_solution_state(ranked[0][5])

def route_count(state: "SolutionState") -> int:
    return len(state.routes)


def route_count_lower_bound(problem: HCVRPProblem) -> int:
    total_demand = sum(problem.demands[customer] for customer in problem.customer_ids)
    return max(1, math.ceil(total_demand / max(problem.max_vehicle_capacity, 1e-9)))


def route_pressure_penalty(
        problem: HCVRPProblem,
        state: "SolutionState",
        plateau_level: int = 0,
) -> float:
    if plateau_level <= 0:
        return 0.0
    excess_routes = max(0, route_count(state) - route_count_lower_bound(problem))
    if excess_routes <= 0:
        return 0.0
    avg_route_cost = state.total_cost / max(1, route_count(state))
    frac = float(ALGO_CONFIG["route_pressure_avg_route_cost_frac"])
    power = float(ALGO_CONFIG["route_pressure_excess_power"])
    return avg_route_cost * frac * plateau_level * (excess_routes ** power)


def pressured_total_cost(
        problem: HCVRPProblem,
        state: "SolutionState",
        plateau_level: int = 0,
) -> float:
    return state.total_cost + route_pressure_penalty(problem, state, plateau_level)

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


class HuntOperatorBandit:
    _MODES: Tuple[str, ...] = ("pack", "ejection", "merge", "route_pool", "fallback")

    def __init__(self, eps: float = 0.10):
        self.eps = eps
        self.reaction = float(ALGO_CONFIG["operator_bandit_reaction_factor"])
        self._scores: Dict[str, float] = {m: 1.0 for m in self._MODES}
        self._counts: Dict[str, int] = {m: 1 for m in self._MODES}
        self._priors: Dict[str, float] = {
            "pack": float(ALGO_CONFIG["operator_prior_pack"]),
            "ejection": float(ALGO_CONFIG["operator_prior_ejection"]),
            "merge": float(ALGO_CONFIG["operator_prior_merge"]),
            "route_pool": float(ALGO_CONFIG["operator_prior_route_pool"]),
            "fallback": float(ALGO_CONFIG["operator_prior_fallback"]),
        }

    def sample_order(self, include_fallback: bool = True) -> List[str]:
        modes = list(self._MODES if include_fallback else self._MODES[:-1])
        ordered: List[str] = []
        while modes:
            if random.random() < self.eps:
                chosen = random.choice(modes)
            else:
                total = sum(max(1e-9, self._scores[m]) * self._priors.get(m, 1.0) for m in modes)
                roll = random.random() * total
                acc = 0.0
                chosen = modes[-1]
                for mode in modes:
                    acc += max(1e-9, self._scores[mode]) * self._priors.get(mode, 1.0)
                    if roll <= acc:
                        chosen = mode
                        break
            ordered.append(chosen)
            modes.remove(chosen)
        return ordered

    def reward_value(
            self,
            base_state: "SolutionState",
            candidate: "SolutionState",
            problem: HCVRPProblem,
            plateau_level: int = 0,
    ) -> float:
        if not candidate.feasible:
            return float(ALGO_CONFIG["bandit_reward_fail"])
        pressured_gain = max(
            0.0,
            pressured_total_cost(problem, base_state, plateau_level)
            - pressured_total_cost(problem, candidate, plateau_level),
        )
        raw_gain = max(0.0, base_state.total_cost - candidate.total_cost)
        route_gain = max(0, route_count(base_state) - route_count(candidate))
        base_bad = max(
            (route_badness_score(problem, base_state, i) for i, r in enumerate(base_state.routes) if route_core(r)),
            default=0.0,
        )
        cand_bad = max(
            (route_badness_score(problem, candidate, i) for i, r in enumerate(candidate.routes) if route_core(r)),
            default=0.0,
        )
        badness_drop = max(0.0, base_bad - cand_bad)
        reward = float(ALGO_CONFIG["bandit_reward_feasible"])
        reward += 0.6 * math.sqrt(raw_gain)
        reward += 1.0 * math.sqrt(pressured_gain)
        reward += 0.8 * route_gain
        reward += float(ALGO_CONFIG["bandit_pathology_bonus_weight"]) * math.sqrt(badness_drop)
        if candidate.hard_feasible and (pressured_gain > 1e-9 or raw_gain > 1e-9):
            reward += float(ALGO_CONFIG["bandit_reward_improving"])
        return reward

    def update(self, mode: str, reward: float) -> None:
        floor = float(ALGO_CONFIG["operator_bandit_score_floor"])
        self._scores[mode] = max(
            floor,
            (1.0 - self.reaction) * self._scores[mode] + self.reaction * max(0.0, reward),
        )
        self._counts[mode] += 1

    def score(self, mode: str) -> float:
        return self._scores.get(mode, float(ALGO_CONFIG["operator_bandit_score_floor"]))

    def stats(self) -> Dict[str, float]:
        return {m: round(self._scores[m], 4) for m in self._MODES}


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
                delta_candidate = evaluate_fixed_vehicle_route_delta_allow_removal(
                    problem,
                    state,
                    {
                        from_idx: [0] + reduced_core + [0],
                        to_idx: new_to_route,
                    },
                )
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
    if getattr(problem, "is_homogeneous_fleet", False):
        return clone_solution_state(state)
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
    delta_candidate = evaluate_vehicle_reassignment_delta(problem, state, r_idx, new_type_id)
    if delta_candidate is not None:
        return delta_candidate
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


def is_pulse_hunt(hunt_number: int) -> bool:
    interval = max(0, int(ALGO_CONFIG["pulse_hunt_interval"]))
    return interval > 0 and hunt_number % interval == 0


def get_local_search_limits(
        state: "SolutionState",
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> Dict[str, float]:
    route_lengths = [len(route_core(r)) for r in state.routes if route_core(r)]
    if not route_lengths:
        limits = dict(ALGO_CONFIG["adaptive_profiles"]["light"])
    else:
        avg_len = sum(route_lengths) / len(route_lengths)
        max_len = max(route_lengths)
        if avg_len >= 8.0 or max_len >= 12:
            limits = dict(ALGO_CONFIG["adaptive_profiles"]["dense"])
        elif avg_len >= 6.0 or max_len >= 9:
            limits = dict(ALGO_CONFIG["adaptive_profiles"]["medium"])
        else:
            limits = dict(ALGO_CONFIG["adaptive_profiles"]["light"])

    if pulse_mode:
        pair_mult = float(ALGO_CONFIG["pulse_pair_multiplier"])
        intra_mult = float(ALGO_CONFIG["pulse_intra_multiplier"])
        path_mult = float(ALGO_CONFIG["pulse_path_multiplier"])
        for key in ("relocate_pairs", "two_opt_pairs", "cross_pairs", "or_opt_pairs", "max_cuts_per_route", "max_cross_starts"):
            limits[key] = max(1, int(round(float(limits[key]) * pair_mult)))
        limits["intra_routes"] = max(1, int(round(float(limits["intra_routes"]) * intra_mult)))
        limits["path_customers"] = max(1, int(round(float(limits["path_customers"]) * path_mult)))
        limits["path_steps"] = max(1, int(round(float(limits["path_steps"]) * path_mult)))
        limits["ls_rounds"] = max(1, int(limits["ls_rounds"]) + 1)
    if plateau_level > 0:
        route_mult = float(ALGO_CONFIG["plateau_route_operator_mult"]) ** plateau_level
        intra_mult = float(ALGO_CONFIG["plateau_intra_operator_mult"]) ** plateau_level
        for key in ("relocate_pairs", "two_opt_pairs", "cross_pairs", "or_opt_pairs", "max_cuts_per_route", "max_cross_starts", "path_customers", "path_steps"):
            limits[key] = max(1, int(round(float(limits[key]) * route_mult)))
        limits["intra_routes"] = max(1, int(round(float(limits["intra_routes"]) * intra_mult)))
        limits["route_elimination_tries"] = max(1, int(round(float(limits["route_elimination_tries"]) * route_mult)))
        limits["ls_rounds"] = max(1, int(limits["ls_rounds"]) + plateau_level * int(ALGO_CONFIG["plateau_ls_round_bonus"]))
    return limits


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

    if candidate_is_progress(
            problem, state, best_state,
            allow_structural_progress=True):
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
                candidate = evaluate_fixed_vehicle_route_delta_allow_removal(
                    problem, state,
                    {
                        from_idx: [0] + reduced_core + [0],
                        to_idx: new_to_route,
                    },
                )
            if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                best_state = candidate
    if candidate_is_progress(
            problem, state, best_state,
            allow_structural_progress=True):
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
                    candidate = evaluate_fixed_vehicle_route_delta_allow_removal(
                        problem, state,
                        {
                            from_idx: [0] + reduced_core + [0],
                            to_idx: new_to_route,
                        },
                    )
                if candidate is not None and candidate.feasible and candidate.total_cost < best_state.total_cost:
                    best_state = candidate
    if candidate_is_progress(
            problem, state, best_state,
            allow_structural_progress=True):
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


def _best_total_cost_candidate(
        base_state: "SolutionState",
        candidates: List[Optional["SolutionState"]],
) -> Optional["SolutionState"]:
    best_candidate: Optional["SolutionState"] = None
    for candidate in candidates:
        if candidate is None or not candidate.feasible or candidate.total_cost >= base_state.total_cost:
            continue
        if best_candidate is None or candidate.total_cost < best_candidate.total_cost:
            best_candidate = candidate
    return best_candidate


def _best_progress_candidate(
        problem: HCVRPProblem,
        base_state: "SolutionState",
        candidates: List[Optional["SolutionState"]],
        plateau_level: int = 0,
) -> Optional["SolutionState"]:
    best_candidate: Optional["SolutionState"] = None
    for candidate in candidates:
        if candidate is None:
            continue
        if not candidate_is_progress(
                problem, base_state, candidate,
                allow_structural_progress=True,
                plateau_level=plateau_level):
            continue
        if (best_candidate is None
                or pressured_total_cost(problem, candidate, plateau_level) < pressured_total_cost(problem, best_candidate, plateau_level)
                or (pressured_total_cost(problem, candidate, plateau_level) == pressured_total_cost(problem, best_candidate, plateau_level)
                    and candidate.total_cost < best_candidate.total_cost)):
            best_candidate = candidate
    return best_candidate


def intensify_local_search(
        problem: HCVRPProblem, state: "SolutionState", max_rounds: int = 3,
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
    current = clone_solution_state(state)
    limits  = get_local_search_limits(current, pulse_mode=pulse_mode, plateau_level=plateau_level)
    if plateau_level > 0:
        op_sequence = [
            (best_improving_outlier_relocate,     {"max_source_routes":   int(ALGO_CONFIG["outlier_source_routes"]),
                                                   "max_target_routes":   int(ALGO_CONFIG["outlier_target_routes"]),
                                                   "max_outliers_per_route": int(ALGO_CONFIG["outlier_customers_per_route"])}),
            (best_improving_inter_route_relocate,  {"max_pairs":           int(limits["relocate_pairs"])}),
            (best_improving_two_customer_relocate, {"max_pairs":           max(1, int(limits["relocate_pairs"]) // 2)}),
            (best_improving_inter_route_2opt_star, {"max_pairs":           int(limits["two_opt_pairs"]),
                                                    "max_cuts_per_route":  int(limits["max_cuts_per_route"])}),
            (best_improving_cross_exchange,        {"max_pairs":           int(limits["cross_pairs"]),
                                                    "max_start_positions": int(limits["max_cross_starts"])}),
            (best_improving_intra_route_2opt,     {"max_routes":          int(limits["intra_routes"])}),
            (best_improving_or_opt,               {"max_routes":          int(limits["intra_routes"]),
                                                   "max_block_size":      3}),
        ]
    else:
        op_sequence = [
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
        ]
    use_parallel_ops = (
        bool(ALGO_CONFIG.get("local_search_parallel_enabled", False))
        and len(current.routes) >= int(ALGO_CONFIG["local_search_parallel_min_routes"])
        and len(op_sequence) >= int(ALGO_CONFIG["local_search_parallel_min_ops"])
    )
    ls_workers = min(
        int(ALGO_CONFIG["local_search_parallel_max_workers"]),
        max(1, len(op_sequence)),
    )
    round_budget = max(1, min(max_rounds, int(limits["ls_rounds"])))
    for _ in range(round_budget):
        improved = False
        cheap_improved = False
        if use_parallel_ops and ls_workers > 1:
            executor = get_shared_local_search_executor(ls_workers)
            task_states = [clone_solution_state(current) for _ in op_sequence]
            futures = [
                executor.submit(op, problem, task_state, **kwargs)
                for (op, kwargs), task_state in zip(op_sequence, task_states)
            ]
            best_parallel = _best_total_cost_candidate(current, [future.result() for future in futures])
            if best_parallel is not None:
                current = best_parallel
                improved = True
                cheap_improved = True
        else:
            for op, kwargs in op_sequence:
                candidate = op(problem, current, **kwargs)
                if candidate.feasible and candidate.total_cost < current.total_cost:
                    current = candidate
                    improved = True
                    cheap_improved = True
        if cheap_improved:
            continue
        heavy_ops = []
        if not getattr(problem, "is_homogeneous_fleet", False):
            heavy_ops.append((random_vehicle_reassignment, False))
        heavy_ops.append((
            lambda p, s: targeted_cleanup_phase(p, s, pulse_mode=pulse_mode, plateau_level=plateau_level),
            True,
        ))
        heavy_ops.append((lambda p, s: route_elimination_phase(p, s, int(limits["route_elimination_tries"])), True))
        if use_parallel_ops:
            executor = get_shared_local_search_executor(min(3, ls_workers))
            task_states = [clone_solution_state(current) for _ in heavy_ops]
            futures = [
                executor.submit(op, problem, task_state)
                for (op, _), task_state in zip(heavy_ops, task_states)
            ]
            best_heavy = _best_progress_candidate(problem, current, [future.result() for future in futures], plateau_level=plateau_level)
            if best_heavy is not None:
                current = best_heavy
                improved = True
        else:
            for op, allow_structural_progress in heavy_ops:
                candidate = op(problem, current)
                if candidate_is_progress(
                        problem, current, candidate,
                        allow_structural_progress=allow_structural_progress,
                        plateau_level=plateau_level):
                    current = candidate
                    improved = True
                    break
        if not improved:
            break
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
    return intensify_local_search(problem, kicked, max_rounds=3, plateau_level=1)


def diversification_burst(
        wolves: List[Wolf],
        global_best: "SolutionState",
        ruin_frac: float,
        plateau_level: int,
        alpha_idx: int,
        bandit: Optional["DestroyBandit"] = None,
) -> None:
    if plateau_level <= 0 or len(wolves) <= 1:
        return
    burst_count = min(max(1, int(ALGO_CONFIG["diversification_burst_wolves"])), max(0, len(wolves) - 1))
    ranked = []
    for idx, wolf in enumerate(wolves):
        if idx == alpha_idx:
            continue
        sim = state_edge_similarity(wolf.best_state, global_best)
        novelty = state_novelty_against_pool(wolf.best_state, [global_best])
        ranked.append((sim, -novelty, wolf.best_state.total_cost, idx))
    ranked.sort(key=lambda x: (-x[0], x[1], x[2], x[3]))
    destroy_modes = ("route", "targeted", "worst")
    for pick_idx, (_, _, _, wolf_idx) in enumerate(ranked[:burst_count]):
        wolf = wolves[wolf_idx]
        burst_ruin = min(
            float(ALGO_CONFIG["stagnation_ruin_cap"]),
            ruin_frac * float(ALGO_CONFIG["diversification_burst_ruin_mult"]),
        )
        candidate = ruin_and_rebuild_routes(
            wolf.problem,
            wolf.state,
            ruin_frac=burst_ruin,
            destroy_mode=destroy_modes[pick_idx % len(destroy_modes)],
            bandit=bandit,
            use_bandit=False,
        )
        candidate = focused_cluster_rebuild(
            wolf.problem, candidate,
            max_bad_routes=max(1, int(ALGO_CONFIG["cluster_rebuild_bad_routes"])),
            max_neighbor_routes=max(1, int(ALGO_CONFIG["cluster_rebuild_neighbor_routes"])),
            max_routes_to_rebuild=max(2, int(ALGO_CONFIG["cluster_rebuild_max_routes"])),
        )
        candidate = intensify_local_search(
            wolf.problem, candidate,
            max_rounds=3,
            pulse_mode=True,
            plateau_level=plateau_level,
        )
        candidate = maybe_targeted_cleanup(
            wolf.problem, candidate,
            pulse_mode=True,
            plateau_level=plateau_level,
        )
        wolf.update_if_better(candidate)


# ==============================================================================
#  REGRET INSERT
# ==============================================================================

def choose_best_insertion_position(
        problem: HCVRPProblem, route: Route, customer: int, route_arr=None
) -> Tuple[int, float]:
    nr = _ensure_normalized(route)
    if NUMBA_AVAILABLE and np is not None:
        best_pos, best_delta = _best_insertion_position_numba(
            _route_to_numpy(nr) if route_arr is None else route_arr, customer, problem.dist_np
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
    if route_centroids is None:
        route_centroids = compute_route_centroids(problem, routes)
    pre_limit = min(
        len(routes),
        max_candidates * max(1, int(ALGO_CONFIG["route_selection_numba_buffer_mult"]))
    )
    if NUMBA_AVAILABLE and np is not None and route_arrays is not None:
        centroid_arr = np.asarray(route_centroids, dtype=np.float64)
        preselected = list(_select_candidate_route_indices_numba(
            cx, cy, centroid_arr[:, 0], centroid_arr[:, 1], pre_limit
        ))
        gcount = int(problem.granular_neighbor_counts_np[customer]) if hasattr(problem, "granular_neighbor_counts_np") else 0
        if gcount <= 0:
            return preselected[:max_candidates]
        scored = []
        for r_idx in preselected:
            overlap = int(_count_granular_overlap_numba(
                route_arrays[r_idx],
                problem.granular_neighbors_np[customer],
                gcount,
            ))
            dx = cx - route_centroids[r_idx][0]
            dy = cy - route_centroids[r_idx][1]
            scored.append((-overlap, dx * dx + dy * dy, r_idx))
        scored.sort(key=lambda x: (x[0], x[1], x[2]))
        return [r for _, _, r in scored[:max_candidates]]
    granular_neighbors = set(problem.granular_neighbors[customer]) if customer < len(problem.granular_neighbors) else set()
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
        allow_new_route: bool = True,
        candidate_route_cache: Optional[Dict[Tuple[int, int, int], List[int]]] = None,
        cache_epoch: int = 0,
) -> List[Tuple]:
    def evaluate_route_candidates(candidate_indices: List[int], skip: Optional[Set[int]] = None) -> List[Tuple]:
        local_options: List[Tuple] = []
        skipped = skip or set()
        for r_idx in candidate_indices:
            if r_idx in skipped:
                continue
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
                if not route_ok:
                    continue
            route_arr = None if route_arrays is None else route_arrays[r_idx]
            pos, _          = choose_best_insertion_position(problem, route, customer, route_arr=route_arr)
            candidate_route = route[:]
            candidate_route.insert(pos, customer)
            best_vehicle    = assign_best_vehicle_for_existing_route(
                problem, candidate_route, current_type_id=current_type_id, type_usage=type_usage
            )
            if best_vehicle is None:
                continue
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
            local_options.append(((new_cost - current_cost) + geo_penalty, ("existing", r_idx, pos, new_type_id, new_cost)))
        return local_options

    options: List[Tuple] = []
    customer_demand = problem.demands[customer]
    centroid_weight = float(ALGO_CONFIG["insertion_centroid_penalty_weight"])
    outlier_weight  = float(ALGO_CONFIG["insertion_outlier_penalty_weight"])
    load_threshold  = float(ALGO_CONFIG["insertion_load_penalty_threshold"])
    load_weight     = float(ALGO_CONFIG["insertion_load_penalty_weight"])
    cache_key = (customer, candidate_route_limit, cache_epoch)
    if candidate_route_cache is not None and cache_key in candidate_route_cache:
        initial_candidates = candidate_route_cache[cache_key]
    else:
        initial_candidates = select_candidate_route_indices(
            problem, routes, customer,
            max_candidates=candidate_route_limit,
            route_centroids=route_centroids,
            route_arrays=route_arrays)
        if candidate_route_cache is not None:
            candidate_route_cache[cache_key] = initial_candidates
    options.extend(evaluate_route_candidates(initial_candidates))
    if len(options) < 2 and len(routes) > candidate_route_limit:
        expanded_limit = min(len(routes), candidate_route_limit + int(ALGO_CONFIG["candidate_route_soft_expand"]))
        if expanded_limit > candidate_route_limit:
            expanded_key = (customer, expanded_limit, cache_epoch)
            if candidate_route_cache is not None and expanded_key in candidate_route_cache:
                expanded_candidates = candidate_route_cache[expanded_key]
            else:
                expanded_candidates = select_candidate_route_indices(
                    problem, routes, customer,
                    max_candidates=expanded_limit,
                    route_centroids=route_centroids,
                    route_arrays=route_arrays)
                if candidate_route_cache is not None:
                    candidate_route_cache[expanded_key] = expanded_candidates
            options.extend(evaluate_route_candidates(expanded_candidates, skip=set(initial_candidates)))
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
        route_arrays=None,
        candidate_route_cache: Optional[Dict[Tuple[int, int, int], List[int]]] = None,
        cache_epoch: int = 0,
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

    use_parallel = len(prioritized) >= int(ALGO_CONFIG["regret_parallel_min_pending"])

    def score_customer(customer: int) -> Optional[Tuple]:
        options = build_insertion_options_for_customer(
            problem, routes, vehicle_ids, type_usage, customer,
            current_route_costs=current_route_costs,
            current_route_loads=current_route_loads,
            candidate_route_limit=candidate_route_limit,
            route_centroids=route_centroids,
            route_arrays=route_arrays,
            max_options=max(regret_k, 2),
            allow_new_route=allow_new_route,
            candidate_route_cache=None if use_parallel else candidate_route_cache,
            cache_epoch=cache_epoch,
        )
        if not options:
            return None
        best_delta, best_action = options[0]
        k = min(regret_k, len(options))
        regret_score = sum(options[i][0] - best_delta for i in range(1, k)) if k > 1 else 1e9
        choice_key   = (-regret_score, best_delta, customer)
        return choice_key, (customer, best_action, best_delta, regret_score)

    if use_parallel:
        workers = min(
            int(ALGO_CONFIG["regret_parallel_max_workers"]),
            max(1, len(prioritized)),
        )
        executor = get_shared_local_search_executor(workers)
        scored = [future.result() for future in [executor.submit(score_customer, customer) for customer in prioritized]]
    else:
        scored = [score_customer(customer) for customer in prioritized]

    for scored_customer in scored:
        if scored_customer is None:
            continue
        if best_customer_choice is None or scored_customer[0] < best_customer_choice[0]:
            best_customer_choice = scored_customer
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

    insertion_count = 0
    cache_epoch = 0
    cache_refresh_every = max(1, int(ALGO_CONFIG["insertion_cache_refresh_every"]))
    candidate_route_cache: Dict[Tuple[int, int, int], List[int]] = {}

    while pending_customers:
        if insertion_count > 0 and insertion_count % cache_refresh_every == 0:
            cache_epoch += 1
            candidate_route_cache.clear()
        rc = choose_regret_customer_insertion(
            problem, routes, vehicle_ids, type_usage,
            pending_customers, regret_k=sample_regret_k(),
            current_route_costs=current_route_costs,
            current_route_loads=current_route_loads,
            allow_new_route=allow_new_route,
            route_centroids=route_centroids,
            route_arrays=route_arrays,
            candidate_route_cache=candidate_route_cache,
            cache_epoch=cache_epoch,
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
            cache_epoch += 1
            candidate_route_cache.clear()

        pending_customers.remove(customer)
        insertion_count += 1
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
    farthest_seeds = farthest_customer_seeds(problem, customers, target_route_count)

    def run_attempt(attempt_idx: int, ordering: List[int]) -> Optional[Tuple[Route_matrix, List[int], float]]:
        if attempt_idx == 0:
            seeds = farthest_seeds[:]
        else:
            head = ordering[:target_route_count]
            seeds = list(dict.fromkeys(head))
            if len(seeds) < target_route_count:
                for customer in farthest_seeds:
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
    use_parallel = (
        len(attempt_items) >= int(ALGO_CONFIG["pool_rebuild_parallel_min_attempts"])
        and len(customers) >= int(ALGO_CONFIG["pool_rebuild_parallel_min_customers"])
    )
    parallel_workers = min(4, len(attempt_items)) if use_parallel else 1
    if parallel_workers > 1:
        executor = get_shared_rebuild_executor(parallel_workers)
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


def has_severe_route_pathology(problem: HCVRPProblem, state: "SolutionState") -> bool:
    active = [idx for idx, route in enumerate(state.routes) if route_core(route)]
    if not active:
        return False
    badness = [route_badness_score(problem, state, idx) for idx in active]
    mean_bad = sum(badness) / len(badness)
    variance = sum((score - mean_bad) ** 2 for score in badness) / len(badness)
    severe_limit = mean_bad + float(ALGO_CONFIG["targeted_cleanup_early_severe_sigma"]) * math.sqrt(variance)
    return max(badness) > severe_limit


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


def candidate_is_progress(
        problem: HCVRPProblem,
        base_state: "SolutionState",
        candidate: "SolutionState",
        allow_structural_progress: bool = False,
        plateau_level: int = 0,
) -> bool:
    if not candidate.feasible:
        return False
    if plateau_level > 0:
        base_pressured = pressured_total_cost(problem, base_state, plateau_level)
        candidate_pressured = pressured_total_cost(problem, candidate, plateau_level)
        if candidate_pressured + 1e-9 < base_pressured:
            return True
        if (abs(candidate_pressured - base_pressured) <= 1e-9
                and route_count(candidate) < route_count(base_state)):
            return True
    if candidate.total_cost < base_state.total_cost:
        return True
    return allow_structural_progress and cleanup_candidate_is_better(problem, base_state, candidate)


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


def complete_pack_trail(
        problem: HCVRPProblem,
        pooled_customers: List[int],
        partial_trail: List[int],
) -> List[int]:
    pooled_set = set(pooled_customers)
    trail: List[int] = []
    seen: Set[int] = set()
    for customer in partial_trail:
        if customer in pooled_set and customer not in seen:
            trail.append(customer)
            seen.add(customer)

    remaining = [customer for customer in pooled_customers if customer not in seen]
    if not remaining:
        return trail

    if not trail:
        start = max(
            remaining,
            key=lambda customer: (problem.dist[0][customer], problem.demands[customer], customer),
        )
        trail.append(start)
        seen.add(start)
        remaining.remove(start)

    while remaining:
        anchor = trail[-1]
        next_customer = min(
            remaining,
            key=lambda customer: (problem.dist[anchor][customer], problem.dist[0][customer], customer),
        )
        trail.append(next_customer)
        seen.add(next_customer)
        remaining.remove(next_customer)
    return trail


def build_pack_trail_orderings(
        problem: HCVRPProblem,
        state: "SolutionState",
        pooled_customers: List[int],
        selected_routes: List[int],
        pack_states: Optional[List["SolutionState"]] = None,
        attempts: int = 5,
) -> List[List[int]]:
    if not pooled_customers:
        return []

    pooled_set = set(pooled_customers)
    trails: List[List[int]] = []

    current_trail: List[int] = []
    for r_idx in selected_routes:
        current_trail.extend(route_core(state.routes[r_idx]))
    trails.append(complete_pack_trail(problem, pooled_customers, current_trail))

    cx = sum(problem.coords[customer][0] for customer in pooled_customers) / len(pooled_customers)
    cy = sum(problem.coords[customer][1] for customer in pooled_customers) / len(pooled_customers)
    sweep_trail = sorted(
        pooled_customers,
        key=lambda customer: (
            math.atan2(problem.coords[customer][1] - cy, problem.coords[customer][0] - cx),
            problem.dist[0][customer],
            customer,
        ),
    )
    trails.append(sweep_trail)
    trails.append(list(reversed(sweep_trail)))

    radial_trail = sorted(
        pooled_customers,
        key=lambda customer: (-problem.dist[0][customer], -problem.demands[customer], customer),
    )
    trails.append(complete_pack_trail(problem, pooled_customers, radial_trail))

    for pack_state in (pack_states or [])[:6]:
        if pack_state is None or not pack_state.hard_feasible:
            continue
        fragment_trail: List[int] = []
        ranked_routes = sorted(
            pack_state.routes,
            key=lambda route: -len(pooled_set & set(route_core(route))),
        )
        for route in ranked_routes:
            overlap = [customer for customer in route_core(route) if customer in pooled_set]
            if overlap:
                fragment_trail.extend(overlap)
        if fragment_trail:
            trails.append(complete_pack_trail(problem, pooled_customers, fragment_trail))

    unique_trails: List[List[int]] = []
    seen_keys: Set[Tuple[int, ...]] = set()
    for trail in trails:
        if len(trail) != len(pooled_customers):
            trail = complete_pack_trail(problem, pooled_customers, trail)
        key = tuple(trail)
        if len(key) == len(pooled_customers) and key not in seen_keys:
            seen_keys.add(key)
            unique_trails.append(trail)

    while len(unique_trails) < max(2, attempts):
        shuffled = pooled_customers[:]
        random.shuffle(shuffled)
        trail = complete_pack_trail(problem, pooled_customers, shuffled)
        key = tuple(trail)
        if key in seen_keys:
            break
        seen_keys.add(key)
        unique_trails.append(trail)
    return unique_trails[:max(2, attempts)]


def split_pack_trail_into_routes(
        problem: HCVRPProblem,
        giant_tour: List[int],
        target_route_count: int,
        max_extra_routes: int = 2,
) -> Optional[Tuple[Route_matrix, List[int]]]:
    if not giant_tour:
        return [], []

    n = len(giant_tour)
    max_routes = max(1, target_route_count + max_extra_routes)
    inf = float("inf")
    segment_cost = [[inf] * n for _ in range(n)]
    segment_route: List[List[Optional[Route]]] = [[None] * n for _ in range(n)]
    load_prefix = [0.0]
    for customer in giant_tour:
        load_prefix.append(load_prefix[-1] + problem.demands[customer])

    for start in range(n):
        for end in range(start, n):
            segment_load = load_prefix[end + 1] - load_prefix[start]
            if segment_load > problem.max_vehicle_capacity:
                break
            route = [0] + giant_tour[start:end + 1] + [0]
            best_cost = inf
            best_route: Optional[Route] = None
            for vehicle_type in problem.vehicle_types:
                if vehicle_type.capacity < segment_load:
                    continue
                route_ok, _, _, _, route_cost = evaluate_route_for_vehicle(problem, route, vehicle_type)
                if route_ok and route_cost < best_cost:
                    best_cost = route_cost
                    best_route = route
            if best_route is not None:
                segment_cost[start][end] = best_cost
                segment_route[start][end] = best_route

    dp = [[inf] * (n + 1) for _ in range(max_routes + 1)]
    prev = [[-1] * (n + 1) for _ in range(max_routes + 1)]
    dp[0][0] = 0.0

    for route_count_used in range(1, max_routes + 1):
        for end in range(1, n + 1):
            best_val = inf
            best_start = -1
            for start in range(end - 1, -1, -1):
                seg_cost = segment_cost[start][end - 1]
                if seg_cost == inf or dp[route_count_used - 1][start] == inf:
                    continue
                candidate_val = dp[route_count_used - 1][start] + seg_cost
                if candidate_val < best_val:
                    best_val = candidate_val
                    best_start = start
            dp[route_count_used][end] = best_val
            prev[route_count_used][end] = best_start

    preferred_route_counts = [
        route_count_used
        for route_count_used in range(max(1, target_route_count - 1), min(max_routes, target_route_count + 2) + 1)
        if dp[route_count_used][n] < inf
    ]
    if not preferred_route_counts:
        preferred_route_counts = [
            route_count_used for route_count_used in range(1, max_routes + 1)
            if dp[route_count_used][n] < inf
        ]
    if not preferred_route_counts:
        return None

    best_route_count = min(
        preferred_route_counts,
        key=lambda route_count_used: (dp[route_count_used][n], abs(route_count_used - target_route_count), route_count_used),
    )

    rebuilt_routes: Route_matrix = []
    cursor = n
    route_count_used = best_route_count
    while route_count_used > 0 and cursor > 0:
        start = prev[route_count_used][cursor]
        if start < 0:
            return None
        rebuilt_route = segment_route[start][cursor - 1]
        if rebuilt_route is None:
            return None
        rebuilt_routes.append(normalize_route(rebuilt_route))
        cursor = start
        route_count_used -= 1
    rebuilt_routes.reverse()

    ordered_indices = sorted(
        range(len(rebuilt_routes)),
        key=lambda idx: (-problem.route_load(rebuilt_routes[idx]), -len(route_core(rebuilt_routes[idx])), idx),
    )
    rebuilt_vehicle_ids = [-1] * len(rebuilt_routes)
    type_usage: Dict[int, int] = {}
    for idx in ordered_indices:
        vehicle_id = assign_best_feasible_vehicle_for_tour(problem, rebuilt_routes[idx], type_usage)
        if vehicle_id is None:
            return None
        rebuilt_vehicle_ids[idx] = vehicle_id
        type_usage[vehicle_id] = type_usage.get(vehicle_id, 0) + 1

    return rebuilt_routes, rebuilt_vehicle_ids


def reconstruct_exact_route_for_mask(
        customers: List[int],
        parent: List[List[int]],
        best_end: List[int],
        mask: int,
) -> Optional[Route]:
    end_idx = best_end[mask]
    if end_idx < 0:
        return None
    sequence: List[int] = []
    current_mask = mask
    current_end = end_idx
    while current_mask:
        sequence.append(customers[current_end])
        prev_end = parent[current_mask][current_end]
        current_mask ^= (1 << current_end)
        current_end = prev_end
    sequence.reverse()
    return [0] + sequence + [0]


def solve_small_exact_customer_pool(
        problem: HCVRPProblem,
        customers: List[int],
        target_route_count: int,
        seed_type_usage: Optional[Dict[int, int]] = None,
        max_extra_routes: Optional[int] = None,
) -> Optional[Tuple[Route_matrix, List[int]]]:
    unique_customers = list(dict.fromkeys(customers))
    n = len(unique_customers)
    if n == 0:
        return [], []
    if n > int(ALGO_CONFIG["exact_pool_customer_cap"]):
        return None
    if getattr(problem, "_has_tight_time_windows", False) or getattr(problem, "max_route_time_min", None) is not None:
        return None

    if max_extra_routes is None:
        max_extra_routes = int(ALGO_CONFIG["exact_pool_route_slack"])

    max_capacity = float(problem.max_vehicle_capacity)
    full_mask = (1 << n) - 1
    inf = float("inf")

    subset_load = [0.0] * (full_mask + 1)
    for mask in range(1, full_mask + 1):
        lsb = mask & -mask
        idx = lsb.bit_length() - 1
        subset_load[mask] = subset_load[mask ^ lsb] + problem.demands[unique_customers[idx]]

    dp = [[inf] * n for _ in range(full_mask + 1)]
    parent = [[-1] * n for _ in range(full_mask + 1)]
    for end_idx, customer in enumerate(unique_customers):
        mask = 1 << end_idx
        dp[mask][end_idx] = problem.dist[0][customer]

    for mask in range(1, full_mask + 1):
        for end_idx in range(n):
            if not (mask & (1 << end_idx)):
                continue
            prev_mask = mask ^ (1 << end_idx)
            if prev_mask == 0:
                continue
            best_val = dp[mask][end_idx]
            best_prev = parent[mask][end_idx]
            end_customer = unique_customers[end_idx]
            for prev_idx in range(n):
                if not (prev_mask & (1 << prev_idx)):
                    continue
                prev_val = dp[prev_mask][prev_idx]
                if prev_val == inf:
                    continue
                candidate_val = prev_val + problem.dist[unique_customers[prev_idx]][end_customer]
                if candidate_val < best_val:
                    best_val = candidate_val
                    best_prev = prev_idx
            dp[mask][end_idx] = best_val
            parent[mask][end_idx] = best_prev

    route_cost = [inf] * (full_mask + 1)
    best_end = [-1] * (full_mask + 1)
    exact_routes: Dict[int, Route] = {}
    for mask in range(1, full_mask + 1):
        if subset_load[mask] > max_capacity:
            continue
        best_cycle = inf
        best_cycle_end = -1
        for end_idx in range(n):
            if not (mask & (1 << end_idx)):
                continue
            path_cost = dp[mask][end_idx]
            if path_cost == inf:
                continue
            total_cost = path_cost + problem.dist[unique_customers[end_idx]][0]
            if total_cost < best_cycle:
                best_cycle = total_cost
                best_cycle_end = end_idx
        if best_cycle_end < 0:
            continue
        best_end[mask] = best_cycle_end
        route = reconstruct_exact_route_for_mask(unique_customers, parent, best_end, mask)
        if route is None:
            continue
        best_vehicle_cost = inf
        for vehicle_type in problem.vehicle_types:
            if vehicle_type.capacity < subset_load[mask]:
                continue
            route_ok, _, _, _, candidate_cost = evaluate_route_for_vehicle(problem, route, vehicle_type)
            if route_ok and candidate_cost < best_vehicle_cost:
                best_vehicle_cost = candidate_cost
        if best_vehicle_cost < inf:
            route_cost[mask] = best_vehicle_cost
            exact_routes[mask] = route

    min_routes_needed = max(1, math.ceil(sum(problem.demands[c] for c in unique_customers) / max_capacity))
    max_routes = min(n, max(min_routes_needed, target_route_count + max(0, max_extra_routes)))
    min_target_routes = max(min_routes_needed, max(1, target_route_count - 1))
    dp_part = [[inf] * (full_mask + 1) for _ in range(max_routes + 1)]
    part_choice = [[0] * (full_mask + 1) for _ in range(max_routes + 1)]
    dp_part[0][0] = 0.0

    for route_count_used in range(1, max_routes + 1):
        for mask in range(1, full_mask + 1):
            submask = mask
            best_val = inf
            best_submask = 0
            while submask:
                rc = route_cost[submask]
                if rc < inf and dp_part[route_count_used - 1][mask ^ submask] < inf:
                    candidate_val = dp_part[route_count_used - 1][mask ^ submask] + rc
                    if candidate_val < best_val:
                        best_val = candidate_val
                        best_submask = submask
                submask = (submask - 1) & mask
            dp_part[route_count_used][mask] = best_val
            part_choice[route_count_used][mask] = best_submask

    candidate_route_counts = [
        route_count_used for route_count_used in range(min_target_routes, max_routes + 1)
        if dp_part[route_count_used][full_mask] < inf
    ]
    if not candidate_route_counts:
        return None

    best_route_count = min(
        candidate_route_counts,
        key=lambda route_count_used: (
            dp_part[route_count_used][full_mask],
            abs(route_count_used - target_route_count),
            route_count_used,
        ),
    )

    chosen_masks: List[int] = []
    mask = full_mask
    route_count_used = best_route_count
    while mask and route_count_used > 0:
        submask = part_choice[route_count_used][mask]
        if submask == 0:
            return None
        chosen_masks.append(submask)
        mask ^= submask
        route_count_used -= 1
    if mask != 0:
        return None

    rebuilt_routes = [exact_routes[submask] for submask in reversed(chosen_masks)]
    rebuilt_vehicle_ids: List[int] = []
    type_usage = dict(seed_type_usage or {})
    ordered_indices = sorted(
        range(len(rebuilt_routes)),
        key=lambda idx: (-problem.route_load(rebuilt_routes[idx]), -len(route_core(rebuilt_routes[idx])), idx),
    )
    rebuilt_vehicle_ids = [-1] * len(rebuilt_routes)
    for idx in ordered_indices:
        vehicle_id = assign_best_feasible_vehicle_for_tour(problem, rebuilt_routes[idx], type_usage)
        if vehicle_id is None:
            return None
        rebuilt_vehicle_ids[idx] = vehicle_id
        type_usage[vehicle_id] = type_usage.get(vehicle_id, 0) + 1
    return rebuilt_routes, rebuilt_vehicle_ids


def exact_tsp_route_for_vehicle(
        problem: HCVRPProblem,
        customers: List[int],
        vehicle_type_id: int,
) -> Optional[Tuple[Route, float, float, float, float]]:
    unique_customers = list(dict.fromkeys(customers))
    n = len(unique_customers)
    if n == 0:
        return [0, 0], 0.0, 0.0, 0.0, 0.0
    if n > int(ALGO_CONFIG["exact_route_polish_customer_cap"]):
        return None
    if getattr(problem, "_has_tight_time_windows", False) or getattr(problem, "max_route_time_min", None) is not None:
        return None
    if vehicle_type_id < 0 or vehicle_type_id >= len(problem.vehicle_types):
        return None

    cache_key = (id(problem), vehicle_type_id, tuple(sorted(unique_customers)))
    if cache_key in _EXACT_ROUTE_TSP_CACHE:
        cached = _EXACT_ROUTE_TSP_CACHE[cache_key]
        if cached is None:
            return None
        route, load, dist, route_time, route_cost = cached
        return route[:], load, dist, route_time, route_cost

    vt = get_vehicle_type_by_id(problem, vehicle_type_id)
    if sum(problem.demands[c] for c in unique_customers) > vt.capacity + 1e-9:
        _EXACT_ROUTE_TSP_CACHE[cache_key] = None
        return None
    if n <= 2:
        best_eval: Optional[Tuple[Route, float, float, float, float]] = None
        orders = [unique_customers, list(reversed(unique_customers))] if n == 2 else [unique_customers]
        for order in orders:
            route = [0] + order + [0]
            route_ok, load, dist, route_time, route_cost = evaluate_route_for_vehicle(problem, route, vt)
            if route_ok and (best_eval is None or route_cost < best_eval[4]):
                best_eval = (route, load, dist, route_time, route_cost)
        _EXACT_ROUTE_TSP_CACHE[cache_key] = None if best_eval is None else (best_eval[0][:], *best_eval[1:])
        return best_eval

    full_mask = (1 << n) - 1
    inf = float("inf")
    dp = [[inf] * n for _ in range(full_mask + 1)]
    parent = [[-1] * n for _ in range(full_mask + 1)]
    for end_idx, customer in enumerate(unique_customers):
        dp[1 << end_idx][end_idx] = problem.dist[0][customer]

    for mask in range(1, full_mask + 1):
        for end_idx in range(n):
            if not (mask & (1 << end_idx)):
                continue
            prev_mask = mask ^ (1 << end_idx)
            if prev_mask == 0:
                continue
            best_val = dp[mask][end_idx]
            best_prev = parent[mask][end_idx]
            end_customer = unique_customers[end_idx]
            for prev_idx in range(n):
                if not (prev_mask & (1 << prev_idx)):
                    continue
                candidate_val = dp[prev_mask][prev_idx] + problem.dist[unique_customers[prev_idx]][end_customer]
                if candidate_val < best_val:
                    best_val = candidate_val
                    best_prev = prev_idx
            dp[mask][end_idx] = best_val
            parent[mask][end_idx] = best_prev

    best_total = inf
    best_end = -1
    for end_idx, customer in enumerate(unique_customers):
        candidate_total = dp[full_mask][end_idx] + problem.dist[customer][0]
        if candidate_total < best_total:
            best_total = candidate_total
            best_end = end_idx
    if best_end < 0:
        _EXACT_ROUTE_TSP_CACHE[cache_key] = None
        return None

    sequence: List[int] = []
    mask = full_mask
    current_end = best_end
    while mask:
        sequence.append(unique_customers[current_end])
        prev_end = parent[mask][current_end]
        mask ^= (1 << current_end)
        current_end = prev_end
    sequence.reverse()
    route = [0] + sequence + [0]
    route_ok, load, dist, route_time, route_cost = evaluate_route_for_vehicle(problem, route, vt)
    if not route_ok:
        _EXACT_ROUTE_TSP_CACHE[cache_key] = None
        return None
    result = (route, load, dist, route_time, route_cost)
    _EXACT_ROUTE_TSP_CACHE[cache_key] = (route[:], load, dist, route_time, route_cost)
    return result


def exact_route_polish_solution(
        problem: HCVRPProblem,
        state: "SolutionState",
) -> "SolutionState":
    if not bool(ALGO_CONFIG.get("exact_route_polish_enabled", True)):
        return clone_solution_state(state)
    max_customers = int(ALGO_CONFIG["exact_route_polish_customer_cap"])
    max_routes = int(ALGO_CONFIG["exact_route_polish_max_routes"])
    min_gain = float(ALGO_CONFIG["exact_route_polish_min_gain"])
    route_candidates = [
        (state.route_costs[idx], idx)
        for idx, route in enumerate(state.routes)
        if 2 <= len(route_core(route)) <= max_customers
    ]
    if not route_candidates:
        return clone_solution_state(state)
    route_candidates.sort(key=lambda item: (-item[0], item[1]))

    updates: List[Tuple[int, Route, float, float, float, float]] = []
    for _, route_idx in route_candidates[:max_routes]:
        exact_eval = exact_tsp_route_for_vehicle(
            problem,
            route_core(state.routes[route_idx]),
            state.vehicle_ids[route_idx],
        )
        if exact_eval is None:
            continue
        route, load, dist, route_time, route_cost = exact_eval
        if route_cost + min_gain < state.route_costs[route_idx]:
            updates.append((route_idx, route, load, dist, route_time, route_cost))

    if not updates:
        return clone_solution_state(state)
    candidate = clone_state_with_updated_routes(state, updates)
    if candidate.total_cost + min_gain < state.total_cost:
        return candidate
    return clone_solution_state(state)


def solve_exact_two_route_customer_pool(
        problem: HCVRPProblem,
        customers: List[int],
        seed_type_usage: Optional[Dict[int, int]] = None,
        customer_cap: Optional[int] = None,
) -> Optional[Tuple[Route_matrix, List[int]]]:
    unique_customers = list(dict.fromkeys(customers))
    n = len(unique_customers)
    if n < 2:
        return None
    if customer_cap is None:
        customer_cap = int(ALGO_CONFIG["exact_2route_customer_cap"])
    if n > customer_cap:
        return None
    if getattr(problem, "_has_tight_time_windows", False) or getattr(problem, "max_route_time_min", None) is not None:
        return None

    full_mask = (1 << n) - 1
    inf = float("inf")
    max_capacity = float(problem.max_vehicle_capacity)
    subset_load = [0.0] * (full_mask + 1)
    for mask in range(1, full_mask + 1):
        lsb = mask & -mask
        idx = lsb.bit_length() - 1
        subset_load[mask] = subset_load[mask ^ lsb] + problem.demands[unique_customers[idx]]

    dp = [[inf] * n for _ in range(full_mask + 1)]
    parent = [[-1] * n for _ in range(full_mask + 1)]
    for end_idx, customer in enumerate(unique_customers):
        dp[1 << end_idx][end_idx] = problem.dist[0][customer]

    for mask in range(1, full_mask + 1):
        for end_idx in range(n):
            if not (mask & (1 << end_idx)):
                continue
            prev_mask = mask ^ (1 << end_idx)
            if prev_mask == 0:
                continue
            best_val = dp[mask][end_idx]
            best_prev = parent[mask][end_idx]
            end_customer = unique_customers[end_idx]
            for prev_idx in range(n):
                if not (prev_mask & (1 << prev_idx)):
                    continue
                prev_val = dp[prev_mask][prev_idx]
                if prev_val == inf:
                    continue
                candidate_val = prev_val + problem.dist[unique_customers[prev_idx]][end_customer]
                if candidate_val < best_val:
                    best_val = candidate_val
                    best_prev = prev_idx
            dp[mask][end_idx] = best_val
            parent[mask][end_idx] = best_prev

    route_cost = [inf] * (full_mask + 1)
    best_end = [-1] * (full_mask + 1)
    exact_routes: Dict[int, Route] = {}
    for mask in range(1, full_mask + 1):
        if subset_load[mask] > max_capacity:
            continue
        best_cycle = inf
        best_cycle_end = -1
        for end_idx in range(n):
            if not (mask & (1 << end_idx)):
                continue
            candidate_cost = dp[mask][end_idx] + problem.dist[unique_customers[end_idx]][0]
            if candidate_cost < best_cycle:
                best_cycle = candidate_cost
                best_cycle_end = end_idx
        if best_cycle_end < 0:
            continue
        best_end[mask] = best_cycle_end
        route = reconstruct_exact_route_for_mask(unique_customers, parent, best_end, mask)
        if route is None:
            continue
        best_vehicle_cost = inf
        for vehicle_type in problem.vehicle_types:
            if vehicle_type.capacity < subset_load[mask]:
                continue
            route_ok, _, _, _, candidate_route_cost = evaluate_route_for_vehicle(problem, route, vehicle_type)
            if route_ok and candidate_route_cost < best_vehicle_cost:
                best_vehicle_cost = candidate_route_cost
        if best_vehicle_cost < inf:
            route_cost[mask] = best_vehicle_cost
            exact_routes[mask] = route

    best_partition_cost = inf
    best_pair: Optional[Tuple[int, int]] = None
    for submask in range(1, full_mask):
        if not (submask & 1):
            continue
        other = full_mask ^ submask
        if other == 0:
            continue
        candidate_cost = route_cost[submask] + route_cost[other]
        if candidate_cost < best_partition_cost:
            best_partition_cost = candidate_cost
            best_pair = (submask, other)
    if best_pair is None:
        return None

    rebuilt_routes = [exact_routes[best_pair[0]], exact_routes[best_pair[1]]]
    type_usage = dict(seed_type_usage or {})
    rebuilt_vehicle_ids = [-1, -1]
    ordered_indices = sorted(
        range(2),
        key=lambda idx: (-problem.route_load(rebuilt_routes[idx]), -len(route_core(rebuilt_routes[idx])), idx),
    )
    for idx in ordered_indices:
        vehicle_id = assign_best_feasible_vehicle_for_tour(problem, rebuilt_routes[idx], type_usage)
        if vehicle_id is None:
            return None
        rebuilt_vehicle_ids[idx] = vehicle_id
        type_usage[vehicle_id] = type_usage.get(vehicle_id, 0) + 1
    return rebuilt_routes, rebuilt_vehicle_ids


def exact_two_route_repartition_phase(
        problem: HCVRPProblem,
        state: "SolutionState",
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
    if not bool(ALGO_CONFIG.get("exact_2route_repartition_enabled", True)):
        return clone_solution_state(state)
    active = [idx for idx, route in enumerate(state.routes) if route_core(route)]
    if len(active) < 2:
        return clone_solution_state(state)

    badness_values = [(route_badness_score(problem, state, idx), idx) for idx in active]
    badness_scores = [score for score, _ in badness_values]
    mean_bad = sum(badness_scores) / max(1, len(badness_scores))
    variance = sum((score - mean_bad) ** 2 for score in badness_scores) / max(1, len(badness_scores))
    badness_limit = mean_bad + float(ALGO_CONFIG["exact_2route_badness_sigma"]) * math.sqrt(variance)
    ranked_targets = sorted(badness_values, key=lambda item: (-item[0], item[1]))
    if not (pulse_mode or plateau_level > 0 or ranked_targets[0][0] > badness_limit):
        return clone_solution_state(state)

    centroids = _state_route_centroids(problem, state)
    max_pairs = int(ALGO_CONFIG["exact_2route_max_pairs"])
    customer_cap = int(ALGO_CONFIG["exact_2route_customer_cap"])
    min_gain = float(ALGO_CONFIG["exact_2route_min_gain"])
    best_candidate: Optional["SolutionState"] = None
    for _, target_idx in ranked_targets[:max(1, max_pairs)]:
        target_centroid = centroids[target_idx]
        neighbors = []
        target_set = _state_route_core_set(state, target_idx)
        for other_idx in active:
            if other_idx == target_idx:
                continue
            other_set = _state_route_core_set(state, other_idx)
            dx = target_centroid[0] - centroids[other_idx][0]
            dy = target_centroid[1] - centroids[other_idx][1]
            neighbors.append((
                -len(target_set & other_set),
                dx * dx + dy * dy,
                other_idx,
            ))
        if not neighbors:
            continue
        neighbors.sort(key=lambda item: (item[0], item[1], item[2]))
        other_idx = neighbors[0][2]
        pooled_customers = route_core(state.routes[target_idx]) + route_core(state.routes[other_idx])
        if len(pooled_customers) > customer_cap:
            continue

        kept_routes: Route_matrix = []
        kept_vehicle_ids: List[int] = []
        selected = {target_idx, other_idx}
        for idx, (route, vehicle_id) in enumerate(zip(state.routes, state.vehicle_ids)):
            if idx in selected:
                continue
            kept_routes.append(normalize_route(route))
            kept_vehicle_ids.append(vehicle_id)
        rebuilt = solve_exact_two_route_customer_pool(
            problem,
            pooled_customers,
            seed_type_usage=_type_usage_from_ids(kept_vehicle_ids),
            customer_cap=customer_cap,
        )
        if rebuilt is None:
            continue
        rebuilt_routes, rebuilt_vehicle_ids = rebuilt
        candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
        if not candidate.feasible or candidate.total_cost + min_gain >= state.total_cost:
            continue
        if best_candidate is None or candidate.total_cost < best_candidate.total_cost:
            best_candidate = candidate

    if best_candidate is not None:
        return best_candidate
    return clone_solution_state(state)


def hunt_end_exact_polish(
        problem: HCVRPProblem,
        state: "SolutionState",
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
    current = exact_route_polish_solution(problem, state)
    candidate = exact_two_route_repartition_phase(
        problem,
        current,
        pulse_mode=pulse_mode,
        plateau_level=plateau_level,
    )
    if candidate.total_cost < current.total_cost:
        current = exact_route_polish_solution(problem, candidate)
    return current


def decode_customer_pool_with_split(
        problem: HCVRPProblem,
        customers: List[int],
        target_route_count: int,
        seed_routes: Optional[Route_matrix] = None,
        guide_states: Optional[List["SolutionState"]] = None,
        attempts: int = 4,
        max_extra_routes: int = 2,
        seed_type_usage: Optional[Dict[int, int]] = None,
        seed_orderings: Optional[List[List[int]]] = None,
) -> Optional[Tuple[Route_matrix, List[int]]]:
    unique_customers = list(dict.fromkeys(customers))
    if not unique_customers:
        return [], []

    exact_decoded = solve_small_exact_customer_pool(
        problem,
        unique_customers,
        target_route_count,
        seed_type_usage=seed_type_usage,
        max_extra_routes=max_extra_routes,
    )
    if exact_decoded is not None:
        return exact_decoded

    customer_set = set(unique_customers)
    orderings = build_customer_pool_orderings(problem, unique_customers, attempts=max(2, attempts))
    ordering_candidates: List[List[int]] = []

    for ordering in (seed_orderings or []):
        if ordering:
            ordering_candidates.append(complete_pack_trail(problem, unique_customers, ordering))

    if seed_routes:
        seed_order = [customer for route in seed_routes for customer in route_core(route) if customer in customer_set]
        if seed_order:
            ordering_candidates.append(complete_pack_trail(problem, unique_customers, seed_order))

    for guide_state in (guide_states or [])[:6]:
        if guide_state is None or not guide_state.hard_feasible:
            continue
        guide_order = []
        ranked_routes = sorted(
            guide_state.routes,
            key=lambda route: -len(customer_set & set(route_core(route))),
        )
        for route in ranked_routes:
            overlap = [customer for customer in route_core(route) if customer in customer_set]
            if overlap:
                guide_order.extend(overlap)
        if guide_order:
            ordering_candidates.append(complete_pack_trail(problem, unique_customers, guide_order))

    for ordering in orderings:
        ordering_candidates.append(complete_pack_trail(problem, unique_customers, ordering))

    best_decoded: Optional[Tuple[Route_matrix, List[int], float]] = None
    seen: Set[Tuple[int, ...]] = set()
    for giant_tour in ordering_candidates[:max(3, attempts + 2)]:
        key = tuple(giant_tour)
        if key in seen:
            continue
        seen.add(key)
        rebuilt = split_pack_trail_into_routes(
            problem,
            giant_tour,
            target_route_count=target_route_count,
            max_extra_routes=max_extra_routes,
        )
        if rebuilt is None:
            continue
        rebuilt_routes, rebuilt_vehicle_ids = rebuilt
        candidate = evaluate_solution(problem, rebuilt_routes, rebuilt_vehicle_ids)
        if not candidate.feasible:
            continue
        if best_decoded is None or candidate.total_cost < best_decoded[2]:
            best_decoded = (rebuilt_routes, rebuilt_vehicle_ids, candidate.total_cost)

    if best_decoded is not None:
        return best_decoded[0], best_decoded[1]
    return rebuild_customer_pool_into_routes(
        problem,
        unique_customers,
        target_route_count,
        attempts=max(2, attempts),
    )


def full_moon_phase(
        problem: HCVRPProblem, state: "SolutionState",
        pack_states: Optional[List["SolutionState"]] = None,
        max_bad_routes: int = 2, neighbor_routes: int = 2,
        max_routes_to_rebuild: int = 4, attempts: int = 5,
        post_ls_rounds: int = 1, pulse_mode: bool = False,
        plateau_level: int = 0,
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

    best_candidate: Optional["SolutionState"] = None
    pack_trails = build_pack_trail_orderings(
        problem,
        state,
        pooled_customers,
        selected,
        pack_states=pack_states,
        attempts=max(3, attempts),
    )
    pack_pool_states = [state] + [pack_state for pack_state in (pack_states or []) if pack_state is not None]
    direct_rebuild = decode_customer_pool_with_split(
        problem,
        pooled_customers,
        target_route_count=len(selected),
        seed_routes=[state.routes[idx] for idx in selected],
        guide_states=pack_pool_states,
        attempts=max(3, attempts),
        max_extra_routes=3 if pulse_mode else 2,
        seed_type_usage=_type_usage_from_ids(kept_vehicle_ids),
    )

    if direct_rebuild is not None:
        rebuilt_routes, rebuilt_vehicle_ids = direct_rebuild
        candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
        if candidate.feasible:
            candidate = maybe_targeted_cleanup(
                problem,
                candidate,
                pulse_mode=pulse_mode,
                plateau_level=plateau_level,
            )
            if candidate_is_progress(problem, state, candidate, allow_structural_progress=True):
                best_candidate = candidate

    for giant_tour in pack_trails:
        rebuilt = split_pack_trail_into_routes(
            problem,
            giant_tour,
            target_route_count=len(selected),
            max_extra_routes=3 if pulse_mode else 2,
        )
        if rebuilt is None:
            continue

        rebuilt_routes, rebuilt_vehicle_ids = rebuilt
        candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
        if not candidate.feasible:
            continue

        candidate = route_pool_set_partition_phase(
            problem,
            candidate,
            pool_states=pack_pool_states,
            target_route_count=route_count(candidate),
            attempts=max(2, min(attempts, int(ALGO_CONFIG["route_pool_attempts"]))),
            plateau_level=plateau_level,
        )
        if post_ls_rounds > 0:
            candidate = intensify_local_search(
                problem,
                candidate,
                max_rounds=post_ls_rounds,
                pulse_mode=pulse_mode,
                plateau_level=plateau_level,
            )
        candidate = maybe_targeted_cleanup(
            problem,
            candidate,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )

        if not candidate_is_progress(problem, state, candidate, allow_structural_progress=True, plateau_level=plateau_level):
            continue
        if (best_candidate is None
                or pressured_total_cost(problem, candidate, plateau_level) < pressured_total_cost(problem, best_candidate, plateau_level)
                or cleanup_candidate_is_better(problem, best_candidate, candidate)):
            best_candidate = candidate

    if best_candidate is not None and candidate_is_progress(
            problem, state, best_candidate,
            allow_structural_progress=True,
            plateau_level=plateau_level):
        return best_candidate
    return clone_solution_state(state)


def maybe_targeted_cleanup(
        problem: HCVRPProblem,
        state: "SolutionState",
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
    if not _state_has_route_pathology(problem, state):
        return state
    threshold = float(ALGO_CONFIG["pulse_cleanup_prob"] if pulse_mode else ALGO_CONFIG["targeted_cleanup_prob"])
    threshold = min(1.0, threshold + plateau_level * float(ALGO_CONFIG["plateau_cleanup_prob_bonus"]))
    if random.random() >= threshold:
        return state
    return targeted_cleanup_phase(problem, state, pulse_mode=pulse_mode, plateau_level=plateau_level)


def targeted_cleanup_phase(
        problem: HCVRPProblem,
        state: "SolutionState",
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
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

    if candidate_is_progress(
            problem, state, best_state,
            allow_structural_progress=True,
            plateau_level=plateau_level):
        return best_state
    return clone_solution_state(state)


# ==============================================================================
#  PATH RELINK / ALPHA GUIDED REBUILD
# ==============================================================================

def build_route_customer_sets(routes: Route_matrix) -> List[Set[int]]:
    return [set(route_core(r)) for r in routes]


def select_alpha_inherit_route_indices(
        base_state: "SolutionState",
        alpha_state: "SolutionState",
        inherit_frac: float = 0.35,
) -> List[int]:
    alpha_active = [i for i, route in enumerate(alpha_state.routes) if route_core(route)]
    if not alpha_active:
        return []
    target_count = max(1, min(len(alpha_active), int(round(inherit_frac * len(alpha_active))) or 1))
    base_sets = build_route_customer_sets(base_state.routes)
    ranked = []
    for idx in alpha_active:
        alpha_set = set(route_core(alpha_state.routes[idx]))
        if not alpha_set:
            continue
        best_overlap = max((len(alpha_set & base_set) for base_set in base_sets), default=0)
        novelty = len(alpha_set) - best_overlap
        ranked.append((novelty, len(alpha_set), -alpha_state.route_costs[idx], idx))
    ranked.sort(key=lambda x: (-x[0], -x[1], x[2], x[3]))
    return [idx for _, _, _, idx in ranked[:target_count]]

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
        alpha_state: "SolutionState", inherit_frac: float = 0.35,
        plateau_level: int = 0,
) -> "SolutionState":
    selected_alpha_routes = select_alpha_inherit_route_indices(base_state, alpha_state, inherit_frac)
    if not selected_alpha_routes:
        return clone_solution_state(base_state)

    inherited_routes = [normalize_route(alpha_state.routes[idx]) for idx in selected_alpha_routes]
    selected_customers = set(n for route in inherited_routes for n in route if n != 0)
    reduced_routes = remove_customers_from_routes(base_state.routes, selected_customers)

    candidate_routes: Route_matrix = []
    candidate_vehicle_ids: List[int] = []
    type_usage: Dict[int, int] = {}
    for route in reduced_routes + inherited_routes:
        if not route_core(route):
            continue
        v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
        if v_id is None:
            return clone_solution_state(base_state)
        candidate_routes.append(normalize_route(route))
        candidate_vehicle_ids.append(v_id)
        type_usage[v_id] = type_usage.get(v_id, 0) + 1

    candidate = evaluate_solution(problem, candidate_routes, candidate_vehicle_ids)
    candidate = maybe_targeted_cleanup(problem, candidate, plateau_level=plateau_level)
    if candidate_is_progress(problem, base_state, candidate, allow_structural_progress=True, plateau_level=plateau_level):
        return candidate
    return clone_solution_state(base_state)


def merge_and_repartition_phase(
        problem: HCVRPProblem,
        state: "SolutionState",
        guide_state: Optional["SolutionState"] = None,
        inherit_frac: float = 0.35,
        max_routes_to_rebuild: int = 4,
        plateau_level: int = 0,
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if route_core(route)]
    if len(active) < 2:
        return clone_solution_state(state)

    selected: List[int] = []
    if guide_state is not None:
        guide_route_indices = select_alpha_inherit_route_indices(state, guide_state, inherit_frac)
        guide_customers = {
            customer
            for idx in guide_route_indices
            for customer in route_core(guide_state.routes[idx])
        }
        if guide_customers:
            route_map = build_customer_to_route_map(state.routes)
            for customer in guide_customers:
                r_idx = route_map.get(customer)
                if r_idx is not None and r_idx not in selected:
                    selected.append(r_idx)
                if len(selected) >= max_routes_to_rebuild:
                    break

    if not selected:
        ranked = sorted(
            ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
            key=lambda x: (-x[0], x[1])
        )
        selected = [r_idx for _, r_idx in ranked[:max_routes_to_rebuild]]
    elif len(selected) < max_routes_to_rebuild:
        ranked = sorted(
            ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active if r_idx not in selected),
            key=lambda x: (-x[0], x[1])
        )
        for _, r_idx in ranked:
            selected.append(r_idx)
            if len(selected) >= max_routes_to_rebuild:
                break

    if len(selected) < 2:
        return clone_solution_state(state)

    pooled_customers: List[int] = []
    kept_routes: Route_matrix = []
    kept_vehicle_ids: List[int] = []
    selected_set = set(selected[:max_routes_to_rebuild])
    for idx, (route, v_id) in enumerate(zip(state.routes, state.vehicle_ids)):
        if idx in selected_set:
            pooled_customers.extend(route_core(route))
        else:
            kept_routes.append(normalize_route(route))
            kept_vehicle_ids.append(v_id)
    if not pooled_customers:
        return clone_solution_state(state)

    seed_routes = [state.routes[idx] for idx in selected[:max_routes_to_rebuild]]
    guide_states = [guide_state] if guide_state is not None else []
    rebuilt = decode_customer_pool_with_split(
        problem,
        pooled_customers,
        len(selected_set),
        seed_routes=seed_routes,
        guide_states=guide_states,
        attempts=max(3, int(ALGO_CONFIG["full_moon_attempts"])),
        max_extra_routes=2,
        seed_type_usage=_type_usage_from_ids(kept_vehicle_ids),
    )
    if rebuilt is None:
        return clone_solution_state(state)
    rebuilt_routes, rebuilt_vehicle_ids = rebuilt
    candidate = evaluate_solution(problem, kept_routes + rebuilt_routes, kept_vehicle_ids + rebuilt_vehicle_ids)
    if candidate_is_progress(problem, state, candidate, allow_structural_progress=True, plateau_level=plateau_level):
        return candidate
    return clone_solution_state(state)


def build_route_pool_entries(
        states: List["SolutionState"],
        max_entries: Optional[int] = None,
) -> List[Tuple[Route, float]]:
    if max_entries is None:
        max_entries = int(ALGO_CONFIG["route_pool_max_entries"])
    best_by_customer_set: Dict[frozenset[int], Tuple[Route, float]] = {}
    for state in states:
        if state is None or not state.hard_feasible:
            continue
        for route, route_cost in zip(state.routes, state.route_costs):
            core = route_core(route)
            if not core:
                continue
            key = frozenset(core)
            current = best_by_customer_set.get(key)
            normalized = normalize_route(route)
            if current is None or route_cost < current[1]:
                best_by_customer_set[key] = (normalized, route_cost)
    entries = list(best_by_customer_set.values())
    entries.sort(key=lambda item: (item[1] / max(1, len(route_core(item[0]))), item[1], -len(route_core(item[0]))))
    return entries[:max_entries]


def select_pack_crossover_parents(
        problem: HCVRPProblem,
        base_state: "SolutionState",
        guide_state: "SolutionState",
        candidate_states: List["SolutionState"],
        plateau_level: int = 0,
        max_parents: Optional[int] = None,
) -> List["SolutionState"]:
    if max_parents is None:
        max_parents = int(ALGO_CONFIG["pack_crossover_parent_count"])
    pool: List["SolutionState"] = [guide_state, base_state]
    for state in candidate_states:
        if state is None or not state.hard_feasible:
            continue
        pool.append(state)

    unique_pool: List["SolutionState"] = []
    for state in pool:
        if any(state_edge_similarity(state, existing) > 0.995 for existing in unique_pool):
            continue
        unique_pool.append(state)

    ranked = []
    for state in unique_pool:
        novelty = state_novelty_against_pool(state, [base_state, guide_state])
        sim_to_guide = state_edge_similarity(state, guide_state)
        ranked.append((
            pressured_total_cost(problem, state, plateau_level),
            -novelty,
            sim_to_guide,
            state.total_cost,
            state,
        ))
    ranked.sort(key=lambda x: (x[0], x[1], x[2], x[3]))

    selected: List["SolutionState"] = []
    for _, _, _, _, state in ranked:
        if any(state_edge_similarity(state, existing) > 0.985 for existing in selected):
            continue
        selected.append(state)
        if len(selected) >= max_parents:
            break
    return selected or [guide_state, base_state][:max_parents]


def state_to_giant_tour(
        problem: HCVRPProblem,
        state: "SolutionState",
        customer_pool: Optional[List[int]] = None,
) -> List[int]:
    allowed = set(customer_pool) if customer_pool is not None else None
    tour: List[int] = []
    for route in state.routes:
        for customer in route_core(route):
            if allowed is None or customer in allowed:
                tour.append(customer)
    if customer_pool is None:
        return tour
    return complete_pack_trail(problem, customer_pool, tour)


def build_pack_giant_tour_orderings(
        problem: HCVRPProblem,
        customers: List[int],
        parent_states: List["SolutionState"],
        attempts: int = 4,
) -> List[List[int]]:
    unique_customers = list(dict.fromkeys(customers))
    if not unique_customers:
        return []

    parent_tours: List[List[int]] = []
    for state in parent_states:
        if state is None or not state.hard_feasible:
            continue
        parent_tour = state_to_giant_tour(problem, state, unique_customers)
        if parent_tour:
            parent_tours.append(parent_tour)
    if not parent_tours:
        return build_customer_pool_orderings(problem, unique_customers, attempts=max(2, attempts))

    pos_maps = [{customer: idx for idx, customer in enumerate(tour)} for tour in parent_tours]

    def consensus_construct(seed_customer: int) -> List[int]:
        remaining: Set[int] = set(unique_customers)
        if seed_customer not in remaining:
            seed_customer = max(
                unique_customers,
                key=lambda customer: (problem.dist[0][customer], problem.demands[customer], customer),
            )
        tour = [seed_customer]
        remaining.remove(seed_customer)
        while remaining:
            current = tour[-1]
            neighbor_votes: Dict[int, int] = {}
            rank_score: Dict[int, float] = {}
            for parent_tour, pos_map in zip(parent_tours, pos_maps):
                idx = pos_map.get(current)
                if idx is None:
                    continue
                if idx + 1 < len(parent_tour):
                    nxt = parent_tour[idx + 1]
                    if nxt in remaining:
                        neighbor_votes[nxt] = neighbor_votes.get(nxt, 0) + 2
                if idx - 1 >= 0:
                    prv = parent_tour[idx - 1]
                    if prv in remaining:
                        neighbor_votes[prv] = neighbor_votes.get(prv, 0) + 1
                for customer in remaining:
                    rank_score[customer] = rank_score.get(customer, 0.0) + pos_map.get(customer, len(parent_tour))

            candidate_pool = set(neighbor_votes) if neighbor_votes else set()
            if not candidate_pool:
                candidate_pool = set(remaining)
            next_customer = min(
                candidate_pool,
                key=lambda customer: (
                    -neighbor_votes.get(customer, 0),
                    rank_score.get(customer, 0.0) / max(1, len(parent_tours)),
                    problem.dist[current][customer],
                    -problem.demands[customer],
                    customer,
                ),
            )
            tour.append(next_customer)
            remaining.remove(next_customer)
        return tour

    seeds = []
    for tour in parent_tours:
        if tour:
            seeds.append(tour[0])
            seeds.append(tour[-1])
    seeds.extend([
        max(unique_customers, key=lambda customer: (problem.demands[customer], problem.dist[0][customer], customer)),
        max(unique_customers, key=lambda customer: (problem.dist[0][customer], problem.demands[customer], customer)),
    ])
    seeds = list(dict.fromkeys(seeds))

    orderings: List[List[int]] = []
    seen: Set[Tuple[int, ...]] = set()
    avg_rank_order = sorted(
        unique_customers,
        key=lambda customer: (
            sum(pos_map.get(customer, len(unique_customers)) for pos_map in pos_maps) / max(1, len(pos_maps)),
            -problem.demands[customer],
            customer,
        ),
    )
    for ordering in [avg_rank_order] + [consensus_construct(seed) for seed in seeds[:max(2, attempts + 1)]]:
        key = tuple(ordering)
        if key not in seen:
            seen.add(key)
            orderings.append(ordering)

    while len(orderings) < max(2, attempts):
        shuffled = unique_customers[:]
        random.shuffle(shuffled)
        ordering = complete_pack_trail(problem, unique_customers, shuffled)
        key = tuple(ordering)
        if key in seen:
            break
        seen.add(key)
        orderings.append(ordering)
    return orderings[:max(2, attempts)]


def strong_ejection_local_search(
        problem: HCVRPProblem,
        state: "SolutionState",
        plateau_level: int = 0,
        pulse_mode: bool = False,
        extra_passes: int = 1,
) -> "SolutionState":
    current = intensify_local_search(
        problem,
        state,
        max_rounds=2,
        pulse_mode=pulse_mode,
        plateau_level=plateau_level,
    )
    passes = max(1, extra_passes + max(0, plateau_level))
    chain_depth = int(ALGO_CONFIG["ejection_chain_base_depth"]) + (
        int(ALGO_CONFIG["ejection_chain_plateau_depth_bonus"]) if plateau_level > 0 else 0
    )
    for _ in range(passes):
        candidate = ejection_chain_phase(
            problem,
            current,
            max_source_routes=max(2, 3 + plateau_level),
            max_target_routes=max(4, 5 + plateau_level),
            max_eject_per_target=2,
            chain_depth=max(2, chain_depth),
        )
        candidate = intensify_local_search(
            problem,
            candidate,
            max_rounds=2,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        candidate = maybe_targeted_cleanup(
            problem,
            candidate,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        if candidate_is_progress(
                problem,
                current,
                candidate,
                allow_structural_progress=True,
                plateau_level=plateau_level):
            current = candidate
        else:
            break
    return current


def pack_crossover_phase(
        problem: HCVRPProblem,
        base_state: "SolutionState",
        guide_state: "SolutionState",
        parent_states: List["SolutionState"],
        plateau_level: int = 0,
        target_route_count: Optional[int] = None,
        attempts: Optional[int] = None,
) -> "SolutionState":
    if attempts is None:
        attempts = int(ALGO_CONFIG["pack_crossover_orderings"])
    if target_route_count is None:
        target_route_count = max(1, route_count(base_state))

    selected_parents = select_pack_crossover_parents(
        problem,
        base_state,
        guide_state,
        parent_states,
        plateau_level=plateau_level,
        max_parents=int(ALGO_CONFIG["pack_crossover_parent_count"]),
    )
    if len(selected_parents) < 2:
        return clone_solution_state(base_state)

    giant_tour_orderings = build_pack_giant_tour_orderings(
        problem,
        problem.customer_ids,
        selected_parents,
        attempts=max(2, attempts),
    )
    rebuilt = decode_customer_pool_with_split(
        problem,
        problem.customer_ids,
        target_route_count=max(1, target_route_count),
        guide_states=selected_parents,
        attempts=max(2, attempts),
        max_extra_routes=2,
        seed_orderings=giant_tour_orderings,
    )
    if rebuilt is None:
        return clone_solution_state(base_state)
    rebuilt_routes, rebuilt_vehicle_ids = rebuilt
    candidate = evaluate_solution(problem, rebuilt_routes, rebuilt_vehicle_ids)
    if not candidate.feasible:
        return clone_solution_state(base_state)
    candidate = strong_ejection_local_search(
        problem,
        candidate,
        plateau_level=plateau_level,
        pulse_mode=False,
        extra_passes=1,
    )
    if candidate_is_progress(
            problem,
            base_state,
            candidate,
            allow_structural_progress=True,
            plateau_level=plateau_level):
        return candidate
    return clone_solution_state(base_state)


def select_archive_parents(
        problem: HCVRPProblem,
        archive_population: List["SolutionState"],
        plateau_level: int = 0,
        max_parents: Optional[int] = None,
) -> List["SolutionState"]:
    if max_parents is None:
        max_parents = int(ALGO_CONFIG["pack_crossover_parent_count"])
    if not archive_population:
        return []
    candidate_pool = sorted(
        archive_population,
        key=lambda state: (
            pressured_total_cost(problem, state, plateau_level),
            route_count(state),
            state.total_cost,
        ),
    )[:max(2, int(ALGO_CONFIG["archive_parent_pool_size"]))]
    selected = [candidate_pool[0]]
    while len(selected) < min(max_parents, len(candidate_pool)):
        best_candidate = None
        best_score = float("-inf")
        for candidate in candidate_pool:
            if candidate in selected:
                continue
            novelty = state_novelty_against_pool(candidate, selected)
            score = 2.5 * novelty - 0.001 * pressured_total_cost(problem, candidate, plateau_level)
            if score > best_score:
                best_score = score
                best_candidate = candidate
        if best_candidate is None:
            break
        selected.append(best_candidate)
    return selected


def select_support_states_for_reference(
        problem: HCVRPProblem,
        pool: List["SolutionState"],
        reference_state: "SolutionState",
        plateau_level: int = 0,
        limit: int = 6,
) -> List["SolutionState"]:
    ranked: List[Tuple[float, float, float, int, "SolutionState"]] = []
    for idx, state in enumerate(pool):
        if state is None or not state.hard_feasible:
            continue
        similarity = state_edge_similarity(state, reference_state)
        novelty = 1.0 - similarity
        ranked.append((
            pressured_total_cost(problem, state, plateau_level),
            -novelty,
            state.total_cost,
            idx,
            state,
        ))
    ranked.sort()

    selected: List["SolutionState"] = []
    for _, _, _, _, state in ranked:
        if any(state_edge_similarity(state, existing) > 0.985 for existing in selected):
            continue
        selected.append(state)
        if len(selected) >= max(1, limit):
            break
    return selected


def generate_archive_offspring(
        problem: HCVRPProblem,
        archive_population: List["SolutionState"],
        elite_pool: List["SolutionState"],
        global_best: "SolutionState",
        plateau_level: int = 0,
        offspring_count: Optional[int] = None,
) -> List["SolutionState"]:
    if offspring_count is None:
        offspring_count = int(ALGO_CONFIG["archive_offspring_count"])
    if len(archive_population) < 2:
        return []

    offspring: List["SolutionState"] = []
    base_parents = select_archive_parents(
        problem,
        archive_population,
        plateau_level=max(plateau_level, 1),
        max_parents=max(2, int(ALGO_CONFIG["pack_crossover_parent_count"])),
    )
    if len(base_parents) < 2:
        return []

    parent_pool = list(archive_population) + list(elite_pool) + [global_best]
    for child_idx in range(max(1, offspring_count)):
        ordered = base_parents[child_idx % len(base_parents):] + base_parents[:child_idx % len(base_parents)]
        if len(ordered) < 2:
            break
        base_state = ordered[0]
        guide_state = ordered[1]
        aux_parents = ordered[2:] + parent_pool
        child = pack_crossover_phase(
            problem,
            base_state,
            guide_state,
            aux_parents,
            plateau_level=max(plateau_level, 1),
            target_route_count=max(1, min(route_count(base_state), route_count(guide_state))),
            attempts=max(2, int(ALGO_CONFIG["pack_crossover_orderings"])),
        )
        child = strong_ejection_local_search(
            problem,
            child,
            plateau_level=max(plateau_level, 1),
            pulse_mode=False,
            extra_passes=1,
        )
        if child.hard_feasible:
            offspring.append(child)
    return offspring


def tournament_select_state(
        problem: HCVRPProblem,
        population: List["SolutionState"],
        tournament_size: int,
        plateau_level: int = 0,
) -> Optional["SolutionState"]:
    candidates = [state for state in population if state is not None and state.hard_feasible]
    if not candidates:
        return None
    sample_size = min(max(1, tournament_size), len(candidates))
    sampled = random.sample(candidates, sample_size)
    return min(
        sampled,
        key=lambda state: (
            pressured_total_cost(problem, state, plateau_level),
            route_count(state),
            state.total_cost,
        ),
    )


def order_crossover_tours(
        parent_a: List[int],
        parent_b: List[int],
        customers: List[int],
) -> List[int]:
    customer_set = set(customers)
    a = [customer for customer in parent_a if customer in customer_set]
    b = [customer for customer in parent_b if customer in customer_set]
    if len(a) != len(customers):
        a = complete_pack_trail_for_order(customers, a)
    if len(b) != len(customers):
        b = complete_pack_trail_for_order(customers, b)
    n = len(customers)
    if n <= 2:
        return a[:]
    left = random.randrange(0, n - 1)
    right = random.randrange(left + 1, n)
    child: List[Optional[int]] = [None] * n
    child[left:right + 1] = a[left:right + 1]
    used = set(customer for customer in child if customer is not None)
    fill = [customer for customer in b if customer not in used]
    fill_idx = 0
    for idx in range(n):
        if child[idx] is None:
            child[idx] = fill[fill_idx]
            fill_idx += 1
    return [int(customer) for customer in child if customer is not None]


def complete_pack_trail_for_order(customers: List[int], partial_order: List[int]) -> List[int]:
    customer_set = set(customers)
    seen: Set[int] = set()
    order = []
    for customer in partial_order:
        if customer in customer_set and customer not in seen:
            order.append(customer)
            seen.add(customer)
    for customer in customers:
        if customer not in seen:
            order.append(customer)
            seen.add(customer)
    return order


def mutate_giant_tour_order(order: List[int], mutation_prob: float) -> List[int]:
    mutated = order[:]
    n = len(mutated)
    if n < 4 or random.random() >= mutation_prob:
        return mutated
    move = random.choice(("reverse", "swap", "shift"))
    if move == "reverse":
        left = random.randrange(0, n - 2)
        right = random.randrange(left + 2, n)
        mutated[left:right] = reversed(mutated[left:right])
    elif move == "swap":
        i, j = random.sample(range(n), 2)
        mutated[i], mutated[j] = mutated[j], mutated[i]
    else:
        left = random.randrange(0, n - 2)
        right = random.randrange(left + 1, n)
        block = mutated[left:right]
        rest = mutated[:left] + mutated[right:]
        insert_at = random.randrange(0, len(rest) + 1)
        mutated = rest[:insert_at] + block + rest[insert_at:]
    return mutated


def pulse_micro_hgs_mutation_rate(generation_idx: int, generations: int) -> float:
    if generations <= 1:
        return float(ALGO_CONFIG.get("pulse_micro_hgs_mutation_prob", 0.35))
    start = float(ALGO_CONFIG["pulse_micro_hgs_initial_mutation_prob"])
    end = float(ALGO_CONFIG["pulse_micro_hgs_final_mutation_prob"])
    progress = max(0.0, min(1.0, generation_idx / max(1, generations - 1)))
    return end + (start - end) * ((1.0 - progress) ** 1.35)


def decode_micro_hgs_tour(
        problem: HCVRPProblem,
        child_tour: List[int],
        parent_a: "SolutionState",
        parent_b: "SolutionState",
        global_best: "SolutionState",
        max_extra_routes: int,
        variant_limit: int,
        plateau_level: int = 0,
) -> Optional["SolutionState"]:
    lower_bound = route_count_lower_bound(problem)
    route_targets = [
        route_count(parent_a),
        route_count(parent_b),
        route_count(global_best),
        min(route_count(parent_a), route_count(parent_b), route_count(global_best)),
        lower_bound,
        lower_bound + 1,
    ]
    expanded_targets: List[int] = []
    for target in route_targets:
        for delta in (0, -1, 1):
            candidate_target = max(1, int(target) + delta)
            if candidate_target not in expanded_targets:
                expanded_targets.append(candidate_target)
    best_child: Optional["SolutionState"] = None
    for target_routes in expanded_targets[:max(1, variant_limit)]:
        decoded = split_pack_trail_into_routes(
            problem,
            child_tour,
            target_route_count=target_routes,
            max_extra_routes=max_extra_routes,
        )
        if decoded is None:
            continue
        child_routes, child_vehicle_ids = decoded
        child = evaluate_solution(problem, child_routes, child_vehicle_ids)
        if not child.hard_feasible:
            continue
        child = exact_route_polish_solution(problem, child)
        if (best_child is None
                or pressured_total_cost(problem, child, plateau_level) < pressured_total_cost(problem, best_child, plateau_level)
                or (pressured_total_cost(problem, child, plateau_level) == pressured_total_cost(problem, best_child, plateau_level)
                    and child.total_cost < best_child.total_cost)):
            best_child = child
    return best_child


def pulse_micro_hgs_phase(
        problem: HCVRPProblem,
        wolves: List[Wolf],
        archive_population: List["SolutionState"],
        elite_pool: List["SolutionState"],
        global_best: "SolutionState",
        alpha_idx: int,
        plateau_level: int = 0,
) -> Tuple[List["SolutionState"], Optional["SolutionState"]]:
    if not bool(ALGO_CONFIG.get("pulse_micro_hgs_enabled", True)):
        return [], None

    parent_pool = update_archive_population(
        [],
        list(archive_population) + list(elite_pool) + [global_best] + [wolf.best_state for wolf in wolves],
    )
    if len(parent_pool) < 2:
        return [], None

    generations = max(0, int(ALGO_CONFIG["pulse_micro_hgs_generations"]))
    tournament_size = max(1, int(ALGO_CONFIG["pulse_micro_hgs_tournament_size"]))
    keep_children = max(1, int(ALGO_CONFIG["pulse_micro_hgs_keep_children"]))
    max_extra_routes = int(ALGO_CONFIG["pulse_micro_hgs_max_extra_routes"])
    decode_variants = max(1, int(ALGO_CONFIG["pulse_micro_hgs_decode_variants"]))
    strong_polish_top = max(0, int(ALGO_CONFIG["pulse_micro_hgs_strong_polish_top"]))
    children: List["SolutionState"] = []
    customers = problem.customer_ids

    for generation_idx in range(generations):
        parent_a = tournament_select_state(problem, parent_pool, tournament_size, plateau_level=plateau_level)
        parent_b = tournament_select_state(problem, parent_pool, tournament_size, plateau_level=plateau_level)
        if parent_a is None or parent_b is None:
            break
        if parent_b is parent_a and len(parent_pool) > 1:
            alternatives = [state for state in parent_pool if state is not parent_a]
            parent_b = random.choice(alternatives)

        tour_a = state_to_giant_tour(problem, parent_a, customers)
        tour_b = state_to_giant_tour(problem, parent_b, customers)
        child_tour = order_crossover_tours(tour_a, tour_b, customers)
        mutation_prob = pulse_micro_hgs_mutation_rate(generation_idx, generations)
        child_tour = mutate_giant_tour_order(child_tour, mutation_prob)
        child = decode_micro_hgs_tour(
            problem,
            child_tour,
            parent_a,
            parent_b,
            global_best,
            max_extra_routes=max_extra_routes,
            variant_limit=decode_variants,
            plateau_level=plateau_level,
        )
        if child is None or not child.hard_feasible:
            continue
        children.append(child)
        parent_pool = update_archive_population(parent_pool, [child])

    if not children:
        return [], None

    ranked_children = sorted(
        children,
        key=lambda state: (
            pressured_total_cost(problem, state, plateau_level),
            -state_novelty_against_pool(state, parent_pool),
            state.total_cost,
        ),
    )
    polished_children: List["SolutionState"] = []
    for idx, child in enumerate(ranked_children[:keep_children]):
        if idx < strong_polish_top:
            child = hunt_end_exact_polish(problem, child, pulse_mode=True, plateau_level=plateau_level)
        polished_children.append(child)

    inject_archive_offspring_into_wolves(
        problem,
        wolves,
        polished_children[:int(ALGO_CONFIG["pulse_micro_hgs_inject_wolves"])],
        alpha_idx,
        plateau_level=plateau_level,
    )
    best_child = min(polished_children, key=lambda state: state.total_cost)
    return polished_children, best_child


def inject_archive_offspring_into_wolves(
        problem: HCVRPProblem,
        wolves: List[Wolf],
        offspring: List["SolutionState"],
        alpha_idx: int,
        plateau_level: int = 0,
) -> None:
    if not offspring:
        return
    candidate_indices = [idx for idx in range(len(wolves)) if idx != alpha_idx]
    if not candidate_indices:
        return

    pack_reference = [wolf.best_state for idx, wolf in enumerate(wolves) if idx != alpha_idx]
    ranked_targets = []
    for idx in candidate_indices:
        wolf = wolves[idx]
        novelty = state_novelty_against_pool(wolf.state, [wolves[alpha_idx].best_state])
        ranked_targets.append((
            novelty,
            pressured_total_cost(problem, wolf.best_state, plateau_level),
            idx,
        ))
    ranked_targets.sort(key=lambda item: (item[0], -item[1], item[2]))

    ranked_offspring = sorted(
        offspring,
        key=lambda state: (
            -state_novelty_against_pool(state, pack_reference),
            pressured_total_cost(problem, state, plateau_level),
            state.total_cost,
        ),
    )

    rel_slack = float(ALGO_CONFIG["archive_injection_rel_slack"])
    novelty_min = float(ALGO_CONFIG["archive_injection_novelty_min"])
    inject_limit = min(
        int(ALGO_CONFIG["archive_injection_wolves"]),
        len(ranked_targets),
        len(ranked_offspring),
    )
    used_targets: Set[int] = set()
    injections = 0
    for child in ranked_offspring:
        if injections >= inject_limit:
            break
        child_novelty = state_novelty_against_pool(child, pack_reference)
        for _, _, target_idx in ranked_targets:
            if target_idx in used_targets:
                continue
            target_wolf = wolves[target_idx]
            target_best = target_wolf.best_state
            quality_ok = child.total_cost <= target_best.total_cost * (1.0 + rel_slack)
            if not quality_ok and child.total_cost > target_wolf.state.total_cost:
                continue
            if child_novelty < novelty_min and child.total_cost >= target_best.total_cost:
                continue
            target_wolf.state = clone_solution_state(child)
            if child.hard_feasible and child.total_cost < target_wolf.best_state.total_cost:
                target_wolf.best_state = clone_solution_state(child)
            used_targets.add(target_idx)
            injections += 1
            break

def route_pool_set_partition_phase(
        problem: HCVRPProblem,
        base_state: "SolutionState",
        pool_states: List["SolutionState"],
        target_route_count: Optional[int] = None,
        attempts: Optional[int] = None,
        plateau_level: int = 0,
) -> "SolutionState":
    if attempts is None:
        attempts = int(ALGO_CONFIG["route_pool_attempts"])
    if target_route_count is None:
        target_route_count = max(1, route_count(base_state))
    pool_entries = build_route_pool_entries([base_state] + pool_states)
    if len(pool_entries) < 2:
        return clone_solution_state(base_state)

    orderings: List[List[Tuple[Route, float]]] = [
        sorted(pool_entries, key=lambda item: (item[1] / max(1, len(route_core(item[0]))), item[1])),
        sorted(pool_entries, key=lambda item: (-len(route_core(item[0])), item[1])),
        sorted(pool_entries, key=lambda item: (item[1], -len(route_core(item[0])))),
    ]
    while len(orderings) < max(1, attempts):
        shuffled = pool_entries[:]
        random.shuffle(shuffled)
        orderings.append(shuffled)

    def evaluate_ordering(ordering: List[Tuple[Route, float]]) -> Optional["SolutionState"]:
        selected_routes: Route_matrix = []
        covered: Set[int] = set()
        for route, _ in ordering:
            route_set = set(route_core(route))
            if route_set & covered:
                continue
            selected_routes.append(normalize_route(route))
            covered |= route_set
            if len(covered) == len(problem.customer_ids):
                break
            if len(selected_routes) >= target_route_count + 2 and len(covered) >= int(0.85 * len(problem.customer_ids)):
                break

        if not selected_routes:
            return None

        selected_vehicle_ids: List[int] = []
        type_usage: Dict[int, int] = {}
        vehicle_assignment_ok = True
        for route in selected_routes:
            v_id = assign_best_feasible_vehicle_for_tour(problem, route, type_usage)
            if v_id is None:
                vehicle_assignment_ok = False
                break
            selected_vehicle_ids.append(v_id)
            type_usage[v_id] = type_usage.get(v_id, 0) + 1
        if not vehicle_assignment_ok:
            return None

        uncovered = [customer for customer in problem.customer_ids if customer not in covered]
        routes_try = clone_routes(selected_routes)
        vehicle_ids_try = selected_vehicle_ids[:]
        if uncovered:
            uncovered_set = set(uncovered)
            uncovered_seed_routes = [
                route for route, _ in ordering
                if set(route_core(route)) & uncovered_set
            ][:max(1, target_route_count)]
            rebuilt = decode_customer_pool_with_split(
                problem,
                uncovered,
                max(1, target_route_count - len(routes_try)),
                seed_routes=uncovered_seed_routes,
                guide_states=pool_states,
                attempts=max(2, attempts),
                max_extra_routes=2,
                seed_type_usage=type_usage,
            )
            if rebuilt is None:
                return None
            rebuilt_routes, rebuilt_vehicle_ids = rebuilt
            routes_try.extend(rebuilt_routes)
            vehicle_ids_try.extend(rebuilt_vehicle_ids)

        candidate = evaluate_solution(problem, routes_try, vehicle_ids_try)
        return candidate if candidate.feasible else None

    orderings = orderings[:max(1, attempts)]
    best_candidate: Optional["SolutionState"] = None
    use_parallel = (
        len(orderings) >= int(ALGO_CONFIG["route_pool_parallel_min_attempts"])
    )
    if use_parallel:
        workers = min(
            int(ALGO_CONFIG["route_pool_parallel_max_workers"]),
            max(1, len(orderings)),
        )
        executor = get_shared_local_search_executor(workers)
        futures = [executor.submit(evaluate_ordering, ordering) for ordering in orderings]
        candidates = [future.result() for future in futures]
    else:
        candidates = [evaluate_ordering(ordering) for ordering in orderings]

    for candidate in candidates:
        if candidate is None:
            continue
        if (best_candidate is None
                or pressured_total_cost(problem, candidate, plateau_level) < pressured_total_cost(problem, best_candidate, plateau_level)):
            best_candidate = candidate

    if best_candidate is not None and candidate_is_progress(
            problem, base_state, best_candidate,
            allow_structural_progress=True,
            plateau_level=plateau_level):
        return best_candidate
    return clone_solution_state(base_state)


def _complete_ejection_chain(
        problem: HCVRPProblem,
        partial_state: "SolutionState",
        pending_customer: int,
        visited_routes: Set[int],
        depth_remaining: int,
        max_target_routes: int,
        max_eject_per_target: int,
) -> Optional["SolutionState"]:
    best_candidate: Optional["SolutionState"] = None

    routes_try = clone_routes(partial_state.routes)
    vehicle_ids_try = partial_state.vehicle_ids[:]
    type_usage = _type_usage_from_ids(vehicle_ids_try)
    pending = [pending_customer]
    route_centroids_try = compute_route_centroids(problem, routes_try) if routes_try else []
    if _apply_regret_insertion(
            problem,
            routes_try,
            vehicle_ids_try,
            type_usage,
            pending,
            allow_new_route=True,
            route_centroids=route_centroids_try):
        direct_candidate = evaluate_solution(problem, routes_try, vehicle_ids_try)
        if direct_candidate.feasible:
            best_candidate = direct_candidate

    if depth_remaining <= 0:
        return best_candidate

    route_centroids = compute_route_centroids(problem, partial_state.routes)
    route_arrays = _routes_to_numpy(partial_state.routes) if (NUMBA_AVAILABLE and np is not None) else None
    target_indices = select_candidate_route_indices(
        problem,
        partial_state.routes,
        pending_customer,
        max_candidates=max_target_routes,
        route_centroids=route_centroids,
        route_arrays=route_arrays,
    )
    for target_idx in target_indices:
        if target_idx in visited_routes or target_idx >= len(partial_state.routes):
            continue
        target_core = route_core(partial_state.routes[target_idx])
        if not target_core:
            continue
        eject_candidates = _state_route_outliers(
            problem,
            partial_state,
            target_idx,
            min(max_eject_per_target, len(target_core)),
        )
        for ejected in eject_candidates:
            target_without_ejected = [n for n in target_core if n != ejected]
            target_route = [0] + target_without_ejected + [0]
            insert_pos, _ = choose_best_insertion_position(problem, target_route, pending_customer)
            new_target_route = target_route[:]
            new_target_route.insert(insert_pos, pending_customer)
            next_state = evaluate_fixed_vehicle_route_delta_allow_removal(
                problem,
                partial_state,
                {target_idx: new_target_route},
            )
            if next_state is None or not next_state.feasible:
                continue
            candidate = _complete_ejection_chain(
                problem,
                next_state,
                ejected,
                visited_routes | {target_idx},
                depth_remaining - 1,
                max_target_routes,
                max_eject_per_target,
            )
            if candidate is not None and (best_candidate is None or candidate.total_cost < best_candidate.total_cost):
                best_candidate = candidate
    return best_candidate


def ejection_chain_phase(
        problem: HCVRPProblem,
        state: "SolutionState",
        max_source_routes: int = 3,
        max_target_routes: int = 4,
        max_eject_per_target: int = 2,
        chain_depth: int = 2,
) -> "SolutionState":
    active = [i for i, route in enumerate(state.routes) if len(route_core(route)) >= 2]
    if len(active) < 2:
        return clone_solution_state(state)

    ranked_sources = sorted(
        ((route_badness_score(problem, state, r_idx), r_idx) for r_idx in active),
        key=lambda x: (-x[0], x[1])
    )
    best_state = clone_solution_state(state)

    for _, source_idx in ranked_sources[:max_source_routes]:
        source_core = route_core(state.routes[source_idx])
        source_take = min(len(source_core), max(1, max_eject_per_target + 1))
        source_candidates = _state_route_outliers(problem, state, source_idx, source_take)
        for customer in source_candidates:
            reduced_source = [0] + [n for n in source_core if n != customer] + [0]
            base_candidate = evaluate_fixed_vehicle_route_delta_allow_removal(
                problem,
                state,
                {source_idx: reduced_source},
            )
            if base_candidate is None or not base_candidate.feasible:
                continue
            candidate = _complete_ejection_chain(
                problem,
                base_candidate,
                customer,
                {source_idx},
                max(0, chain_depth - 1),
                max_target_routes,
                max_eject_per_target,
            )
            if candidate is not None and candidate_is_progress(problem, best_state, candidate, allow_structural_progress=True):
                best_state = candidate

    return best_state


# ==============================================================================
#  ALPHA / HUNT MEKANİZMASI
# ==============================================================================

def select_alpha_index(
        wolves: List[Wolf],
        elite_pool: Optional[List["SolutionState"]] = None,
        plateau_level: int = 0,
) -> int:
    problem = wolves[0].problem
    cq = minmax_normalize_costs_to_quality([
        pressured_total_cost(problem, w.best_state, plateau_level) for w in wolves
    ])
    bq = minmax_normalize_values([w.blood for w in wolves])
    hq = minmax_normalize_values([w.best_quality_score for w in wolves])
    nq = minmax_normalize_values([
        state_novelty_against_pool(w.best_state, elite_pool or [])
        for w in wolves
    ])
    cw = float(ALGO_CONFIG["alpha_cost_weight"])
    bw = float(ALGO_CONFIG["alpha_blood_weight"])
    hw = float(ALGO_CONFIG["alpha_history_weight"])
    nw = float(ALGO_CONFIG["plateau_alpha_novelty_weight"]) * max(0, plateau_level)
    total = cw + bw + hw + nw; cw /= total; bw /= total; hw /= total; nw /= total
    best_idx = 0; best_score = cw * cq[0] + bw * bq[0] + hw * hq[0] + nw * nq[0]
    for i in range(1, len(wolves)):
        score = cw * cq[i] + bw * bq[i] + hw * hq[i] + nw * nq[i]
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
        oscillation: Optional[OscillationController] = None,   # SO: faz kontrolü
        parallel_workers: int = 1,
):
    update_interval = int(ALGO_CONFIG["free_search_quality_update_interval"])
    parallel_workers = max(1, min(int(parallel_workers), len(wolves)))
    if parallel_workers > 1 and len(wolves) > 1:
        executor = get_shared_wolf_executor(
            min(parallel_workers, int(ALGO_CONFIG["wolf_parallel_max_workers"]))
        )
        for step in range(iterations_per_wolf):
            if oscillation is not None:
                oscillation.step()
            futures = [
                executor.submit(
                    explore_one_step,
                    wolf=wolf,
                    closed_regions=closed_regions,
                    lambda_reg=lambda_reg,
                    a=a,
                    b=b,
                    c=c,
                    b_par=b_par,
                )
                for wolf in wolves
            ]
            for future in futures:
                future.result()
            if (step + 1) % update_interval == 0:
                update_population_quality_scores(wolves)
    else:
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
        wolf: Wolf, guide_state: "SolutionState", route_pool_states: Optional[List["SolutionState"]] = None,
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, hunt_chain_passes: int = 2,
        bandit: Optional["DestroyBandit"] = None,
        operator_bandit: Optional["HuntOperatorBandit"] = None,
        destroy_modes: Optional[List[str]] = None,
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> "SolutionState":
    current  = alpha_guided_rebuild(wolf.problem, wolf.state, guide_state, inherit_frac, plateau_level=plateau_level)
    current  = intensify_local_search(wolf.problem, current, max_rounds=3, pulse_mode=pulse_mode, plateau_level=plateau_level)
    current  = maybe_targeted_cleanup(wolf.problem, current, pulse_mode=pulse_mode, plateau_level=plateau_level)
    relinked = elite_path_relink(wolf.problem, current, guide_state, max_steps=6)
    relinked = intensify_local_search(wolf.problem, relinked, max_rounds=2, pulse_mode=pulse_mode, plateau_level=plateau_level)
    relinked = maybe_targeted_cleanup(wolf.problem, relinked, pulse_mode=pulse_mode, plateau_level=plateau_level)
    if candidate_is_progress(
            wolf.problem, current, relinked,
            allow_structural_progress=True,
            plateau_level=plateau_level):
        current = relinked
    best = current

    chain_passes = max(1, min(3, hunt_chain_passes))
    chain_depth = int(ALGO_CONFIG["ejection_chain_base_depth"]) + (
        int(ALGO_CONFIG["ejection_chain_plateau_depth_bonus"]) if plateau_level > 0 else 0
    )

    def run_pack(base_state: "SolutionState") -> "SolutionState":
        candidate = pack_crossover_phase(
            wolf.problem,
            base_state,
            guide_state,
            [wolf.best_state, current] + list(route_pool_states or []),
            plateau_level=plateau_level,
            target_route_count=max(1, route_count(base_state)),
            attempts=int(ALGO_CONFIG["pack_crossover_orderings"]),
        )
        candidate = intensify_local_search(
            wolf.problem, candidate,
            max_rounds=2,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        return maybe_targeted_cleanup(
            wolf.problem, candidate,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )

    def run_ejection(base_state: "SolutionState") -> "SolutionState":
        candidate = clone_solution_state(base_state)
        for _ in range(chain_passes):
            step_candidate = ejection_chain_phase(
                wolf.problem,
                candidate,
                max_source_routes=max(2, 2 + plateau_level),
                max_target_routes=max(3, 4 + plateau_level),
                max_eject_per_target=2,
                chain_depth=chain_depth,
            )
            step_candidate = intensify_local_search(
                wolf.problem, step_candidate,
                max_rounds=2,
                pulse_mode=pulse_mode,
                plateau_level=plateau_level,
            )
            if candidate_is_progress(
                    wolf.problem, candidate, step_candidate,
                    allow_structural_progress=True,
                    plateau_level=plateau_level):
                candidate = step_candidate
        return candidate

    def run_merge(base_state: "SolutionState") -> "SolutionState":
        candidate = merge_and_repartition_phase(
            wolf.problem,
            base_state,
            guide_state=guide_state,
            inherit_frac=inherit_frac,
            max_routes_to_rebuild=max(3, min(6, 3 + plateau_level + hunt_chain_passes // 2)),
            plateau_level=plateau_level,
        )
        return strong_ejection_local_search(
            wolf.problem, candidate,
            plateau_level=plateau_level,
            pulse_mode=pulse_mode,
            extra_passes=1 if plateau_level > 0 else 0,
        )

    def run_route_pool(base_state: "SolutionState") -> "SolutionState":
        candidate = route_pool_set_partition_phase(
            wolf.problem,
            base_state,
            pool_states=(route_pool_states or []) + [guide_state, wolf.best_state, current],
            target_route_count=max(1, route_count(base_state)),
            attempts=int(ALGO_CONFIG["route_pool_attempts"]),
            plateau_level=plateau_level,
        )
        return strong_ejection_local_search(
            wolf.problem, candidate,
            plateau_level=plateau_level,
            pulse_mode=pulse_mode,
            extra_passes=1 if plateau_level > 0 else 0,
        )

    def run_fallback(base_state: "SolutionState") -> "SolutionState":
        if destroy_modes is not None and destroy_modes:
            fallback_mode = destroy_modes[0]
        else:
            fallback_mode = sample_destroy_mode()
        candidate = ruin_and_rebuild_routes(
            wolf.problem, base_state, ruin_frac=ruin_frac,
            destroy_mode=fallback_mode,
            bandit=(None if destroy_modes is not None else bandit),
            use_bandit=(bandit is not None and destroy_modes is None),
        )
        candidate = intensify_local_search(
            wolf.problem, candidate,
            max_rounds=2,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        return maybe_targeted_cleanup(
            wolf.problem, candidate,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )

    operator_runners = {
        "pack": run_pack,
        "ejection": run_ejection,
        "merge": run_merge,
        "route_pool": run_route_pool,
        "fallback": run_fallback,
    }
    operator_order = (
        operator_bandit.sample_order(include_fallback=True)
        if operator_bandit is not None
        else ["pack", "ejection", "merge", "route_pool", "fallback"]
    )
    for op_name in operator_order:
        base_before = clone_solution_state(best)
        candidate = operator_runners[op_name](best)
        accepted = candidate_is_progress(
            wolf.problem, best, candidate,
            allow_structural_progress=True,
            plateau_level=plateau_level)
        if operator_bandit is not None:
            reward = (
                operator_bandit.reward_value(base_before, candidate, wolf.problem, plateau_level)
                if accepted
                else float(ALGO_CONFIG["bandit_reward_fail"])
            )
            operator_bandit.update(op_name, reward)
        if accepted:
            best = candidate
    return best

def hunt_around_alpha(
        wolves: List[Wolf], alpha_idx: int,
        elite_pool: Optional[List["SolutionState"]] = None,
        archive_population: Optional[List["SolutionState"]] = None,
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, hunt_chain_passes: int = 2,
        bandit: Optional["DestroyBandit"] = None,
        operator_bandit: Optional["HuntOperatorBandit"] = None,
        parallel_workers: int = 1,
        pulse_mode: bool = False,
        plateau_level: int = 0,
) -> Tuple["SolutionState", float]:
    alpha           = wolves[alpha_idx]
    alpha_state     = alpha.best_state
    hunt_best_state = alpha.clone_state(alpha_state)
    hunt_best_cost  = alpha_state.total_cost
    tasks: List[Tuple[int, Wolf, "SolutionState", Optional[List[str]], List["SolutionState"]]] = []
    for i, wolf in enumerate(wolves):
        if i == alpha_idx:
            continue
        guide_states = [alpha_state]
        route_pool_states = select_support_states_for_reference(
            wolf.problem,
            list(elite_pool or []) + list(archive_population or []),
            wolf.state,
            plateau_level=plateau_level,
            limit=max(4, min(8, int(ALGO_CONFIG["archive_parent_pool_size"]))),
        )
        elite_guide  = choose_elite_guide(wolf.problem, elite_pool or [], wolf.state, plateau_level=plateau_level)
        if elite_guide is not None and state_edge_similarity(elite_guide, alpha_state) < 0.98:
            guide_states.append(elite_guide)
        archive_guide = choose_elite_guide(wolf.problem, archive_population or [], wolf.state, plateau_level=plateau_level)
        if (archive_guide is not None
                and state_edge_similarity(archive_guide, alpha_state) < 0.985
                and all(state_edge_similarity(archive_guide, existing) < 0.99 for existing in guide_states)):
            guide_states.append(archive_guide)
        for guide_state in guide_states:
            destroy_modes = None
            if plateau_level > 0:
                cycle = ("targeted", "route", "worst", "shaw")
                destroy_modes = [cycle[(plateau_level + step_idx) % len(cycle)] for step_idx in range(hunt_chain_passes)]
            elif bandit is not None and parallel_workers > 1:
                destroy_modes = [
                    choose_bandit_mode_for_state(wolf.problem, wolf.state, bandit)
                    for _ in range(hunt_chain_passes)
                ]
            tasks.append((i, wolf, guide_state, destroy_modes, route_pool_states))

    wolf_best_candidates: Dict[int, "SolutionState"] = {}
    if parallel_workers > 1 and len(tasks) > 1:
        executor = get_shared_wolf_executor(
            min(parallel_workers, int(ALGO_CONFIG["wolf_parallel_max_workers"]))
        )
        future_map = {
            executor.submit(
                hunt_one_wolf_towards_alpha,
                wolf,
                guide_state,
                route_pool_states,
                inherit_frac,
                ruin_frac,
                hunt_chain_passes,
                bandit,
                operator_bandit,
                destroy_modes,
                pulse_mode,
                plateau_level,
            ): i
            for i, wolf, guide_state, destroy_modes, route_pool_states in tasks
        }
        for future in as_completed(future_map):
            i = future_map[future]
            candidate = future.result()
            prev = wolf_best_candidates.get(i)
            if prev is None or pressured_total_cost(wolves[i].problem, candidate, plateau_level) < pressured_total_cost(wolves[i].problem, prev, plateau_level):
                wolf_best_candidates[i] = candidate
    else:
        for i, wolf, guide_state, destroy_modes, route_pool_states in tasks:
            candidate = hunt_one_wolf_towards_alpha(
                wolf, guide_state, route_pool_states, inherit_frac, ruin_frac, hunt_chain_passes,
                bandit=bandit, operator_bandit=operator_bandit,
                destroy_modes=destroy_modes, pulse_mode=pulse_mode,
                plateau_level=plateau_level
            )
            prev = wolf_best_candidates.get(i)
            if prev is None or pressured_total_cost(wolf.problem, candidate, plateau_level) < pressured_total_cost(wolf.problem, prev, plateau_level):
                wolf_best_candidates[i] = candidate

    for i, candidate in wolf_best_candidates.items():
        wolf = wolves[i]
        candidate = hunt_end_exact_polish(
            wolf.problem,
            candidate,
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        wolf.update_if_better(candidate)
        if candidate.hard_feasible and (
                pressured_total_cost(wolf.problem, candidate, plateau_level) < pressured_total_cost(wolf.problem, hunt_best_state, plateau_level)
                or candidate.total_cost < hunt_best_cost):  # SO: hard_feasible
            hunt_best_state = alpha.clone_state(candidate)
            hunt_best_cost = candidate.total_cost
    hunt_best_state = hunt_end_exact_polish(
        alpha.problem,
        hunt_best_state,
        pulse_mode=pulse_mode,
        plateau_level=plateau_level,
    )
    hunt_best_cost = hunt_best_state.total_cost
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
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, hunt_chain_passes: int = 2,
        wolf_parallel_workers: int = 1,
        verbose: bool = True, random_seed: Optional[int] = None,
        target_optimal_cost: Optional[float] = None,
        # SO: Strategic Oscillation parametreleri (None → ALGO_CONFIG'ten alınır)
        so_cap_penalty_weight: Optional[float] = None,
        so_relax_period:       Optional[int]   = None,
        so_enforce_period:     Optional[int]   = None,
) -> "SolutionState":
    if random_seed is not None: random.seed(random_seed)
    started_at = time.perf_counter()
    stopped_on_target = False

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
    archive_population = update_archive_population([], [w.best_state for w in wolves] + [global_best])
    closed_regions: List[Set[Edge]] = []
    hunts_without_global_improvement = 0

    bandit = DestroyBandit(eps=float(ALGO_CONFIG["destroy_bandit_eps"]))
    operator_bandit = HuntOperatorBandit(eps=float(ALGO_CONFIG["operator_bandit_eps"]))
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
        pulse_mode = is_pulse_hunt(hunt_idx + 1)
        plateau_level = compute_plateau_level(hunts_without_global_improvement)
        current_ruin_frac = get_plateau_ruin_frac(ruin_frac, plateau_level)
        current_hunt_chain_passes = get_plateau_hunt_chain_passes(hunt_chain_passes, plateau_level)
        current_a, current_c, current_b_par = get_plateau_acceptance_params(a, c, b_par, plateau_level)
        reset_wolves_for_new_hunt(wolves, reserve_blood=reserve_blood, clear_history=True)

        # SO: free_search başlangıcında oscillation devreye alınır, ENFORCE'tan başlar
        oscillation.set_phase("ENFORCE")
        set_active_oscillation(oscillation)

        free_search_phase(
            wolves=wolves, iterations_per_wolf=explore_iterations,
            closed_regions=closed_regions, lambda_reg=lambda_reg,
            a=current_a, b=b, c=current_c, b_par=current_b_par,
            oscillation=oscillation,    # SO: faz adımlaması için geçilir
            parallel_workers=wolf_parallel_workers,
        )

        # SO: Hunt ve LS aşamalarına geçmeden önce oscillation kapatılır (hard mod).
        # Bu sayede araç ataması, regret insertion ve intensify_local_search
        # her zaman hard kapasite kısıtı ile çalışır.
        set_active_oscillation(None)

        alpha_idx = select_alpha_index(wolves, elite_pool=elite_pool, plateau_level=plateau_level)
        hunt_best_state, hunt_best_cost = hunt_around_alpha(
            wolves, alpha_idx, elite_pool, archive_population, inherit_frac, current_ruin_frac, current_hunt_chain_passes,
            bandit=bandit, operator_bandit=operator_bandit,
            parallel_workers=wolf_parallel_workers, pulse_mode=pulse_mode,
            plateau_level=plateau_level
        )
        if hunts_without_global_improvement >= int(ALGO_CONFIG["stagnation_hunt_limit"]):
            kick = stagnation_kick(
                problem, hunt_best_state,
                ruin_frac=min(float(ALGO_CONFIG["stagnation_ruin_cap"]),
                              current_ruin_frac + float(ALGO_CONFIG["stagnation_ruin_boost"])),
                bandit=bandit
            )
            if candidate_is_progress(problem, hunt_best_state, kick, allow_structural_progress=True, plateau_level=plateau_level):
                hunt_best_state = kick; hunt_best_cost = kick.total_cost

        if (plateau_level > 0
                and int(ALGO_CONFIG["diversification_burst_interval"]) > 0
                and (hunt_idx + 1) % int(ALGO_CONFIG["diversification_burst_interval"]) == 0):
            diversification_burst(
                wolves,
                global_best,
                current_ruin_frac,
                plateau_level,
                alpha_idx,
                bandit=bandit,
            )

        full_moon = full_moon_phase(
            problem, hunt_best_state,
            pack_states=list(elite_pool) + [global_best],
            max_bad_routes=int(ALGO_CONFIG["full_moon_bad_routes"]),
            neighbor_routes=int(ALGO_CONFIG["full_moon_neighbor_routes"]),
            max_routes_to_rebuild=int(ALGO_CONFIG["full_moon_max_routes"]),
            attempts=int(ALGO_CONFIG["full_moon_attempts"]),
            post_ls_rounds=int(ALGO_CONFIG["full_moon_post_ls_rounds"]),
            pulse_mode=pulse_mode,
            plateau_level=plateau_level,
        )
        if candidate_is_progress(problem, hunt_best_state, full_moon, allow_structural_progress=True, plateau_level=plateau_level):
            hunt_best_state = full_moon
            hunt_best_cost = full_moon.total_cost

        if hunt_best_cost < global_best.total_cost:
            prev_global_best_cost = global_best.total_cost
            improvement_class = classify_improvement_magnitude(prev_global_best_cost, hunt_best_cost)
            global_best = wolves[alpha_idx].clone_state(hunt_best_state)
            if bandit.last_mode is not None:
                bandit.update(
                    bandit.last_mode,
                    bandit.reward_value("global_best", max(0.0, prev_global_best_cost - hunt_best_cost))
                )
            if improvement_class == "strong":
                hunts_without_global_improvement = 0
            elif improvement_class == "soft":
                hunts_without_global_improvement = max(
                    0,
                    hunts_without_global_improvement - int(ALGO_CONFIG["stagnation_soft_reset_decrement"])
                )
        else:
            hunts_without_global_improvement += 1

        closed_regions.append(build_edge_signature_from_routes(hunt_best_state.routes))
        update_population_quality_scores(wolves)
        elite_pool = update_elite_pool(
            elite_pool, [w.best_state for w in wolves] + [hunt_best_state, global_best]
        )
        archive_population = update_archive_population(
            archive_population,
            [w.best_state for w in wolves] + [hunt_best_state, global_best] + list(elite_pool),
        )

        if ((hunt_idx + 1) >= int(ALGO_CONFIG["archive_activation_hunt"])
                and int(ALGO_CONFIG["archive_injection_interval"]) > 0
                and (hunt_idx + 1) % int(ALGO_CONFIG["archive_injection_interval"]) == 0):
            archive_offspring = generate_archive_offspring(
                problem,
                archive_population,
                elite_pool,
                global_best,
                plateau_level=plateau_level,
                offspring_count=int(ALGO_CONFIG["archive_offspring_count"]),
            )
            archive_population = update_archive_population(
                archive_population,
                archive_offspring,
            )
            inject_archive_offspring_into_wolves(
                problem,
                wolves,
                archive_offspring,
                alpha_idx,
                plateau_level=plateau_level,
            )
            update_population_quality_scores(wolves)

        if pulse_mode:
            hgs_children, hgs_best = pulse_micro_hgs_phase(
                problem,
                wolves,
                archive_population,
                elite_pool,
                global_best,
                alpha_idx,
                plateau_level=plateau_level,
            )
            if hgs_children:
                archive_population = update_archive_population(archive_population, hgs_children)
                elite_pool = update_elite_pool(elite_pool, hgs_children + [global_best])
                update_population_quality_scores(wolves)
            if hgs_best is not None and hgs_best.hard_feasible and hgs_best.total_cost < global_best.total_cost:
                global_best = clone_solution_state(hgs_best)
                hunt_best_state = clone_solution_state(hgs_best)
                hunt_best_cost = hgs_best.total_cost
                hunts_without_global_improvement = 0

        if verbose:
            c_min, c_mean, c_max = population_cost_stats(wolves)
            so_s = oscillation.stats()
            elapsed_now = time.perf_counter() - started_at
            print(
                f"Hunt {hunt_idx+1}/{num_hunts} | alpha={alpha_idx} | "
                f"hunt_best={hunt_best_cost:.4f} | global_best={global_best.total_cost:.4f} | "
                f"elapsed={elapsed_now:.2f}s | "
                f"pulse={int(pulse_mode)} | "
                f"plateau={plateau_level} | "
                f"hunt_routes={route_count(hunt_best_state)} | best_routes={route_count(global_best)} | "
                f"pop_min={c_min:.4f} | pop_mean={c_mean:.4f} | pop_max={c_max:.4f} | "
                f"stagnation={hunts_without_global_improvement} | "
                f"closed_regions={len(closed_regions)} | elite_pool={len(elite_pool)} | archive={len(archive_population)} | "
                f"bandit={bandit.stats()} | "
                f"op_bandit={operator_bandit.stats()} | "
                f"so_relax={so_s['relax_entered']} so_enforce={so_s['enforce_entered']}"  # SO
            )

        if target_optimal_cost is not None and global_best.total_cost <= float(target_optimal_cost):
            stopped_on_target = True
            if verbose:
                print(
                    f"Target reached at hunt {hunt_idx+1}/{num_hunts} | "
                    f"target={float(target_optimal_cost):.4f} | best={global_best.total_cost:.4f}"
                )
            break

    # SO: Çalışma bitti — oscillation kapalı bırakılır
    set_active_oscillation(None)

    elapsed_sec = time.perf_counter() - started_at
    setattr(global_best, "elapsed_sec", elapsed_sec)
    setattr(global_best, "target_optimal_cost", target_optimal_cost)
    setattr(global_best, "stopped_on_target", stopped_on_target)
    if target_optimal_cost is not None and float(target_optimal_cost) > 0.0:
        gap_pct = max(0.0, (global_best.total_cost - float(target_optimal_cost)) / float(target_optimal_cost) * 100.0)
        setattr(global_best, "optimality_gap_pct", gap_pct)
    else:
        setattr(global_best, "optimality_gap_pct", None)

    return global_best


# ==============================================================================
#  GİRİŞ NOKTASI
# ==============================================================================

if __name__ == "__main__":

    SEARCH_PARAMS = {
        "num_wolves":         6,
        "num_hunts":          9,
        "explore_iterations": 100,
        "reserve_blood":      3,
        "lambda_reg":         1,
        "a":                  1.0,
        "b":                  2.0,
        "c":                  1.3,
        "b_par":              1.2,
        "inherit_frac":       0.90,
        "ruin_frac":          0.40,
        "hunt_chain_passes":  2,
        "wolf_parallel_workers": 3,
        "verbose":            True,
        "random_seed":        9,
        "target_optimal_cost": 910,
        # SO: İsteğe bağlı override — None bırakılırsa ALGO_CONFIG değerleri kullanılır
        "so_cap_penalty_weight": None,
        "so_relax_period":       None,
        "so_enforce_period":     None,
    }

    DATASET_DIR = Path(__file__).resolve().parent / "Test_data"
    requested_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (DATASET_DIR / "christofides-et-al-1979-cmt" / "CMT07.xml")
    if not requested_path.exists():
        requested_path = DATASET_DIR

    DATASET_FILE = resolve_supported_dataset_path(requested_path)

    print(f"Veri dosyasi: {DATASET_FILE.name}")
    problem = load_supported_instance(DATASET_FILE)

    best_state = run_bloodhound_hcvrp(problem=problem, **SEARCH_PARAMS)

    print("\n===== FINAL BEST =====")
    print("Instance   :", getattr(problem, "original_vrplib_name", "?"))
    print("Feasible   :", best_state.feasible)
    print("Hard Feas. :", best_state.hard_feasible)
    print("Route count:", route_count(best_state))
    print("Total cost :", round(best_state.total_cost, 4))
    if getattr(best_state, "elapsed_sec", None) is not None:
        print("Elapsed sec:", round(float(best_state.elapsed_sec), 4))
    if getattr(best_state, "target_optimal_cost", None) is not None:
        print("Target cost:", round(float(best_state.target_optimal_cost), 4))
        if bool(getattr(best_state, "stopped_on_target", False)):
            print("Target hit :", True)
        else:
            print("Target hit :", False)
            gap_pct = getattr(best_state, "optimality_gap_pct", None)
            if gap_pct is not None:
                print("Opt gap % :", round(float(gap_pct), 4))
    type_counts = Counter(best_state.vehicle_ids)
    print("Type usage :", {f"type{t}(cap={problem.vehicle_types[t].capacity})": c
                           for t, c in sorted(type_counts.items())})
    print("Route loads:", best_state.route_loads)
    print("Route dist :", best_state.route_distances)
    print("Route costs:", best_state.route_costs)
    for i, route in enumerate(best_state.routes):
        print(f"  Route {i:2d} [type{best_state.vehicle_ids[i]}]: {route_to_original_ids(problem, route)}")
