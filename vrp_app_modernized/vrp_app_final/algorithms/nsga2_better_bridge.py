from __future__ import annotations

import random
import time
from importlib.machinery import SourceFileLoader
from pathlib import Path
import sys


def _resolve_root_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[2]


ROOT_DIR = _resolve_root_dir()
APP_ALGORITHMS_DIR = ROOT_DIR / "app_algorithms"
NSGA2_BETTER_SOURCE = APP_ALGORITHMS_DIR / "NSGA_2_BETTER"

_NSGA2_BETTER = None


def load_nsga2_better():
    global _NSGA2_BETTER
    if _NSGA2_BETTER is None:
        _NSGA2_BETTER = SourceFileLoader(
            "vrp_app_final_nsga2_better",
            str(NSGA2_BETTER_SOURCE),
        ).load_module()
    return _NSGA2_BETTER


def _route_distance_with_return(route: list[int], dist: list[list[float]]) -> float:
    if not route:
        return 0.0
    total = dist[0][route[0]]
    for index in range(len(route) - 1):
        total += dist[route[index]][route[index + 1]]
    total += dist[route[-1]][0]
    return total


def _route_duration_with_return(route: list[int], time_matrix: list[list[float]]) -> float:
    if not route:
        return 0.0
    total = time_matrix[0][route[0]]
    for index in range(len(route) - 1):
        total += time_matrix[route[index]][route[index + 1]]
    total += time_matrix[route[-1]][0]
    return total


def _configure_module(module, vehicle_capacity: float, fixed_cost: float, cost_per_km: float) -> None:
    module.TAXI_CAPACITY = max(1, int(round(vehicle_capacity)))
    module.FIXED_TAXI_COST = float(fixed_cost)
    module.COST_PER_KM = float(cost_per_km)
    module.route_distance = _route_distance_with_return
    module.route_duration = _route_duration_with_return


def run_nsga2_better(
    distance_matrix: list[list[float]],
    time_matrix: list[list[float]],
    demands: list[float],
    vehicle_capacity: float,
    fixed_cost: float,
    cost_per_km: float,
    pop_size: int,
    generations: int,
    seed: int,
    crossover_rate: float = 0.90,
    base_mutation: float = 0.05,
    boost_mutation: float = 0.60,
    mutation_kind: str = "inversion",
    duplicate_penalty: float = 12.0,
    tournament_k: int = 2,
    callback=None,
    stop_flag: list[bool] | None = None,
) -> list[dict]:
    module = load_nsga2_better()
    _configure_module(
        module,
        vehicle_capacity=vehicle_capacity,
        fixed_cost=fixed_cost,
        cost_per_km=cost_per_km,
    )

    n_customers = len(distance_matrix) - 1
    rng = random.Random(seed)

    population = module.init_population(pop_size, n_customers, seed=seed)
    module.evaluate_population_vrp(population, distance_matrix, time_matrix)
    module.apply_duplicate_penalty(population, penalty_step=duplicate_penalty)

    for generation in range(generations):
        if stop_flag and stop_flag[0]:
            break

        if generation % 5 == 0:
            time.sleep(0.001)

        module.prepare_rank_and_crowding(population)
        mutation_rate = base_mutation
        if population and all(individual.rank == 1 for individual in population):
            mutation_rate = boost_mutation

        mating_rng = random.Random(seed + 2000 + generation)
        mating_pool = [
            module.tournament_pick(population, mating_rng, k=tournament_k)
            for _ in range(pop_size)
        ]
        offspring = module.make_offspring(
            parents=mating_pool,
            rng=rng,
            crossover_rate=crossover_rate,
            mutation_rate=mutation_rate,
            mutation_kind=mutation_kind,
        )
        module.evaluate_population_vrp(offspring, distance_matrix, time_matrix)
        module.apply_duplicate_penalty(offspring, penalty_step=duplicate_penalty)
        population = module.environmental_selection_elitist(population, offspring, pop_size)

        if callback and ((generation + 1) % 5 == 0 or generation + 1 == generations):
            rank1_count = sum(1 for individual in population if individual.rank == 1)
            best_cost = min(
                individual.f1_total_cost
                for individual in population
                if individual.rank == 1
            )
            callback(generation + 1, rank1_count, best_cost)

    module.prepare_rank_and_crowding(population)
    first_front = [individual for individual in population if individual.rank == 1]

    results: list[dict] = []
    seen: set[tuple[tuple[int, ...], ...]] = set()
    for individual in sorted(
        first_front,
        key=lambda item: (
            item.f1_total_cost,
            item.f2_max_route_duration,
            item.f3_avg_route_duration,
        ),
    ):
        routes, total_cost = module.decode_giant_tour_min_cost_dp(
            individual.chromosome,
            distance_matrix,
            capacity=max(1, int(round(vehicle_capacity))),
        )
        key = tuple(tuple(route) for route in routes)
        if key in seen:
            continue
        seen.add(key)

        route_times = [_route_duration_with_return(route, time_matrix) for route in routes]
        route_distances = [_route_distance_with_return(route, distance_matrix) for route in routes]
        route_costs = [
            float(fixed_cost) + float(cost_per_km) * _route_distance_with_return(route, distance_matrix)
            for route in routes
        ]
        max_duration = max(route_times) if route_times else 0.0
        avg_duration = sum(route_times) / len(route_times) if route_times else 0.0
        results.append(
            {
                "cost": total_cost,
                "max_duration": max_duration,
                "avg_duration": avg_duration,
                "routes": routes,
                "route_times": route_times,
                "route_distances": route_distances,
                "route_costs": route_costs,
                "chromosome": individual.chromosome[:],
            }
        )

    return results
