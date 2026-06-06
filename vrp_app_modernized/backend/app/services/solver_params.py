from __future__ import annotations

from app.schemas.solver_params import BloodhoundParams, Nsga2Params


def normalize_solver_params(solver_key: str, solver_params: dict | None) -> dict:
    params = dict(solver_params or {})
    if solver_key == "nsga2":
        return Nsga2Params.model_validate(params).model_dump()
    if solver_key == "bloodhound":
        if "max_hunts" in params and "num_hunts" not in params:
            params["num_hunts"] = params.pop("max_hunts")
        if "pack_size" in params and "num_wolves" not in params:
            params["num_wolves"] = params.pop("pack_size")
        params.pop("max_hunts", None)
        params.pop("pack_size", None)
        return BloodhoundParams.model_validate(params).model_dump()
    raise ValueError(f"Unsupported solver: {solver_key}")

