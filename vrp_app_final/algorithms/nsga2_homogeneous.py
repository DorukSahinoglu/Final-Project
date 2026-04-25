from __future__ import annotations

import random
from dataclasses import dataclass, field


Chromosome = list[int]
Route = list[int]
DEPOT = 0


def route_distance(route: Route, dist: list[list[float]]) -> float:
    if not route:
        return 0.0
    total = dist[DEPOT][route[0]]
    for i in range(len(route) - 1):
        total += dist[route[i]][route[i + 1]]
    total += dist[route[-1]][DEPOT]
    return total


def route_duration(route: Route, time_matrix: list[list[float]]) -> float:
    if not route:
        return 0.0
    total = time_matrix[DEPOT][route[0]]
    for i in range(len(route) - 1):
        total += time_matrix[route[i]][route[i + 1]]
    total += time_matrix[route[-1]][DEPOT]
    return total


def route_load(route: Route, demands: list[float]) -> float:
    return sum(demands[node] for node in route)


def random_giant_tour(n_customers: int, rng: random.Random) -> Chromosome:
    tour = list(range(1, n_customers + 1))
    rng.shuffle(tour)
    return tour


@dataclass
class Individual:
    chromosome: Chromosome
    f1_total_cost: float = float("inf")
    f2_max_route_duration: float = float("inf")
    f3_avg_route_duration: float = float("inf")
    rank: int = 10**9
    crowding: float = 0.0
    domination_set: list["Individual"] = field(default_factory=list)
    domination_count: int = 0


def init_population(pop_size: int, n_customers: int, seed: int) -> list[Individual]:
    rng = random.Random(seed)
    return [Individual(random_giant_tour(n_customers, rng)) for _ in range(pop_size)]


def ox_crossover(
    parent_a: Chromosome,
    parent_b: Chromosome,
    rng: random.Random,
) -> tuple[Chromosome, Chromosome]:
    n = len(parent_a)
    a, b = sorted(rng.sample(range(n), 2))

    def make_child(first: Chromosome, second: Chromosome) -> Chromosome:
        child = [-1] * n
        child[a : b + 1] = first[a : b + 1]
        used = set(child[a : b + 1])
        idx = (b + 1) % n
        for gene in second:
            if gene in used:
                continue
            child[idx] = gene
            idx = (idx + 1) % n
        return child

    return make_child(parent_a, parent_b), make_child(parent_b, parent_a)


def swap_mutation(chromosome: Chromosome, rng: random.Random) -> Chromosome:
    i, j = rng.sample(range(len(chromosome)), 2)
    mutated = chromosome[:]
    mutated[i], mutated[j] = mutated[j], mutated[i]
    return mutated


def inversion_mutation(chromosome: Chromosome, rng: random.Random) -> Chromosome:
    i, j = sorted(rng.sample(range(len(chromosome)), 2))
    mutated = chromosome[:]
    mutated[i : j + 1] = reversed(mutated[i : j + 1])
    return mutated


def make_offspring(
    parents: list[Individual],
    rng: random.Random,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.05,
    mutation_kind: str = "inversion",
) -> list[Individual]:
    offspring: list[Individual] = []
    n = len(parents)

    def mutate(chromosome: Chromosome) -> Chromosome:
        if mutation_kind == "swap":
            return swap_mutation(chromosome, rng)
        return inversion_mutation(chromosome, rng)

    i = 0
    while len(offspring) < n:
        parent_1 = parents[i % n].chromosome
        parent_2 = parents[(i + 1) % n].chromosome
        i += 2

        if rng.random() < crossover_rate and len(parent_1) >= 2:
            child_1, child_2 = ox_crossover(parent_1, parent_2, rng)
        else:
            child_1, child_2 = parent_1[:], parent_2[:]

        if len(child_1) >= 2 and rng.random() < mutation_rate:
            child_1 = mutate(child_1)
        if len(child_2) >= 2 and rng.random() < mutation_rate:
            child_2 = mutate(child_2)

        offspring.append(Individual(child_1))
        if len(offspring) < n:
            offspring.append(Individual(child_2))

    return offspring


def dominates(a: Individual, b: Individual) -> bool:
    a_values = (a.f1_total_cost, a.f2_max_route_duration, a.f3_avg_route_duration)
    b_values = (b.f1_total_cost, b.f2_max_route_duration, b.f3_avg_route_duration)
    no_worse_all = True
    better_at_least_one = False

    for av, bv in zip(a_values, b_values):
        if av > bv:
            no_worse_all = False
            break
        if av < bv:
            better_at_least_one = True
    return no_worse_all and better_at_least_one


def fast_non_dominated_sort(population: list[Individual]) -> list[list[Individual]]:
    for individual in population:
        individual.domination_set = []
        individual.domination_count = 0
        individual.rank = 10**9

    fronts: list[list[Individual]] = []
    first_front: list[Individual] = []

    for i, p in enumerate(population):
        for j in range(i + 1, len(population)):
            q = population[j]
            if dominates(p, q):
                p.domination_set.append(q)
                q.domination_count += 1
            elif dominates(q, p):
                q.domination_set.append(p)
                p.domination_count += 1

    for individual in population:
        if individual.domination_count == 0:
            individual.rank = 1
            first_front.append(individual)

    fronts.append(first_front)
    k = 0
    while k < len(fronts) and fronts[k]:
        next_front: list[Individual] = []
        for individual in fronts[k]:
            for dominated in individual.domination_set:
                dominated.domination_count -= 1
                if dominated.domination_count == 0:
                    dominated.rank = k + 2
                    next_front.append(dominated)
        k += 1
        if next_front:
            fronts.append(next_front)

    return fronts


def assign_crowding_distance(front: list[Individual]) -> None:
    if not front:
        return
    for individual in front:
        individual.crowding = 0.0

    if len(front) <= 2:
        for individual in front:
            individual.crowding = float("inf")
        return

    for attr in ("f1_total_cost", "f2_max_route_duration", "f3_avg_route_duration"):
        front.sort(key=lambda individual: getattr(individual, attr))
        front[0].crowding = float("inf")
        front[-1].crowding = float("inf")
        f_min = getattr(front[0], attr)
        f_max = getattr(front[-1], attr)
        denom = f_max - f_min
        if denom <= 1e-12:
            continue
        for i in range(1, len(front) - 1):
            prev_v = getattr(front[i - 1], attr)
            next_v = getattr(front[i + 1], attr)
            front[i].crowding += (next_v - prev_v) / denom


def environmental_selection_elitist(
    parents: list[Individual],
    offspring: list[Individual],
    pop_size: int,
) -> list[Individual]:
    combined = parents + offspring
    fronts = fast_non_dominated_sort(combined)
    next_population: list[Individual] = []

    for front in fronts:
        assign_crowding_distance(front)
        if len(next_population) + len(front) <= pop_size:
            next_population.extend(front)
            continue

        remaining = pop_size - len(next_population)
        front.sort(key=lambda individual: individual.crowding, reverse=True)
        next_population.extend(front[:remaining])
        break

    return next_population


def tournament_pick(population: list[Individual], rng: random.Random, k: int = 2) -> Individual:
    contestants = rng.sample(population, k)
    best = contestants[0]
    for contestant in contestants[1:]:
        if contestant.rank < best.rank:
            best = contestant
        elif contestant.rank == best.rank and contestant.crowding > best.crowding:
            best = contestant
    return best


def build_mating_pool(population: list[Individual], pool_size: int, seed: int) -> list[Individual]:
    rng = random.Random(seed)
    return [tournament_pick(population, rng, k=2) for _ in range(pool_size)]


def apply_duplicate_penalty(population: list[Individual], penalty_step: float = 10.0) -> None:
    buckets: dict[tuple[int, ...], list[Individual]] = {}
    for individual in population:
        key = tuple(individual.chromosome)
        buckets.setdefault(key, []).append(individual)

    for duplicates in buckets.values():
        if len(duplicates) <= 1:
            continue
        for offset, individual in enumerate(duplicates[1:], start=1):
            individual.f1_total_cost += offset * penalty_step


def prepare_rank_and_crowding(population: list[Individual]) -> None:
    for front in fast_non_dominated_sort(population):
        assign_crowding_distance(front)


def segment_route_cost(
    route: Route,
    dist: list[list[float]],
    fixed_cost: float,
    cost_per_km: float,
) -> float:
    return fixed_cost + cost_per_km * route_distance(route, dist)


def decode_giant_tour_min_cost_dp(
    chromosome: Chromosome,
    dist: list[list[float]],
    demands: list[float],
    vehicle_capacity: float,
    fixed_cost: float,
    cost_per_km: float,
) -> tuple[list[Route], float]:
    n = len(chromosome)
    inf = 1e30
    dp = [inf] * (n + 1)
    prev = [-1] * (n + 1)
    dp[0] = 0.0

    for i in range(n):
        if dp[i] >= inf:
            continue

        load = 0.0
        for j in range(i + 1, n + 1):
            load += demands[chromosome[j - 1]]
            if load > vehicle_capacity:
                break

            route = chromosome[i:j]
            candidate_cost = segment_route_cost(route, dist, fixed_cost, cost_per_km)
            if dp[i] + candidate_cost < dp[j]:
                dp[j] = dp[i] + candidate_cost
                prev[j] = i

    if prev[n] == -1 and n > 0:
        raise RuntimeError("Decode failed. No feasible split found for homogeneous NSGA-II.")

    routes: list[Route] = []
    current = n
    while current > 0:
        i = prev[current]
        if i < 0:
            raise RuntimeError("Backtracking failed in decode.")
        routes.append(chromosome[i:current])
        current = i
    routes.reverse()
    return routes, dp[n]


def evaluate_individual_vrp(
    individual: Individual,
    dist: list[list[float]],
    time_matrix: list[list[float]],
    demands: list[float],
    vehicle_capacity: float,
    fixed_cost: float,
    cost_per_km: float,
) -> None:
    routes, total_cost = decode_giant_tour_min_cost_dp(
        individual.chromosome,
        dist,
        demands,
        vehicle_capacity,
        fixed_cost,
        cost_per_km,
    )
    durations = [route_duration(route, time_matrix) for route in routes]
    max_duration = max(durations) if durations else 0.0
    avg_duration = sum(durations) / len(durations) if durations else 0.0
    individual.f1_total_cost = total_cost
    individual.f2_max_route_duration = max_duration
    individual.f3_avg_route_duration = avg_duration


def evaluate_population_vrp(
    population: list[Individual],
    dist: list[list[float]],
    time_matrix: list[list[float]],
    demands: list[float],
    vehicle_capacity: float,
    fixed_cost: float,
    cost_per_km: float,
) -> None:
    for individual in population:
        evaluate_individual_vrp(
            individual,
            dist,
            time_matrix,
            demands,
            vehicle_capacity,
            fixed_cost,
            cost_per_km,
        )


def run_nsga2_homogeneous(
    distance_matrix: list[list[float]],
    time_matrix: list[list[float]],
    demands: list[float],
    vehicle_capacity: float,
    fixed_cost: float,
    cost_per_km: float,
    pop_size: int,
    generations: int,
    seed: int,
    callback=None,
    stop_flag: list[bool] | None = None,
) -> list[dict]:
    n_customers = len(distance_matrix) - 1
    rng = random.Random(seed)

    population = init_population(pop_size, n_customers, seed=seed)
    evaluate_population_vrp(
        population,
        distance_matrix,
        time_matrix,
        demands,
        vehicle_capacity,
        fixed_cost,
        cost_per_km,
    )
    apply_duplicate_penalty(population, penalty_step=12.0)

    base_mutation = 0.05
    boost_mutation = 0.60

    for generation in range(generations):
        if stop_flag and stop_flag[0]:
            break

        prepare_rank_and_crowding(population)
        mutation_rate = base_mutation
        if all(individual.rank == 1 for individual in population):
            mutation_rate = boost_mutation

        mating_pool = build_mating_pool(
            population,
            pool_size=pop_size,
            seed=seed + 2000 + generation,
        )
        offspring = make_offspring(
            parents=mating_pool,
            rng=rng,
            crossover_rate=0.90,
            mutation_rate=mutation_rate,
            mutation_kind="inversion",
        )
        evaluate_population_vrp(
            offspring,
            distance_matrix,
            time_matrix,
            demands,
            vehicle_capacity,
            fixed_cost,
            cost_per_km,
        )
        apply_duplicate_penalty(offspring, penalty_step=12.0)
        population = environmental_selection_elitist(population, offspring, pop_size)

        if callback:
            rank1_count = sum(1 for individual in population if individual.rank == 1)
            best_cost = min(
                individual.f1_total_cost
                for individual in population
                if individual.rank == 1
            )
            callback(generation + 1, rank1_count, best_cost)

    prepare_rank_and_crowding(population)
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
        routes, total_cost = decode_giant_tour_min_cost_dp(
            individual.chromosome,
            distance_matrix,
            demands,
            vehicle_capacity,
            fixed_cost,
            cost_per_km,
        )
        key = tuple(tuple(route) for route in routes)
        if key in seen:
            continue
        seen.add(key)

        route_times = [route_duration(route, time_matrix) for route in routes]
        route_distances = [route_distance(route, distance_matrix) for route in routes]
        route_costs = [
            segment_route_cost(route, distance_matrix, fixed_cost, cost_per_km)
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
