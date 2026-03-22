import random
import math
from typing import List, Tuple

Chromosome = List[int]
Route = List[int]

DEPOT = 0
TAXI_CAPACITY = 4
FIXED_TAXI_COST = 45
COST_PER_KM = 32


def route_distance(route: Route, dist: List[List[float]]) -> float:
    if not route:
        return 0.0
    total = dist[DEPOT][route[0]]
    for i in range(len(route) - 1):
        total += dist[route[i]][route[i + 1]]
    return total


def route_duration(route: Route, time: List[List[float]]) -> float:
    if not route:
        return 0.0
    total = time[DEPOT][route[0]]
    for i in range(len(route) - 1):
        total += time[route[i]][route[i + 1]]
    return total


def random_giant_tour(n_customers: int, rng: random.Random) -> Chromosome:
    tour = list(range(1, n_customers + 1))
    rng.shuffle(tour)
    return tour


class Individual:
    def __init__(self, chromosome: Chromosome):
        self.chromosome = chromosome[:]
        self.f1_total_cost: float = float("inf")
        self.f2_max_route_duration: float = float("inf")
        self.f3_avg_route_duration: float = float("inf")
        self.rank: int = 10**9
        self.crowding: float = 0.0
        self.domination_set: List["Individual"] = []
        self.domination_count: int = 0


def init_population(pop_size: int, n_customers: int, seed: int = 46) -> List[Individual]:
    rng = random.Random(seed)
    pop: List[Individual] = []
    for _ in range(pop_size):
        chrom = random_giant_tour(n_customers, rng)
        pop.append(Individual(chrom))
    return pop


def ox_crossover(p1: Chromosome, p2: Chromosome, rng: random.Random) -> Tuple[Chromosome, Chromosome]:
    n = len(p1)
    a, b = sorted(rng.sample(range(n), 2))

    def make_child(parent_a, parent_b):
        child = [-1] * n
        child[a:b + 1] = parent_a[a:b + 1]
        used = set(child[a:b + 1])
        idx = (b + 1) % n
        for gene in parent_b:
            if gene in used:
                continue
            child[idx] = gene
            idx = (idx + 1) % n
        return child

    return make_child(p1, p2), make_child(p2, p1)


def swap_mutation(ch: Chromosome, rng: random.Random) -> Chromosome:
    n = len(ch)
    i, j = rng.sample(range(n), 2)
    out = ch[:]
    out[i], out[j] = out[j], out[i]
    return out


def inversion_mutation(ch: Chromosome, rng: random.Random) -> Chromosome:
    n = len(ch)
    i, j = sorted(rng.sample(range(n), 2))
    out = ch[:]
    out[i:j + 1] = reversed(out[i:j + 1])
    return out


def make_offspring(parents, rng, crossover_rate=0.9, mutation_rate=0.02, mutation_kind="swap"):
    offspring = []
    n = len(parents)

    def mutate(ch):
        if mutation_kind == "inversion":
            return inversion_mutation(ch, rng)
        return swap_mutation(ch, rng)

    i = 0
    while len(offspring) < n:
        p1 = parents[i % n].chromosome
        p2 = parents[(i + 1) % n].chromosome
        i += 2
        if rng.random() < crossover_rate:
            c1, c2 = ox_crossover(p1, p2, rng)
        else:
            c1, c2 = p1[:], p2[:]
        if rng.random() < mutation_rate:
            c1 = mutate(c1)
        if rng.random() < mutation_rate:
            c2 = mutate(c2)
        offspring.append(Individual(c1))
        if len(offspring) < n:
            offspring.append(Individual(c2))
    return offspring


def dominates(a, b) -> bool:
    a_vals = (a.f1_total_cost, a.f2_max_route_duration, a.f3_avg_route_duration)
    b_vals = (b.f1_total_cost, b.f2_max_route_duration, b.f3_avg_route_duration)
    no_worse_all = True
    better_at_least_one = False
    for av, bv in zip(a_vals, b_vals):
        if av > bv:
            no_worse_all = False
            break
        if av < bv:
            better_at_least_one = True
    return no_worse_all and better_at_least_one


def fast_non_dominated_sort(population):
    for p in population:
        p.domination_set = []
        p.domination_count = 0
        p.rank = 10**9

    fronts = []
    F1 = []

    for i, p in enumerate(population):
        for j in range(i + 1, len(population)):
            q = population[j]
            if dominates(p, q):
                p.domination_set.append(q)
                q.domination_count += 1
            elif dominates(q, p):
                q.domination_set.append(p)
                p.domination_count += 1

    for p in population:
        if p.domination_count == 0:
            p.rank = 1
            F1.append(p)

    fronts.append(F1)
    k = 0
    while k < len(fronts) and fronts[k]:
        next_front = []
        for p in fronts[k]:
            for q in p.domination_set:
                q.domination_count -= 1
                if q.domination_count == 0:
                    q.rank = k + 2
                    next_front.append(q)
        k += 1
        if next_front:
            fronts.append(next_front)

    return fronts


def assign_crowding_distance(front):
    if not front:
        return
    for ind in front:
        ind.crowding = 0.0

    objectives = [("f1_total_cost",), ("f2_max_route_duration",), ("f3_avg_route_duration",)]
    n = len(front)
    if n <= 2:
        for ind in front:
            ind.crowding = float("inf")
        return

    for (attr,) in objectives:
        front.sort(key=lambda x: getattr(x, attr))
        front[0].crowding = float("inf")
        front[-1].crowding = float("inf")
        f_min = getattr(front[0], attr)
        f_max = getattr(front[-1], attr)
        denom = f_max - f_min
        if denom <= 1e-12:
            continue
        for i in range(1, n - 1):
            prev_v = getattr(front[i - 1], attr)
            next_v = getattr(front[i + 1], attr)
            front[i].crowding += (next_v - prev_v) / denom


def environmental_selection_elitist(parents, offspring, pop_size):
    R = parents + offspring
    fronts = fast_non_dominated_sort(R)
    next_pop = []
    for front in fronts:
        assign_crowding_distance(front)
        if len(next_pop) + len(front) <= pop_size:
            next_pop.extend(front)
        else:
            remaining = pop_size - len(next_pop)
            front.sort(key=lambda x: x.crowding, reverse=True)
            next_pop.extend(front[:remaining])
            break
    return next_pop


def tournament_pick(population, rng, k=2):
    contestants = rng.sample(population, k)
    best = contestants[0]
    for c in contestants[1:]:
        if c.rank < best.rank:
            best = c
        elif c.rank == best.rank and c.crowding > best.crowding:
            best = c
    return best


def build_mating_pool(population, pool_size, seed=123):
    rng = random.Random(seed)
    mating_pool = []
    for _ in range(pool_size):
        mating_pool.append(tournament_pick(population, rng, k=2))
    return mating_pool


def apply_duplicate_penalty(pop, penalty_step=10.0):
    buckets = {}
    for ind in pop:
        key = tuple(ind.chromosome)
        buckets.setdefault(key, []).append(ind)
    for key, inds in buckets.items():
        if len(inds) <= 1:
            continue
        for k, ind in enumerate(inds):
            if k == 0:
                continue
            ind.f1_total_cost += k * penalty_step


def prepare_rank_and_crowding(population):
    fronts = fast_non_dominated_sort(population)
    for front in fronts:
        assign_crowding_distance(front)


def segment_route_cost(route, dist):
    return FIXED_TAXI_COST + COST_PER_KM * route_distance(route, dist)


def decode_giant_tour_min_cost_dp(chromosome, dist, capacity=TAXI_CAPACITY):
    n = len(chromosome)
    INF = 1e30
    dp = [INF] * (n + 1)
    prev = [-1] * (n + 1)
    dp[0] = 0.0

    for i in range(n):
        if dp[i] >= INF:
            continue
        for L in range(1, capacity + 1):
            j = i + L
            if j > n:
                break
            route = chromosome[i:j]
            c = segment_route_cost(route, dist)
            if dp[i] + c < dp[j]:
                dp[j] = dp[i] + c
                prev[j] = i

    if prev[n] == -1 and n > 0:
        raise RuntimeError("Decode failed.")

    routes = []
    cur = n
    while cur > 0:
        i = prev[cur]
        routes.append(chromosome[i:cur])
        cur = i
    routes.reverse()
    return routes, dp[n]


def evaluate_individual_vrp(ind, dist, time):
    routes, total_cost = decode_giant_tour_min_cost_dp(ind.chromosome, dist, capacity=TAXI_CAPACITY)
    durations = [route_duration(r, time) for r in routes]
    max_dur = max(durations) if durations else 0.0
    avg_dur = sum(durations) / len(durations) if durations else 0.0
    ind.f1_total_cost = total_cost
    ind.f2_max_route_duration = max_dur
    ind.f3_avg_route_duration = avg_dur


def evaluate_population_vrp(pop, dist, time):
    for ind in pop:
        evaluate_individual_vrp(ind, dist, time)


def run_nsga2(distance_matrix, time_matrix, pop_size, generations, seed,
              callback=None, stop_flag=None):
    """
    Main NSGA-II runner.
    callback(gen, rank1_count, best_cost): called every generation for progress updates.
    stop_flag: a list with one bool element [False]; set to [True] to stop early.
    Returns list of rank-1 solutions.
    """
    n_customers = len(distance_matrix) - 1
    rng = random.Random(seed)

    P = init_population(pop_size, n_customers, seed=seed)
    evaluate_population_vrp(P, distance_matrix, time_matrix)
    apply_duplicate_penalty(P, penalty_step=12.0)

    BASE_MUT = 0.05
    BOOST_MUT = 0.60

    for gen in range(generations):
        if stop_flag and stop_flag[0]:
            break

        prepare_rank_and_crowding(P)

        mut_rate = BASE_MUT
        if all(ind.rank == 1 for ind in P):
            mut_rate = BOOST_MUT

        mating_pool = build_mating_pool(P, pool_size=pop_size, seed=seed + 2000 + gen)
        Q = make_offspring(
            parents=mating_pool,
            rng=rng,
            crossover_rate=0.90,
            mutation_rate=mut_rate,
            mutation_kind="inversion"
        )

        evaluate_population_vrp(Q, distance_matrix, time_matrix)
        apply_duplicate_penalty(Q, penalty_step=12.0)
        P = environmental_selection_elitist(P, Q, pop_size)

        if callback:
            rank1_count = sum(1 for x in P if x.rank == 1)
            best_cost = min(x.f1_total_cost for x in P if x.rank == 1) if rank1_count > 0 else float("inf")
            callback(gen + 1, rank1_count, best_cost)

    prepare_rank_and_crowding(P)
    f1 = [x for x in P if x.rank == 1]

    results = []
    seen = set()
    for ind in sorted(f1, key=lambda z: (z.f1_total_cost, z.f2_max_route_duration, z.f3_avg_route_duration)):
        routes, total_cost = decode_giant_tour_min_cost_dp(ind.chromosome, distance_matrix, capacity=TAXI_CAPACITY)
        key = tuple(tuple(r) for r in routes)
        if key in seen:
            continue
        seen.add(key)
        durations = [route_duration(r, time_matrix) for r in routes]
        max_dur = max(durations) if durations else 0.0
        avg_dur = sum(durations) / len(durations) if durations else 0.0
        results.append({
            "cost": total_cost,
            "max_duration": max_dur,
            "avg_duration": avg_dur,
            "routes": routes,
            "durations": durations,
            "chromosome": ind.chromosome,
        })

    return results
