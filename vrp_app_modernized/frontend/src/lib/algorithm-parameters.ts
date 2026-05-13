export type SolverKey = "bloodhound" | "nsga2";

export type Nsga2Params = {
  pop_size: number;
  generations: number;
  seed: number;
  crossover_rate: number;
  base_mutation: number;
  boost_mutation: number;
  mutation_kind: "inversion" | "swap";
  duplicate_penalty: number;
  tournament_k: number;
};

export type BloodhoundParams = {
  num_wolves: number;
  num_hunts: number;
  explore_iterations: number;
  reserve_blood: number;
  lambda_reg: number;
  a: number;
  b: number;
  c: number;
  b_par: number;
  inherit_frac: number;
  ruin_frac: number;
  rr_repeats: number;
  verbose: boolean;
};

export type AlgorithmParameterState = {
  nsga2: Nsga2Params;
  bloodhound: BloodhoundParams;
};

export type ParameterField = {
  key: string;
  label: string;
  description: string;
  type: "integer" | "float" | "boolean" | "select";
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ value: string; label: string }>;
};

export const defaultAlgorithmParameters: AlgorithmParameterState = {
  nsga2: {
    pop_size: 60,
    generations: 500,
    seed: 0,
    crossover_rate: 0.9,
    base_mutation: 0.05,
    boost_mutation: 0.6,
    mutation_kind: "inversion",
    duplicate_penalty: 12,
    tournament_k: 2,
  },
  bloodhound: {
    num_wolves: 12,
    num_hunts: 20,
    explore_iterations: 120,
    reserve_blood: 2,
    lambda_reg: 0.3,
    a: 1.5,
    b: 2,
    c: 1,
    b_par: 1.2,
    inherit_frac: 0.35,
    ruin_frac: 0.2,
    rr_repeats: 2,
    verbose: true,
  },
};

export const parameterFields: Record<SolverKey, ParameterField[]> = {
  bloodhound: [
    { key: "num_wolves", label: "Number of wolves", description: "Population size used during the hunt process.", type: "integer", min: 1, step: 1 },
    { key: "num_hunts", label: "Number of hunts", description: "Main outer-loop hunt count. Setting this to 1 runs exactly one hunt.", type: "integer", min: 1, step: 1 },
    { key: "explore_iterations", label: "Explore iterations", description: "Free-search iterations performed per wolf before alpha hunting.", type: "integer", min: 1, step: 1 },
    { key: "reserve_blood", label: "Reserve blood", description: "Reset intensity applied at the start of each hunt.", type: "float", min: 0, step: 0.1 },
    { key: "lambda_reg", label: "Lambda regularization", description: "Exploration regularization weight used during free search.", type: "float", min: 0, step: 0.01 },
    { key: "a", label: "Parameter a", description: "Exploration/exploitation coefficient from the Bloodhound free-search phase.", type: "float", min: 0.0001, step: 0.1 },
    { key: "b", label: "Parameter b", description: "Exploration/exploitation coefficient from the Bloodhound free-search phase.", type: "float", min: 0.0001, step: 0.1 },
    { key: "c", label: "Parameter c", description: "Exploration/exploitation coefficient from the Bloodhound free-search phase.", type: "float", min: 0.0001, step: 0.1 },
    { key: "b_par", label: "b_par", description: "Auxiliary Bloodhound control parameter passed into free-search behavior.", type: "float", min: 0.0001, step: 0.1 },
    { key: "inherit_frac", label: "Inherit fraction", description: "Fraction of alpha structure inherited during hunt intensification.", type: "float", min: 0, max: 1, step: 0.01 },
    { key: "ruin_frac", label: "Ruin fraction", description: "Fraction of a route destroyed before rebuild in the hunt phase.", type: "float", min: 0, max: 1, step: 0.01 },
    { key: "rr_repeats", label: "Ruin/rebuild repeats", description: "Number of repeated ruin-rebuild attempts per hunt.", type: "integer", min: 1, step: 1 },
    { key: "verbose", label: "Verbose logging", description: "Emit detailed Bloodhound progress logs into the job monitor.", type: "boolean" },
  ],
  nsga2: [
    { key: "pop_size", label: "Population size", description: "Population size used by NSGA-II in every generation.", type: "integer", min: 2, step: 1 },
    { key: "generations", label: "Generations", description: "Total number of generations. Setting this to 2 runs exactly two generations.", type: "integer", min: 1, step: 1 },
    { key: "seed", label: "Random seed", description: "Deterministic seed for initialization, tournament sampling, and mutation.", type: "integer", step: 1 },
    { key: "crossover_rate", label: "Crossover rate", description: "Probability of applying ordered crossover to parent pairs.", type: "float", min: 0, max: 1, step: 0.01 },
    { key: "base_mutation", label: "Base mutation", description: "Default mutation probability used when diversity is healthy.", type: "float", min: 0, max: 1, step: 0.01 },
    { key: "boost_mutation", label: "Boost mutation", description: "Higher mutation probability used when all individuals collapse into rank 1.", type: "float", min: 0, max: 1, step: 0.01 },
    { key: "mutation_kind", label: "Mutation kind", description: "Choose the chromosome mutation operator used by NSGA-II.", type: "select", options: [{ value: "inversion", label: "Inversion" }, { value: "swap", label: "Swap" }] },
    { key: "duplicate_penalty", label: "Duplicate penalty", description: "Penalty step applied to duplicate chromosomes to preserve diversity.", type: "float", min: 0, step: 0.1 },
    { key: "tournament_k", label: "Tournament size", description: "Number of contestants sampled during tournament selection.", type: "integer", min: 2, step: 1 },
  ],
};

export function mergeAlgorithmParameters(settings: Record<string, unknown> | undefined): AlgorithmParameterState {
  const raw = (settings?.algorithm_parameters ?? {}) as Partial<AlgorithmParameterState>;
  return {
    nsga2: { ...defaultAlgorithmParameters.nsga2, ...(raw.nsga2 ?? {}) },
    bloodhound: { ...defaultAlgorithmParameters.bloodhound, ...(raw.bloodhound ?? {}) },
  };
}

export function validateAlgorithmParameters(state: AlgorithmParameterState) {
  const errors: string[] = [];
  for (const solverKey of Object.keys(parameterFields) as SolverKey[]) {
    for (const field of parameterFields[solverKey]) {
      const value = state[solverKey][field.key as keyof typeof state[typeof solverKey]];
      if (field.type === "boolean" || field.type === "select") continue;
      if (typeof value !== "number" || Number.isNaN(value) || !Number.isFinite(value)) {
        errors.push(`${solverLabel(solverKey)}: ${field.label} must be a valid number.`);
        continue;
      }
      if (field.min != null && value < field.min) errors.push(`${solverLabel(solverKey)}: ${field.label} must be at least ${field.min}.`);
      if (field.max != null && value > field.max) errors.push(`${solverLabel(solverKey)}: ${field.label} must be at most ${field.max}.`);
      if (field.type === "integer" && !Number.isInteger(value)) errors.push(`${solverLabel(solverKey)}: ${field.label} must be an integer.`);
    }
  }
  return errors;
}

export function solverLabel(solver: SolverKey) {
  return solver === "nsga2" ? "NSGA-II" : "Bloodhound";
}

