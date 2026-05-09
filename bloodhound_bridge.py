import random

def expand_fleet_units(fleet: list[FleetUnit]) -> list:
    # Existing implementation...

def build_coords(locations: list[LocationRecord]) -> list[tuple[float, float]]:
    # Existing implementation...

def run_bloodhound_with_matrices(
    locations: list[LocationRecord],
    distance_matrix: list[list[float]],
    time_matrix: list[list[float]] | None,
    demands: list[float],
    fleet: list[FleetUnit],
    time_windows: list[tuple[float, float]] | None = None,
    service_times: list[float] | None = None,
    solver_params: dict | None = None,
    progress_callback=None,
):
    # Existing implementation...

def local_search_improvement(route: list[int], distance_matrix: list[list[float]]) -> list[int]:
    n = len(route)
    best_route = route[:]
    best_cost = sum(distance_matrix[route[i]][route[(i + 1) % n]] for i in range(n))

    for i in range(n):
        for j in range(i + 2, n):
            new_route = route[:i] + route[j:i+1][::-1] + route[i+1:j] + route[j+1:]
            new_cost = sum(distance_matrix[new_route[k]][new_route[(k + 1) % n]] for k in range(n))
            if new_cost < best_cost:
                best_route = new_route
                best_cost = new_cost

    return best_route, best_cost

def run_bloodhound_hcvrp(
        problem: HCVRPProblem,
        num_wolves: int = 12, num_hunts: int = 20, explore_iterations: int = 120,
        reserve_blood: float = 2.0, lambda_reg: float = 0.30,
        a: float = 1.5, b: float = 2.0, c: float = 1.0, b_par: float = 1.2,
        inherit_frac: float = 0.35, ruin_frac: float = 0.20, rr_repeats: int = 2,
        verbose: bool = True, random_seed: Optional[int] = None,
        so_cap_penalty_weight: Optional[float] = None,
        so_relax_period: Optional[int] = None,
):
    # Existing implementation...

    for _ in range(explore_iterations):
        # Existing exploration logic...

        for wolf in wolves:
            state = wolf.clone_state(best_state)
            route_idx = random.randint(0, len(state.routes) - 1)
            new_route, new_cost = local_search_improvement(state.routes[route_idx], problem.distance_matrix)
            state.routes[route_idx] = new_route
            state.route_costs[route_idx] = new_cost

        # Existing exploitation logic...
