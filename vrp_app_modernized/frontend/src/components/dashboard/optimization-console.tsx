import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Ban, Download, GitCompareArrows, LayoutGrid, ListTree, LoaderCircle, Lock, Play, RefreshCcw, ScrollText, Settings2, TableProperties, X } from "lucide-react";
import { api } from "@/lib/api";
import {
  mergeAlgorithmParameters,
  solverLabel,
  validateAlgorithmParameters,
  type AlgorithmParameterState,
} from "@/lib/algorithm-parameters";
import { browserFileSystemAdapter } from "@/lib/filesystem";
import { detectFleetType, getDepot, projectValidation } from "@/lib/vrp";
import { useJobPolling } from "@/hooks/use-job-polling";
import type { CandidateSolution, JobResponse, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { AlgorithmParametersModal } from "@/components/dashboard/algorithm-parameters-modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type Props = {
  project: ProjectRecord | null;
  setProject: (project: ProjectRecord) => void;
  matrix: MatrixResponse | null;
  currentJobId: string | null;
  setCurrentJobId: (jobId: string | null) => void;
  currentSolution: SolutionResponse | null;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

type ResultTab = "overview" | "routes" | "inputs" | "logs" | "comparison";

const routePalette = ["#57e6ff", "#91f7c4", "#f7cf7e", "#f48fb1", "#a5b4fc", "#f9a8d4"];

export function OptimizationConsole({
  project,
  setProject,
  matrix,
  currentJobId,
  setCurrentJobId,
  currentSolution,
  setCurrentSolution,
  onToast,
}: Props) {
  const [solver, setSolver] = useState<"nsga2" | "bloodhound">("bloodhound");
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRoute, setExpandedRoute] = useState<number | null>(0);
  const [parametersOpen, setParametersOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [resultTab, setResultTab] = useState<ResultTab>("overview");
  const [selectedSolutionIndex, setSelectedSolutionIndex] = useState(0);
  const { job, error: jobError } = useJobPolling(currentJobId);
  const [parameterDraft, setParameterDraft] = useState<AlgorithmParameterState>(() => mergeAlgorithmParameters(project?.settings));
  const [selectedCustomerIds, setSelectedCustomerIds] = useState<string[]>(() => getInitialSelectedCustomerIds(project));

  const fleetType = useMemo(() => detectFleetType(project?.fleet_units ?? []), [project?.fleet_units]);
  const validation = useMemo(() => projectValidation(project, matrix), [project, matrix]);
  const depot = useMemo(() => getDepot(project), [project]);
  const solverLocked = solver === "nsga2" && fleetType === "heterogeneous";
  const algorithmParameters = parameterDraft;
  const parameterErrors = useMemo(() => validateAlgorithmParameters(algorithmParameters), [algorithmParameters]);
  const matrixSourceLabel = matrix ? toMatrixSourceLabel(matrix.provider) : "Missing";
  const customers = useMemo(() => (project?.addresses ?? []).filter((item) => !item.is_depot), [project?.addresses]);
  const selectedCustomers = useMemo(
    () => customers.filter((item) => selectedCustomerIds.includes(item.id)),
    [customers, selectedCustomerIds],
  );

  const solutionVariants = useMemo<CandidateSolution[]>(() => {
    if (!currentSolution) return [];
    if (currentSolution.candidate_solutions.length > 0) {
      return currentSolution.candidate_solutions;
    }
    return [
      {
        solution_id: String(currentSolution.summary.solution_id ?? currentSolution.id),
        summary: currentSolution.summary,
        routes: currentSolution.routes,
        analytics: currentSolution.analytics,
        raw_payload: currentSolution.raw_payload,
      },
    ];
  }, [currentSolution]);
  const selectedSolution = solutionVariants[selectedSolutionIndex] ?? solutionVariants[0] ?? null;
  const paretoData = useMemo(
    () =>
      solutionVariants.map((item, index) => ({
        index: index + 1,
        cost: numeric(getObjectiveValue(item.summary, "total_cost") ?? item.analytics.total_cost),
        maxDuration: numeric(getObjectiveValue(item.summary, "max_route_duration") ?? item.analytics.total_time),
        avgDuration: numeric(getObjectiveValue(item.summary, "avg_route_duration") ?? 0),
      })),
    [solutionVariants],
  );

  useEffect(() => {
    if (fleetType === "heterogeneous" && solver === "nsga2") {
      setSolver("bloodhound");
    }
  }, [fleetType, solver]);

  useEffect(() => {
    if (!project) return;
    if (project.settings.selected_solver === solver) return;
    setProject({
      ...project,
      settings: {
        ...project.settings,
        selected_solver: solver,
      },
    });
  }, [project, setProject, solver]);

  useEffect(() => {
    if (!job?.solution_id) return;
    api
      .getSolution(job.solution_id)
      .then((solution) => {
        setCurrentSolution(solution);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load solution.");
      });
  }, [job?.solution_id, setCurrentSolution]);

  useEffect(() => {
    if (!job) return;
    if (job.status === "completed") {
      setCancelling(false);
      onToast("Optimization complete", `${job.solver_key} finished successfully.`);
    }
    if (job.status === "failed") {
      setCancelling(false);
      const backendMessage =
        typeof job.error?.message === "string" && job.error.message.trim().length > 0
          ? job.error.message
          : "Inspect the backend error and solver logs in this workspace.";
      onToast("Optimization failed", backendMessage);
    }
    if (job.status === "cancelled") {
      setCancelling(false);
      onToast("Optimization cancelled", typeof job.error?.message === "string" && job.error.message ? job.error.message : "The solver job was cancelled.");
      setCurrentJobId(null);
    }
  }, [job, onToast]);

  useEffect(() => {
    setSelectedSolutionIndex(0);
    setExpandedRoute(0);
  }, [currentSolution?.id]);

  useEffect(() => {
    setParameterDraft(mergeAlgorithmParameters(project?.settings));
  }, [project?.id, project?.settings]);

  useEffect(() => {
    setSelectedCustomerIds((current) => {
      const next = getInitialSelectedCustomerIds(project);
      if (current.length === 0) return next;
      const validIds = new Set(customers.map((item) => item.id));
      const filtered = current.filter((item) => validIds.has(item));
      return filtered.length > 0 ? filtered : next;
    });
  }, [project?.id, customers]);

  useEffect(() => {
    if (!project) return;
    const savedIds = ((project.settings.selected_customer_ids as string[] | undefined) ?? []).filter((item) =>
      customers.some((customer) => customer.id === item),
    );
    const normalizedCurrent = [...selectedCustomerIds].sort().join("|");
    const normalizedSaved = [...savedIds].sort().join("|");
    if (normalizedCurrent === normalizedSaved) return;
    setProject({
      ...project,
      settings: {
        ...project.settings,
        selected_customer_ids: selectedCustomerIds,
      },
    });
  }, [customers, project, selectedCustomerIds, setProject]);

  const inputReview = useMemo(() => {
    const warnings = [...validation.warnings];
    const errors = [...validation.errors];

    if (solver === "nsga2") {
      warnings.push("NSGA-II solves the homogeneous VRP mode with unit customer demand. Vehicle count is automatically handled automatically by the algorithm.");
      if (fleetType === "heterogeneous") {
        errors.push("NSGA-II is disabled because the saved fleet is heterogeneous.");
      }
    } else {
      warnings.push("Bloodhound uses the real customer demands and saved fleet definitions exactly as configured.");
    }

    if (!matrix) {
      errors.push("Generate a matrix before starting optimization.");
    }
    if (selectedCustomers.length === 0) {
      errors.push("Select at least one customer before running optimization.");
    }
    errors.push(...parameterErrors);

    return {
      warnings,
      errors,
      completeness: Math.max(0, validation.completeness - (errors.length ? 20 : 0)),
    };
  }, [fleetType, matrix, parameterErrors, selectedCustomers.length, solver, validation.completeness, validation.errors, validation.warnings]);

  const saveAlgorithmParameters = async (nextParameters: AlgorithmParameterState) => {
    if (!project) {
      throw new Error("Create and save a project before storing algorithm parameters.");
    }
    const nextSettings = {
      ...project.settings,
      algorithm_parameters: nextParameters,
    };
    const saved = await api.updateProject(project.id, {
      name: project.name,
      description: project.description ?? undefined,
      settings: nextSettings,
      addresses: project.addresses.map((item) => ({
        id: item.id,
        label: item.label,
        address_line: item.address_line,
        demand: item.demand,
        is_depot: item.is_depot,
        latitude: item.latitude ?? null,
        longitude: item.longitude ?? null,
        time_window_start_min: item.time_window_start_min ?? null,
        time_window_end_min: item.time_window_end_min ?? null,
        notes: item.notes ?? null,
      })),
      fleet_units: project.fleet_units.map((item) => ({
        id: item.id,
        vehicle_type_id: item.vehicle_type_id,
        label: item.label,
        count: item.count,
        capacity: item.capacity,
        fixed_cost: item.fixed_cost,
        cost_per_km: item.cost_per_km,
        speed_kmh: item.speed_kmh,
      })),
    });
    setProject(saved);
    setParameterDraft(mergeAlgorithmParameters(saved.settings));
    onToast("Parameters saved", "Algorithm parameters were saved into the current project settings.");
  };

  const updateAlgorithmParametersLocally = (nextParameters: AlgorithmParameterState) => {
    setParameterDraft(nextParameters);
    if (!project) return;
    setProject({
      ...project,
      settings: {
        ...project.settings,
        algorithm_parameters: nextParameters,
      },
    });
  };

  const runSolver = async () => {
    if (!project || !matrix || inputReview.errors.length > 0) return;
    try {
      setBusy(true);
      setError(null);
      setCurrentSolution(null);
      console.info("[optimization] queue solver request", {
        solver,
        projectId: project.id,
        matrixId: matrix.id,
        selectedCustomerIds,
        params: solver === "nsga2" ? algorithmParameters.nsga2 : algorithmParameters.bloodhound,
      });
      const payload =
        solver === "nsga2"
          ? await api.solveNsga2({ project_id: project.id, matrix_id: matrix.id, solver_params: algorithmParameters.nsga2, selected_address_ids: selectedCustomerIds })
          : await api.solveBloodhound({ project_id: project.id, matrix_id: matrix.id, solver_params: algorithmParameters.bloodhound, selected_address_ids: selectedCustomerIds });
      setCurrentJobId(payload.job_id);
      onToast("Job queued", `${solver} job accepted by backend.`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start optimization.";
      console.error("[optimization] failed to queue solver", { solver, error: err });
      setError(message);
      onToast("Optimization request failed", message);
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async () => {
    if (!currentJobId || cancelling) return;
    try {
      setCancelling(true);
      setError(null);
      await api.cancelJob(currentJobId);
      onToast("Cancellation requested", "Backend job marked for cancellation. Waiting for the solver to stop safely.");
    } catch (err) {
      setCancelling(false);
      const message = err instanceof Error ? err.message : "Cancellation failed.";
      console.error("[optimization] cancel failed", { currentJobId, error: err });
      setError(message);
      onToast("Cancellation failed", message);
    }
  };

  const activeJob: JobResponse | null = job;

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-lg font-semibold text-white">Algorithm input review</div>
              <div className="mt-1 break-words text-sm text-slate-400">Check solver rules, completeness and fleet compatibility before the backend job is queued.</div>
            </div>
            <Badge className="max-w-full border-white/10 bg-white/[0.04] text-slate-300">{inputReview.completeness}% ready</Badge>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <SolverCard
              active={solver === "bloodhound"}
              title="Bloodhound"
              description="Uses saved demand and fleet exactly as modeled."
              onClick={() => setSolver("bloodhound")}
            />
            <SolverCard
              active={solver === "nsga2"}
              title="NSGA-II"
              description="Homogeneous-only mode with unit demand and automatic vehicle count."
              locked={fleetType === "heterogeneous"}
              onClick={() => fleetType === "homogeneous" && setSolver("nsga2")}
            />
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Metric
              title="Parameter set"
              value={solverLabel(solver)}
              detail={
                solver === "nsga2"
                  ? `${algorithmParameters.nsga2.pop_size} pop / ${algorithmParameters.nsga2.generations} gen`
                  : `${algorithmParameters.bloodhound.num_wolves} wolves / ${algorithmParameters.bloodhound.num_hunts} hunts`
              }
            />
            <Metric title="Fleet mode" value={fleetType} detail="Auto-detected from saved vehicle definitions" />
          </div>

          {(error || jobError) && (
            <div className="mt-4 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
              {error ?? jobError}
            </div>
          )}

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Metric title="Problem type" value={fleetType} detail={solver === "bloodhound" ? "Demand + fleet aware" : "Unit-demand mode"} />
            <Metric title="Customers" value={String(project?.addresses.filter((item) => !item.is_depot).length ?? 0)} detail={depot ? `Depot: ${depot.label}` : "Depot missing"} />
            <Metric title="Matrix" value={matrix ? "Ready" : "Missing"} detail={matrix ? `${matrixSourceLabel} ${matrix.size}x${matrix.size}` : "Generate in matrix workspace"} />
          </div>

          <div className="mt-5 rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-white">Customer subset solving</div>
                <div className="mt-1 break-words text-sm text-slate-400">
                  Depot is always included. Solvers will run on a submatrix built from the selected customers in current address order.
                </div>
              </div>
              <Badge className="border-white/10 bg-white/[0.04] text-slate-300">
                {selectedCustomers.length} / {customers.length} customers selected
              </Badge>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="secondary" className="px-3 py-2 text-xs" onClick={() => setSelectedCustomerIds(customers.map((item) => item.id))}>
                Select all
              </Button>
              <Button variant="secondary" className="px-3 py-2 text-xs" onClick={() => setSelectedCustomerIds([])}>
                Deselect all
              </Button>
              <Button
                variant="secondary"
                className="px-3 py-2 text-xs"
                onClick={() =>
                  setSelectedCustomerIds(
                    customers.filter((item) => !selectedCustomerIds.includes(item.id)).map((item) => item.id),
                  )
                }
              >
                Invert selection
              </Button>
            </div>
            <div className="mt-4 grid gap-2 md:grid-cols-2">
              <label className="flex items-center gap-3 rounded-2xl border border-accent/20 bg-accent/10 px-4 py-3 text-sm text-white">
                <input type="checkbox" checked disabled className="accent-cyan-400" />
                <span className="min-w-0 break-words">{depot?.label ?? "Depot"}</span>
              </label>
              {customers.map((customer) => (
                <label key={customer.id} className="flex items-center gap-3 rounded-2xl border border-white/10 bg-[#09101c] px-4 py-3 text-sm text-slate-200">
                  <input
                    type="checkbox"
                    checked={selectedCustomerIds.includes(customer.id)}
                    onChange={() =>
                      setSelectedCustomerIds((items) =>
                        items.includes(customer.id) ? items.filter((item) => item !== customer.id) : [...items, customer.id],
                      )
                    }
                    className="accent-cyan-400"
                  />
                  <span className="min-w-0 break-words">{customer.label}</span>
                </label>
              ))}
            </div>
          </div>

          {matrix && (
            <div className="mt-4 rounded-[22px] border border-accent/20 bg-accent/10 px-4 py-3 text-sm text-slate-200">
              Solvers are using the active matrix snapshot from <span className="font-medium text-white">{matrixSourceLabel}</span>.
            </div>
          )}

          <ReviewLists warnings={inputReview.warnings} errors={inputReview.errors} />

          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={() => setParametersOpen(true)} variant="secondary" className="gap-2">
              <Settings2 size={16} />
              Algorithm Parameters
            </Button>
            <Button onClick={runSolver} disabled={!project || !matrix || busy || solverLocked || inputReview.errors.length > 0} className="gap-2">
              {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}
              Run {solver === "nsga2" ? "NSGA-II" : "Bloodhound"}
            </Button>
            <Button onClick={cancelJob} variant="secondary" disabled={!currentJobId || cancelling || activeJob?.status === "cancelled"} className="gap-2">
              {cancelling || activeJob?.status === "cancelling" ? <LoaderCircle size={16} className="animate-spin" /> : <Ban size={16} />}
              {cancelling || activeJob?.status === "cancelling" ? "Cancelling..." : "Cancel job"}
            </Button>
            <Button
              onClick={() =>
                currentJobId &&
                api
                  .getJob(currentJobId)
                  .then(() => onToast("Job refreshed", "Fresh backend job snapshot loaded."))
                  .catch((err) => {
                    const message = err instanceof Error ? err.message : "Could not refresh the backend job snapshot.";
                    console.error("[optimization] manual job refresh failed", { currentJobId, error: err });
                    setError(message);
                    onToast("Job refresh failed", message);
                  })
              }
              variant="ghost"
              disabled={!currentJobId}
              className="gap-2"
            >
              <RefreshCcw size={16} />
              Refresh
            </Button>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-lg font-semibold text-white">Optimization monitor</div>
              <div className="mt-1 break-words text-sm text-slate-400">Immediate `job_id`, progress polling, live logs and cancellation status.</div>
            </div>
            <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{activeJob?.status ?? "Idle"}</Badge>
          </div>
          <div className="mt-5 rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center justify-between text-sm">
              <span className="text-slate-400">Progress</span>
              <span className="text-white">{Math.round(activeJob?.progress ?? 0)}%</span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-white/6">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent to-accent-2 transition-all"
                style={{ width: `${Math.round(activeJob?.progress ?? 0)}%` }}
              />
            </div>
            <div className="mt-3 text-sm text-slate-400">{activeJob?.message ?? "No job has started yet."}</div>
          </div>

          <div className="mt-4 space-y-2">
            {(activeJob?.logs ?? []).slice(-10).map((log) => (
              <div key={`${log.timestamp}-${log.message}`} className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3 text-sm text-slate-300">
                <div className="break-words font-medium text-white">{log.message}</div>
                <div className="mt-1 text-xs text-slate-500">{new Date(log.timestamp).toLocaleTimeString()}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-lg font-semibold text-white">Solution inspection</div>
            <div className="mt-1 break-words text-sm text-slate-400">Stable desktop layout for overview, routes, matrix inputs, logs, and multi-solution NSGA-II inspection.</div>
          </div>
          <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{currentSolution?.solver_key ?? "No solution"}</Badge>
        </div>

        {!currentSolution || !selectedSolution ? (
          <div className="mt-4 text-sm text-slate-400">Run a backend optimization to inspect a real persisted solution here.</div>
        ) : (
          <div className="mt-5 space-y-5">
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Metric title="Total cost" value={formatMetric(selectedSolution.analytics.total_cost)} detail="Objective / total cost" />
              <Metric title="Distance" value={`${formatMetric(selectedSolution.analytics.total_distance)} km`} detail="Total traveled distance" />
              <Metric title="Travel time" value={`${formatMetric(selectedSolution.analytics.total_time)} min`} detail="Total route time" />
              <Metric
                title="Vehicles / routes"
                value={String(selectedSolution.analytics.vehicles_used ?? selectedSolution.routes.length)}
                detail={`Runtime ${formatMetric(selectedSolution.summary.runtime_seconds)} s`}
              />
            </div>
            <div className="grid gap-4 md:grid-cols-3">
              <Metric title="Selected customers" value={String(selectedSolution.summary.selected_customer_count ?? "-")} detail="Subset size used in this run" />
              <Metric title="Matrix subset" value={String(selectedSolution.summary.matrix_subset_size ?? "-")} detail="Depot plus selected customers" />
              <Metric
                title="Selected labels"
                value={Array.isArray(selectedSolution.summary.selected_address_labels) ? `${(selectedSolution.summary.selected_address_labels as string[]).length} nodes` : "-"}
                detail={Array.isArray(selectedSolution.summary.selected_address_labels) ? (selectedSolution.summary.selected_address_labels as string[]).join(", ") : "No subset metadata"}
              />
            </div>

          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setExportOpen(true)} variant="secondary" className="gap-2" disabled={!currentSolution || !selectedSolution}>
              <Download size={16} />
              Export
            </Button>
            <ResultTabButton active={resultTab === "overview"} onClick={() => setResultTab("overview")} icon={LayoutGrid} label="Overview" />
              <ResultTabButton active={resultTab === "routes"} onClick={() => setResultTab("routes")} icon={ListTree} label="Routes" />
              <ResultTabButton active={resultTab === "inputs"} onClick={() => setResultTab("inputs")} icon={TableProperties} label="Matrix / Inputs" />
              <ResultTabButton active={resultTab === "logs"} onClick={() => setResultTab("logs")} icon={ScrollText} label="Logs" />
              <ResultTabButton active={resultTab === "comparison"} onClick={() => setResultTab("comparison")} icon={GitCompareArrows} label="Comparison" />
            </div>

            <AnimatePresence mode="wait">
              <motion.div
                key={resultTab}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                {resultTab === "overview" && (
                  <OverviewTab
                    currentSolution={currentSolution}
                    matrix={matrix}
                    solutionVariants={solutionVariants}
                    selectedSolutionIndex={selectedSolutionIndex}
                    setSelectedSolutionIndex={setSelectedSolutionIndex}
                    paretoData={paretoData}
                  />
                )}
                {resultTab === "routes" && (
                  <RoutesTab
                    project={project}
                    selectedSolution={selectedSolution}
                    expandedRoute={expandedRoute}
                    setExpandedRoute={setExpandedRoute}
                  />
                )}
                {resultTab === "inputs" && (
                  <InputsTab
                    currentSolution={currentSolution}
                    selectedSolution={selectedSolution}
                    matrix={matrix}
                    project={project}
                    matrixSourceLabel={matrixSourceLabel}
                  />
                )}
                {resultTab === "logs" && <LogsTab job={activeJob} />}
                {resultTab === "comparison" && (
                  <ComparisonTab
                    currentSolution={currentSolution}
                    solutionVariants={solutionVariants}
                    selectedSolutionIndex={selectedSolutionIndex}
                    setSelectedSolutionIndex={setSelectedSolutionIndex}
                    paretoData={paretoData}
                  />
                )}
              </motion.div>
            </AnimatePresence>
          </div>
        )}
      </Card>
      <AlgorithmParametersModal
        open={parametersOpen}
        parameters={algorithmParameters}
        project={project}
        selectedSolver={solver}
        onClose={() => setParametersOpen(false)}
        onChangeParameters={updateAlgorithmParametersLocally}
        onSave={saveAlgorithmParameters}
        onToast={onToast}
      />
      <ExportResultsModal
        open={exportOpen}
        onClose={() => setExportOpen(false)}
        project={project}
        matrix={matrix}
        currentSolution={currentSolution}
        selectedSolution={selectedSolution}
        solutionVariants={solutionVariants}
        onToast={onToast}
      />
    </div>
  );
}

function OverviewTab({
  currentSolution,
  matrix,
  solutionVariants,
  selectedSolutionIndex,
  setSelectedSolutionIndex,
  paretoData,
}: {
  currentSolution: SolutionResponse;
  matrix: MatrixResponse | null;
  solutionVariants: CandidateSolution[];
  selectedSolutionIndex: number;
  setSelectedSolutionIndex: (value: number) => void;
  paretoData: Array<{ index: number; cost: number; maxDuration: number; avgDuration: number }>;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
      <div className="space-y-5">
        <Card className="p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium text-white">Solution selector</div>
              <div className="mt-1 break-words text-sm text-slate-400">
                {currentSolution.solver_key === "nsga2"
                  ? `NSGA-II returned ${solutionVariants.length} candidate solutions from the final rank-1 front.`
                  : "Bloodhound exposes the persisted best solution for this run."}
              </div>
            </div>
            <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{solutionVariants.length} solutions</Badge>
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-2">
            {solutionVariants.map((variant, index) => (
              <button
                key={variant.solution_id}
                onClick={() => setSelectedSolutionIndex(index)}
                className={`min-w-0 rounded-[22px] border p-4 text-left transition ${
                  selectedSolutionIndex === index ? "border-accent/30 bg-accent/10" : "border-white/10 bg-white/[0.03]"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-white">{variant.solution_id}</div>
                    <div className="mt-1 break-words text-xs text-slate-400">
                      Cost {formatMetric(getObjectiveValue(variant.summary, "total_cost") ?? variant.summary.total_cost)} | Routes {formatMetric(variant.analytics.route_count ?? variant.routes.length)}
                    </div>
                  </div>
                  <Badge className="border-white/10 bg-white/[0.04] text-slate-300">#{index + 1}</Badge>
                </div>
              </button>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <div className="text-sm font-medium text-white">Solver summary</div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <SummaryMetric label="Problem type" value={String(currentSolution.summary.problem_type ?? "-")} />
            <SummaryMetric label="Matrix source" value={matrix ? toMatrixSourceLabel(matrix.provider) : "Missing"} />
            <SummaryMetric label="Warnings" value={Array.isArray(currentSolution.summary.warnings) ? currentSolution.summary.warnings.join(" | ") || "None" : "None"} />
            <SummaryMetric label="Parameters used in this run" value={JSON.stringify(currentSolution.summary.algorithm_parameters ?? {}, null, 0)} />
          </div>
        </Card>
      </div>

      <Card className="p-5">
        <div className="text-sm font-medium text-white">Pareto / candidate view</div>
        <div className="mt-1 break-words text-sm text-slate-400">
          {currentSolution.solver_key === "nsga2"
            ? "Objective spread across the returned NSGA-II candidate solutions."
            : "Single-solution view for Bloodhound."}
        </div>
        {currentSolution.solver_key === "nsga2" && paretoData.length > 1 ? (
          <div className="mt-4 h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart>
                <CartesianGrid stroke="#223045" strokeDasharray="3 3" />
                <XAxis type="number" dataKey="cost" name="Total cost" stroke="#94a3b8" />
                <YAxis type="number" dataKey="maxDuration" name="Max route duration" stroke="#94a3b8" />
                <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                <Scatter data={paretoData} fill="#57e6ff" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="mt-4 rounded-[22px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
            {currentSolution.solver_key === "nsga2"
              ? "Only one unique candidate solution was returned in the final NSGA-II front for this run."
              : "Bloodhound returns one best solution rather than a Pareto set."}
          </div>
        )}
      </Card>
    </div>
  );
}

function RoutesTab({
  project,
  selectedSolution,
  expandedRoute,
  setExpandedRoute,
}: {
  project: ProjectRecord | null;
  selectedSolution: CandidateSolution;
  expandedRoute: number | null;
  setExpandedRoute: (value: number | null) => void;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <div className="space-y-3">
        {selectedSolution.routes.map((route, index) => {
          const open = expandedRoute === index;
          return (
            <div key={`${route.vehicle_type_id}-${index}`} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
              <button className="flex w-full min-w-0 items-start justify-between gap-3 text-left" onClick={() => setExpandedRoute(open ? null : index)}>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-white">{route.vehicle_label ?? `Route ${index + 1}`}</div>
                  <div className="mt-1 break-words text-xs text-slate-500">{route.stop_labels.join(" -> ")}</div>
                </div>
                <Badge className="border-white/10 bg-white/[0.04] text-slate-300">
                  {route.utilization != null ? `${(route.utilization * 100).toFixed(0)}% util.` : "-"}
                </Badge>
              </button>
              <AnimatePresence initial={false}>
                {open && (
                  <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden">
                    <div className="mt-4 grid gap-3 md:grid-cols-4">
                      <Metric title="Load" value={formatMetric(route.route_load)} detail={`Capacity ${formatMetric(route.capacity)}`} />
                      <Metric title="Distance" value={`${formatMetric(route.route_distance)} km`} detail={`${route.customer_count ?? 0} customers`} />
                      <Metric title="Time" value={`${formatMetric(route.route_time)} min`} detail={route.starts_at_depot && route.ends_at_depot ? "Depot start/end" : "Open route"} />
                      <Metric title="Cost" value={formatMetric(route.route_cost)} detail={`Vehicle ${route.vehicle_type_id ?? "n/a"}`} />
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          );
        })}
      </div>

      <div className="space-y-5">
        <RouteCanvas project={project} solution={selectedSolution} />
        <Card className="p-5">
          <div className="text-sm font-medium text-white">Selected candidate summary</div>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <SummaryMetric label="Solution ID" value={selectedSolution.solution_id} />
            <SummaryMetric label="Objective values" value={JSON.stringify(selectedSolution.summary.objectives ?? {}, null, 0)} />
            <SummaryMetric label="Route count" value={formatMetric(selectedSolution.analytics.route_count ?? selectedSolution.routes.length)} />
            <SummaryMetric label="Vehicles used" value={formatMetric(selectedSolution.analytics.vehicles_used ?? selectedSolution.routes.length)} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function InputsTab({
  currentSolution,
  selectedSolution,
  matrix,
  project,
  matrixSourceLabel,
}: {
  currentSolution: SolutionResponse;
  selectedSolution: CandidateSolution;
  matrix: MatrixResponse | null;
  project: ProjectRecord | null;
  matrixSourceLabel: string;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card className="p-5">
        <div className="text-sm font-medium text-white">Matrix and solver inputs</div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <SummaryMetric label="Matrix source" value={matrixSourceLabel} />
          <SummaryMetric label="Matrix size" value={matrix ? `${matrix.size} x ${matrix.size}` : "Missing"} />
          <SummaryMetric label="Solver" value={currentSolution.solver_key} />
          <SummaryMetric label="Depot" value={project?.addresses.find((item) => item.is_depot)?.label ?? "Missing"} />
          <SummaryMetric label="Objective names" value={JSON.stringify(currentSolution.raw_payload.objective_names ?? [], null, 0)} />
          <SummaryMetric label="Parameters used in this run" value={JSON.stringify(currentSolution.summary.algorithm_parameters ?? {}, null, 0)} />
        </div>
      </Card>

      <Card className="p-5">
        <div className="text-sm font-medium text-white">Selected candidate payload</div>
        <div className="mt-4 space-y-3">
          <SummaryMetric label="Solution ID" value={selectedSolution.solution_id} />
          <SummaryMetric label="Objective values" value={JSON.stringify(selectedSolution.summary.objectives ?? {}, null, 0)} />
          <SummaryMetric label="Analytics" value={JSON.stringify(selectedSolution.analytics ?? {}, null, 0)} />
          <SummaryMetric label="Raw payload" value={JSON.stringify(selectedSolution.raw_payload ?? {}, null, 0)} />
        </div>
      </Card>
    </div>
  );
}

function LogsTab({ job }: { job: JobResponse | null }) {
  return (
    <Card className="p-5">
      <div className="text-sm font-medium text-white">Run logs / progress history</div>
      <div className="mt-4 max-h-[420px] space-y-3 overflow-y-auto pr-1">
        {(job?.logs ?? []).length === 0 ? (
          <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
            No backend logs are available for this run yet.
          </div>
        ) : (
          (job?.logs ?? []).map((log) => (
            <div key={`${log.timestamp}-${log.message}`} className="rounded-[22px] border border-white/10 bg-white/[0.03] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="truncate text-sm font-medium text-white">{log.message}</div>
                <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{log.level}</Badge>
              </div>
              <div className="mt-2 text-xs text-slate-500">{new Date(log.timestamp).toLocaleString()}</div>
              {Object.keys(log.context ?? {}).length > 0 && (
                <pre className="mt-3 overflow-x-auto rounded-2xl border border-white/8 bg-[#09101c] p-3 text-xs text-slate-300">
                  {JSON.stringify(log.context, null, 2)}
                </pre>
              )}
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

function ComparisonTab({
  currentSolution,
  solutionVariants,
  selectedSolutionIndex,
  setSelectedSolutionIndex,
  paretoData,
}: {
  currentSolution: SolutionResponse;
  solutionVariants: CandidateSolution[];
  selectedSolutionIndex: number;
  setSelectedSolutionIndex: (value: number) => void;
  paretoData: Array<{ index: number; cost: number; maxDuration: number; avgDuration: number }>;
}) {
  return (
    <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
      <Card className="p-5">
        <div className="text-sm font-medium text-white">Candidate comparison table</div>
        <div className="mt-4 overflow-x-auto rounded-[22px] border border-white/10">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="bg-white/[0.03] text-slate-400">
              <tr>
                {["#", "Solution", "Cost", "Distance", "Time", "Routes"].map((heading) => (
                  <th key={heading} className="px-3 py-3 text-left font-medium">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10 bg-[#09101c]/60">
              {solutionVariants.map((variant, index) => (
                <tr
                  key={variant.solution_id}
                  className={`cursor-pointer transition ${selectedSolutionIndex === index ? "bg-accent/10" : ""}`}
                  onClick={() => setSelectedSolutionIndex(index)}
                >
                  <td className="px-3 py-3 text-slate-300">{index + 1}</td>
                  <td className="max-w-[220px] px-3 py-3 text-white">{variant.solution_id}</td>
                  <td className="px-3 py-3 text-slate-300">{formatMetric(getObjectiveValue(variant.summary, "total_cost") ?? variant.summary.total_cost)}</td>
                  <td className="px-3 py-3 text-slate-300">{formatMetric(variant.analytics.total_distance)}</td>
                  <td className="px-3 py-3 text-slate-300">{formatMetric(variant.analytics.total_time)}</td>
                  <td className="px-3 py-3 text-slate-300">{formatMetric(variant.analytics.route_count ?? variant.routes.length)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-5">
        <div className="text-sm font-medium text-white">Comparison view</div>
        <div className="mt-1 break-words text-sm text-slate-400">
          {currentSolution.solver_key === "nsga2"
            ? "Rank-1 candidate spread from the NSGA-II final front."
            : "Bloodhound currently exposes one best solution. Use the dedicated compare workspace for cross-algorithm comparison."}
        </div>
        {currentSolution.solver_key === "nsga2" && paretoData.length > 1 ? (
          <div className="mt-4 h-[320px]">
            <ResponsiveContainer width="100%" height="100%">
              <ScatterChart>
                <CartesianGrid stroke="#223045" strokeDasharray="3 3" />
                <XAxis type="number" dataKey="cost" name="Total cost" stroke="#94a3b8" />
                <YAxis type="number" dataKey="avgDuration" name="Average route duration" stroke="#94a3b8" />
                <Tooltip />
                <Scatter data={paretoData} fill="#a5b4fc" />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="mt-4 rounded-[22px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
            No multi-candidate comparison data is available for this result.
          </div>
        )}
      </Card>
    </div>
  );
}

function ReviewLists({ warnings, errors }: { warnings: string[]; errors: string[] }) {
  return (
    <div className="mt-5 grid gap-3 lg:grid-cols-2">
      <ListPanel title="Warnings" tone="warning" items={warnings} />
      <ListPanel title="Errors" tone="danger" items={errors} />
    </div>
  );
}

function ListPanel({ title, tone, items }: { title: string; tone: "warning" | "danger"; items: string[] }) {
  const styles = tone === "danger" ? "border-danger/30 bg-danger/10 text-danger" : "border-warning/30 bg-warning/10 text-warning";
  return (
    <div className={`rounded-[24px] border p-4 ${styles}`}>
      <div className="text-sm font-medium">{title}</div>
      <div className="mt-3 space-y-2 text-sm">
        {items.length ? items.map((item) => <div key={item} className="break-words">{item}</div>) : <div>No {title.toLowerCase()}.</div>}
      </div>
    </div>
  );
}

function SolverCard({
  active,
  title,
  description,
  locked = false,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  locked?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      disabled={locked}
      className={`rounded-[24px] border p-4 text-left transition ${
        active ? "border-accent/30 bg-accent/10" : "border-white/10 bg-white/[0.03]"
      } ${locked ? "cursor-not-allowed opacity-60" : ""}`}
    >
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium text-white">{title}</div>
        {locked && <Lock size={14} className="text-slate-400" />}
      </div>
      <div className="mt-1 break-words text-xs text-slate-400">{description}</div>
    </button>
  );
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[22px] border border-white/10 bg-white/[0.03] p-4">
      <div className="break-words text-xs uppercase tracking-[0.18em] text-slate-500">{title}</div>
      <div className="mt-2 break-words text-lg font-semibold leading-tight text-white">{value}</div>
      <div className="mt-2 break-words text-sm text-slate-400">{detail}</div>
    </div>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3">
      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-2 break-words text-sm text-slate-200">{value}</div>
    </div>
  );
}

function ResultTabButton({
  active,
  onClick,
  icon: Icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: typeof LayoutGrid;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 rounded-full border px-4 py-2 text-sm transition ${
        active ? "border-accent/30 bg-accent/10 text-white" : "border-white/10 bg-white/[0.03] text-slate-300"
      }`}
    >
      <Icon size={15} />
      {label}
    </button>
  );
}

function RouteCanvas({ project, solution }: { project: ProjectRecord | null; solution: CandidateSolution }) {
  if (!project) return null;
  const points = project.addresses.filter((item) => item.latitude != null && item.longitude != null);
  if (points.length < 2) {
    return (
      <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-400">
        Map-style route visualization activates when saved addresses include coordinates.
      </div>
    );
  }

  const lats = points.map((item) => item.latitude as number);
  const lons = points.map((item) => item.longitude as number);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const nodeByAddressId = new Map(points.map((item) => [item.id, item]));
  const mapPoint = (lat: number, lon: number) => ({
    x: 30 + ((lon - minLon) / Math.max(maxLon - minLon, 0.001)) * 320,
    y: 30 + ((maxLat - lat) / Math.max(maxLat - minLat, 0.001)) * 220,
  });

  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="text-sm font-medium text-white">Route visualization</div>
      <svg viewBox="0 0 380 280" className="mt-4 h-[280px] w-full rounded-[20px] bg-[#07111b]">
        {solution.routes.map((route, routeIndex) => {
          const coords = route.address_ids
            .map((addressId) => nodeByAddressId.get(addressId))
            .filter((item): item is NonNullable<typeof item> => Boolean(item))
            .map((item) => mapPoint(item.latitude as number, item.longitude as number));
          if (coords.length < 2) return null;
          const d = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
          return <path key={`${route.vehicle_type_id}-${routeIndex}`} d={d} fill="none" stroke={routePalette[routeIndex % routePalette.length]} strokeWidth="3" strokeLinecap="round" />;
        })}
        {points.map((point) => {
          const mapped = mapPoint(point.latitude as number, point.longitude as number);
          return (
            <g key={point.id}>
              <circle cx={mapped.x} cy={mapped.y} r={point.is_depot ? 7 : 5} fill={point.is_depot ? "#57e6ff" : "#f8fafc"} />
              <text x={mapped.x + 8} y={mapped.y - 8} fontSize="10" fill="#94a3b8">
                {point.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function formatMetric(value: unknown) {
  if (typeof value === "number") return value.toFixed(2);
  return String(value ?? "-");
}

function numeric(value: unknown) {
  return typeof value === "number" ? value : Number(value ?? 0);
}

function toMatrixSourceLabel(provider: string) {
  if (provider === "osrm") return "OSRM generated";
  if (provider === "json_import") return "JSON imported";
  return provider;
}

function getObjectiveValue(summary: Record<string, unknown>, key: string) {
  const objectives = summary.objectives;
  if (!objectives || typeof objectives !== "object") {
    return undefined;
  }
  return (objectives as Record<string, unknown>)[key];
}

function getInitialSelectedCustomerIds(project: ProjectRecord | null) {
  const customers = (project?.addresses ?? []).filter((item) => !item.is_depot);
  const saved = ((project?.settings.selected_customer_ids as string[] | undefined) ?? []).filter((item) =>
    customers.some((customer) => customer.id === item),
  );
  return saved.length > 0 ? saved : customers.map((item) => item.id);
}

function ExportResultsModal({
  open,
  onClose,
  project,
  matrix,
  currentSolution,
  selectedSolution,
  solutionVariants,
  onToast,
}: {
  open: boolean;
  onClose: () => void;
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentSolution: SolutionResponse | null;
  selectedSolution: CandidateSolution | null;
  solutionVariants: CandidateSolution[];
  onToast: (title: string, body: string) => void;
}) {
  if (!currentSolution || !selectedSolution) return null;

  const buildBaseName = () =>
    `${(project?.name ?? "pulseroute").toLowerCase().replace(/[^a-z0-9]+/gi, "-")}-${currentSolution.solver_key}`;

  const normalizeSolution = (solution: CandidateSolution) => ({
    project_name: project?.name ?? null,
    exported_at: new Date().toISOString(),
    algorithm_name: String(solution.summary.algorithm_name ?? currentSolution.solver_key),
    solution_id: solution.solution_id,
    selected_address_ids: Array.isArray(solution.summary.selected_address_ids) ? solution.summary.selected_address_ids : [],
    selected_address_labels: Array.isArray(solution.summary.selected_address_labels) ? solution.summary.selected_address_labels : [],
    selected_customer_count: solution.summary.selected_customer_count ?? null,
    matrix_subset_size: solution.summary.matrix_subset_size ?? null,
    objective_values: solution.summary.objectives ?? {},
    total_distance: solution.analytics.total_distance ?? null,
    total_time: solution.analytics.total_time ?? null,
    total_cost: solution.analytics.total_cost ?? solution.summary.total_cost ?? null,
    vehicles_used: solution.analytics.vehicles_used ?? solution.routes.length,
    runtime_seconds: solution.summary.runtime_seconds ?? null,
    parameters_used: solution.summary.parameters_used ?? solution.summary.algorithm_parameters ?? {},
    matrix_metadata: matrix?.metadata ?? {},
    matrix_provider: matrix?.provider ?? null,
    routes: solution.routes.map((route, index) => ({
      route_index: index + 1,
      vehicle_label: route.vehicle_label ?? null,
      vehicle_type_id: route.vehicle_type_id ?? null,
      customer_sequence: route.stop_labels,
      address_ids: route.address_ids,
      route_distance_km: route.route_distance ?? null,
      route_time_minutes: route.route_time ?? null,
      route_cost: route.route_cost ?? null,
      route_load: route.route_load ?? null,
      route_capacity: route.capacity ?? null,
      utilization: route.utilization ?? null,
    })),
  });

  const buildRouteSummaryCsv = (solution: CandidateSolution) => {
    const rows = [
      ["route_index", "vehicle_label", "vehicle_type_id", "route_distance_km", "route_time_minutes", "route_cost", "route_load", "route_capacity", "utilization", "customer_sequence"],
      ...solution.routes.map((route, index) => [
        String(index + 1),
        route.vehicle_label ?? "",
        route.vehicle_type_id ?? "",
        String(route.route_distance ?? ""),
        String(route.route_time ?? ""),
        String(route.route_cost ?? ""),
        String(route.route_load ?? ""),
        String(route.capacity ?? ""),
        String(route.utilization ?? ""),
        route.stop_labels.join(" -> "),
      ]),
    ];
    return rows.map(toCsvLine).join("\n");
  };

  const buildSolutionCsv = (solution: CandidateSolution) => {
    const rows = [
      ["field", "value"],
      ["project_name", project?.name ?? ""],
      ["algorithm_name", String(solution.summary.algorithm_name ?? currentSolution.solver_key)],
      ["solution_id", solution.solution_id],
      ["total_cost", String(solution.analytics.total_cost ?? solution.summary.total_cost ?? "")],
      ["total_distance_km", String(solution.analytics.total_distance ?? "")],
      ["total_time_minutes", String(solution.analytics.total_time ?? "")],
      ["vehicles_used", String(solution.analytics.vehicles_used ?? solution.routes.length)],
      ["runtime_seconds", String(solution.summary.runtime_seconds ?? "")],
      ["parameters_used", JSON.stringify(solution.summary.parameters_used ?? solution.summary.algorithm_parameters ?? {})],
      ["objective_values", JSON.stringify(solution.summary.objectives ?? {})],
      ["matrix_provider", matrix?.provider ?? ""],
      ["matrix_metadata", JSON.stringify(matrix?.metadata ?? {})],
    ];
    return rows.map(toCsvLine).join("\n");
  };

  const buildComparisonCsv = () => {
    const rows = [
      ["solution_id", "algorithm_name", "total_cost", "total_distance_km", "total_time_minutes", "vehicles_used", "runtime_seconds"],
      ...solutionVariants.map((solution) => [
        solution.solution_id,
        String(solution.summary.algorithm_name ?? currentSolution.solver_key),
        String(solution.analytics.total_cost ?? solution.summary.total_cost ?? ""),
        String(solution.analytics.total_distance ?? ""),
        String(solution.analytics.total_time ?? ""),
        String(solution.analytics.vehicles_used ?? solution.routes.length),
        String(solution.summary.runtime_seconds ?? ""),
      ]),
    ];
    return rows.map(toCsvLine).join("\n");
  };

  const exportAction = async (label: string, filename: string, content: string | object, mimeType?: string) => {
    try {
      if (typeof content === "string") {
        await browserFileSystemAdapter.saveTextFile(filename, content, mimeType);
      } else {
        await browserFileSystemAdapter.saveJsonFile(filename, content);
      }
      onToast("Export complete", `${label} exported successfully.`);
      onClose();
    } catch (error) {
      onToast("Export failed", error instanceof Error ? error.message : `Could not export ${label.toLowerCase()}.`);
    }
  };

  const fullRunReport = {
    project_name: project?.name ?? null,
    exported_at: new Date().toISOString(),
    solver_key: currentSolution.solver_key,
    selected_solution: normalizeSolution(selectedSolution),
    all_solutions: solutionVariants.map(normalizeSolution),
    matrix: matrix
      ? {
          provider: matrix.provider,
          metadata: matrix.metadata,
          size: matrix.size,
        }
      : null,
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-slate-950/65 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            className="fixed inset-x-4 top-10 z-50 mx-auto w-[min(720px,calc(100vw-2rem))] rounded-[30px] border border-white/10 bg-[#09111f]/95 p-5 shadow-panel backdrop-blur-2xl"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-lg font-semibold text-white">Export Results</div>
                <div className="break-words text-sm text-slate-400">Export normalized solution data as JSON or CSV.</div>
              </div>
              <Button variant="ghost" className="px-3" onClick={onClose}>
                <X size={16} />
              </Button>
            </div>
            <div className="mt-5 grid gap-3 md:grid-cols-2">
              <ExportButton label="Selected solution JSON" onClick={() => void exportAction("Selected solution JSON", `${buildBaseName()}-${selectedSolution.solution_id}.json`, normalizeSolution(selectedSolution))} />
              <ExportButton label="Selected solution CSV" onClick={() => void exportAction("Selected solution CSV", `${buildBaseName()}-${selectedSolution.solution_id}.csv`, buildSolutionCsv(selectedSolution), "text/csv;charset=utf-8")} />
              <ExportButton label="Route summary CSV" onClick={() => void exportAction("Route summary CSV", `${buildBaseName()}-${selectedSolution.solution_id}-routes.csv`, buildRouteSummaryCsv(selectedSolution), "text/csv;charset=utf-8")} />
              <ExportButton label="Comparison results CSV" onClick={() => void exportAction("Comparison results CSV", `${buildBaseName()}-comparison.csv`, buildComparisonCsv(), "text/csv;charset=utf-8")} />
              <ExportButton label="Full run report JSON" onClick={() => void exportAction("Full run report JSON", `${buildBaseName()}-run-report.json`, fullRunReport)} />
              {currentSolution.solver_key === "nsga2" && (
                <ExportButton label="All Pareto solutions JSON" onClick={() => void exportAction("All Pareto solutions JSON", `${buildBaseName()}-all-solutions.json`, solutionVariants.map(normalizeSolution))} />
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function ExportButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="rounded-[22px] border border-white/10 bg-white/[0.03] px-4 py-4 text-left text-sm text-slate-200 transition hover:border-accent/20 hover:bg-white/[0.05]">
      {label}
    </button>
  );
}

function toCsvLine(values: string[]) {
  return values
    .map((value) => {
      const escaped = value.replace(/"/g, "\"\"");
      return /[",\n]/.test(escaped) ? `"${escaped}"` : escaped;
    })
    .join(",");
}
