from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from .algorithms.bloodhound_bridge import run_bloodhound_with_matrices
from .algorithms.nsga2_homogeneous import run_nsga2_homogeneous
from .schemas import ProblemType, SolverKey, SolverResult, VRPProblemData
from .schemas import RouteResult, SolutionResult


ProgressCallback = Callable[[dict], None]


@dataclass(slots=True)
class SolverSupport:
    solver_key: SolverKey
    supports_problem_types: tuple[ProblemType, ...]
    is_multiobjective: bool


class SolverAdapter(ABC):
    support: SolverSupport

    @abstractmethod
    def validate_problem(self, problem: VRPProblemData) -> None:
        """Raise ValueError if the solver cannot run this problem."""

    @abstractmethod
    def solve(
        self,
        problem: VRPProblemData,
        progress_callback: ProgressCallback | None = None,
        stop_flag: list[bool] | None = None,
    ) -> SolverResult:
        """Run the solver and return a UI-friendly result object."""

    @staticmethod
    def _validate_square_matrices(problem: VRPProblemData) -> None:
        n = len(problem.locations)
        if len(problem.distance_matrix) != n or any(len(row) != n for row in problem.distance_matrix):
            raise ValueError("Distance matrix size does not match the number of locations.")
        if len(problem.time_matrix) != n or any(len(row) != n for row in problem.time_matrix):
            raise ValueError("Time matrix size does not match the number of locations.")

    @staticmethod
    def _demands_as_vector(problem: VRPProblemData) -> list[float]:
        demand_by_node = {item.node_id: item.demand for item in problem.demands}
        vector = []
        for location in problem.locations:
            default = 0.0 if location.is_depot else 1.0
            vector.append(demand_by_node.get(location.node_id, default))
        return vector

    @staticmethod
    def _time_windows_as_vector(problem: VRPProblemData) -> list[tuple[float, float]]:
        windows_by_node = {
            item.node_id: (item.start_min, item.end_min)
            for item in problem.time_windows
        }
        return [
            windows_by_node.get(location.node_id, (0.0, float("inf")))
            for location in problem.locations
        ]

    @staticmethod
    def _service_times_as_vector(problem: VRPProblemData) -> list[float]:
        service_by_node = {
            item.node_id: item.duration_min
            for item in problem.service_times
        }
        return [
            service_by_node.get(location.node_id, 0.0)
            for location in problem.locations
        ]

    @staticmethod
    def _index_to_node_id(problem: VRPProblemData) -> list[int]:
        return [location.node_id for location in problem.locations]


class NSGA2Adapter(SolverAdapter):
    support = SolverSupport(
        solver_key=SolverKey.NSGA2,
        supports_problem_types=(ProblemType.HOMOGENEOUS,),
        is_multiobjective=True,
    )

    def validate_problem(self, problem: VRPProblemData) -> None:
        self._validate_square_matrices(problem)
        if problem.infer_problem_type() is not ProblemType.HOMOGENEOUS:
            raise ValueError("NSGA-II can only be used with a homogeneous fleet.")
        if not problem.fleet:
            raise ValueError("Fleet cannot be empty for NSGA-II.")
        if not any(location.is_depot for location in problem.locations):
            raise ValueError("At least one depot must be defined.")

    def solve(
        self,
        problem: VRPProblemData,
        progress_callback: ProgressCallback | None = None,
        stop_flag: list[bool] | None = None,
    ) -> SolverResult:
        self.validate_problem(problem)

        config = problem.solver_config.params if problem.solver_config else {}
        fleet_unit = problem.fleet[0]
        demands = self._demands_as_vector(problem)
        index_to_node = self._index_to_node_id(problem)

        def callback(gen: int, rank1_count: int, best_cost: float) -> None:
            if progress_callback:
                progress_callback(
                    {
                        "phase": "evolution",
                        "generation": gen,
                        "rank1_count": rank1_count,
                        "best_cost": best_cost,
                    }
                )

        raw_results = run_nsga2_homogeneous(
            distance_matrix=problem.distance_matrix,
            time_matrix=problem.time_matrix,
            demands=demands,
            vehicle_capacity=fleet_unit.capacity,
            fixed_cost=fleet_unit.fixed_cost,
            cost_per_km=fleet_unit.cost_per_km,
            pop_size=int(config.get("pop_size", 60)),
            generations=int(config.get("generations", 500)),
            seed=int(config.get("seed", 0)),
            callback=callback,
            stop_flag=stop_flag,
        )

        solutions = []
        for idx, item in enumerate(raw_results, start=1):
            routes = []
            for route, route_time, route_distance, route_cost in zip(
                item["routes"],
                item["route_times"],
                item["route_distances"],
                item["route_costs"],
            ):
                variable_cost = route_cost - fleet_unit.fixed_cost
                routes.append(
                    RouteResult(
                        nodes=[index_to_node[node] for node in route],
                        vehicle_label=fleet_unit.label,
                        vehicle_type_id=fleet_unit.vehicle_type_id,
                        route_distance=route_distance,
                        route_time=route_time,
                        route_cost=route_cost,
                        fixed_cost=fleet_unit.fixed_cost,
                        variable_cost=variable_cost,
                    )
                )

            solutions.append(
                SolutionResult(
                    solution_id=f"nsga2-{idx}",
                    objectives={
                        "total_cost": item["cost"],
                        "max_route_duration": item["max_duration"],
                        "avg_route_duration": item["avg_duration"],
                    },
                    total_cost=item["cost"],
                    routes=routes,
                    raw_payload={"chromosome": item["chromosome"]},
                )
            )

        return SolverResult(
            solver_key=SolverKey.NSGA2,
            problem_type=problem.infer_problem_type(),
            is_multiobjective=True,
            objective_names=[
                "total_cost",
                "max_route_duration",
                "avg_route_duration",
            ],
            solutions=solutions,
            metadata={
                "population_size": int(config.get("pop_size", 60)),
                "generations": int(config.get("generations", 500)),
                "seed": int(config.get("seed", 0)),
            },
        )


class BloodhoundAdapter(SolverAdapter):
    support = SolverSupport(
        solver_key=SolverKey.BLOODHOUND,
        supports_problem_types=(ProblemType.HOMOGENEOUS, ProblemType.HETEROGENEOUS),
        is_multiobjective=False,
    )

    def validate_problem(self, problem: VRPProblemData) -> None:
        self._validate_square_matrices(problem)
        if not problem.fleet:
            raise ValueError("At least one vehicle must be defined for Bloodhound.")
        if not any(location.is_depot for location in problem.locations):
            raise ValueError("At least one depot must be defined.")

    def solve(
        self,
        problem: VRPProblemData,
        progress_callback: ProgressCallback | None = None,
        stop_flag: list[bool] | None = None,
    ) -> SolverResult:
        del stop_flag
        self.validate_problem(problem)

        config = problem.solver_config.params if problem.solver_config else {}
        demands = self._demands_as_vector(problem)
        time_windows = self._time_windows_as_vector(problem)
        service_times = self._service_times_as_vector(problem)
        index_to_node = self._index_to_node_id(problem)

        if progress_callback:
            progress_callback({"phase": "initialization"})

        best_state = run_bloodhound_with_matrices(
            locations=problem.locations,
            distance_matrix=problem.distance_matrix,
            time_matrix=problem.time_matrix,
            demands=demands,
            fleet=problem.fleet,
            time_windows=time_windows,
            service_times=service_times,
            solver_params=config,
        )

        expanded_units = []
        for unit in problem.fleet:
            expanded_units.extend([unit] * unit.count)

        routes = []
        for route, vehicle_id, route_time, route_distance, route_cost in zip(
            best_state.routes,
            best_state.vehicle_ids,
            best_state.route_times,
            best_state.route_distances,
            best_state.route_costs,
        ):
            vehicle = expanded_units[vehicle_id]
            routes.append(
                RouteResult(
                    nodes=[index_to_node[node] for node in route if node != 0],
                    vehicle_label=vehicle.label,
                    vehicle_type_id=vehicle.vehicle_type_id,
                    route_distance=route_distance,
                    route_time=route_time,
                    route_cost=route_cost,
                    fixed_cost=vehicle.fixed_cost,
                    variable_cost=route_cost - vehicle.fixed_cost,
                )
            )

        return SolverResult(
            solver_key=SolverKey.BLOODHOUND,
            problem_type=problem.infer_problem_type(),
            is_multiobjective=False,
            objective_names=["total_cost"],
            solutions=[
                SolutionResult(
                    solution_id="bloodhound-best",
                    objectives={"total_cost": best_state.total_cost},
                    total_cost=best_state.total_cost,
                    routes=routes,
                    feasible=best_state.feasible,
                    raw_payload={
                        "vehicle_ids": best_state.vehicle_ids[:],
                        "route_loads": best_state.route_loads[:],
                    },
                )
            ],
            metadata={
                "num_wolves": int(config.get("num_wolves", 12)),
                "num_hunts": int(config.get("num_hunts", 20)),
                "explore_iterations": int(config.get("explore_iterations", 120)),
            },
            warnings=[] if best_state.feasible else ["Bloodhound returned an infeasible solution."],
        )


def choose_available_solvers(problem: VRPProblemData) -> list[SolverSupport]:
    problem_type = problem.infer_problem_type()
    supports = [NSGA2Adapter.support, BloodhoundAdapter.support]
    return [
        support
        for support in supports
        if problem_type in support.supports_problem_types
    ]


def choose_default_solver(problem: VRPProblemData) -> SolverKey:
    if problem.infer_problem_type() is ProblemType.HETEROGENEOUS:
        return SolverKey.BLOODHOUND
    return SolverKey.NSGA2


def get_solver_adapter(solver_key: SolverKey) -> SolverAdapter:
    if solver_key is SolverKey.NSGA2:
        return NSGA2Adapter()
    if solver_key is SolverKey.BLOODHOUND:
        return BloodhoundAdapter()
    raise ValueError(f"Unsupported solver: {solver_key}")
