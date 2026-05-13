from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Nsga2Params(BaseModel):
    pop_size: int = Field(default=60, ge=2)
    generations: int = Field(default=500, ge=1)
    seed: int = Field(default=0)
    crossover_rate: float = Field(default=0.90, ge=0.0, le=1.0)
    base_mutation: float = Field(default=0.05, ge=0.0, le=1.0)
    boost_mutation: float = Field(default=0.60, ge=0.0, le=1.0)
    mutation_kind: Literal["inversion", "swap"] = "inversion"
    duplicate_penalty: float = Field(default=12.0, ge=0.0)
    tournament_k: int = Field(default=2, ge=2)


class BloodhoundParams(BaseModel):
    num_wolves: int = Field(default=12, ge=1)
    num_hunts: int = Field(default=20, ge=1)
    explore_iterations: int = Field(default=120, ge=1)
    reserve_blood: float = Field(default=2.0, ge=0.0)
    lambda_reg: float = Field(default=0.30, ge=0.0)
    a: float = Field(default=1.5, gt=0.0)
    b: float = Field(default=2.0, gt=0.0)
    c: float = Field(default=1.0, gt=0.0)
    b_par: float = Field(default=1.2, gt=0.0)
    inherit_frac: float = Field(default=0.35, ge=0.0, le=1.0)
    ruin_frac: float = Field(default=0.20, ge=0.0, le=1.0)
    rr_repeats: int = Field(default=2, ge=1)
    verbose: bool = True

