import { useEffect, useMemo, useState, type ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Ban, LoaderCircle, Lock, Play, RefreshCcw } from "lucide-react";
import { api } from "@/lib/api";
import { detectFleetType, getDepot, projectValidation } from "@/lib/vrp";
import { useJobPolling } from "@/hooks/use-job-polling";
import type { JobResponse, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

type Props = {
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentJobId: string | null;
  setCurrentJobId: (jobId: string | null) => void;
  currentSolution: SolutionResponse | null;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

const routePalette = ["#57e6ff", "#91f7c4", "#f7cf7e", "#f48fb1", "#a5b4fc", "#f9a8d4"];

export function OptimizationConsole({
  project,
  matrix,
  currentJobId,
  setCurrentJobId,
  currentSolution,
  setCurrentSolution,
  onToast,
}: Props) {
  const [solver, setSolver] = useState<"nsga2" | "bloodhound">("bloodhound");
  const [population, setPopulation] = useState(60);
  const [generations, setGenerations] = useState(120);
  const [hunts, setHunts] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedRoute, setExpandedRoute] = useState<number | null>(0);
  const { job, error: jobError } = useJobPolling(currentJobId);

  const fleetType = useMemo(() => detectFleetType(project?.fleet_units ?? []), [project?.fleet_units]);
  const validation = useMemo(() => projectValidation(project, matrix), [project, matrix]);
  const depot = useMemo(() => getDepot(project), [project]);
  const solverLocked = solver === "nsga2" && fleetType === "heterogeneous";

  useEffect(() => {
    if (fleetType === "heterogeneous" && solver === "nsga2") {
      setSolver("bloodhound");
    }
  }, [fleetType, solver]);

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
      onToast("Optimization complete", `${job.solver_key} finished successfully.`);
    }
    if (job.status === "failed") {
      onToast("Optimization failed", "Inspect the backend error and solver logs in this workspace.");
    }
  }, [job, onToast]);

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

    return {
      warnings,
      errors,
      completeness: Math.max(0, validation.completeness - (errors.length ? 20 : 0)),
    };
  }, [fleetType, matrix, solver, validation.completeness, validation.errors, validation.warnings]);

  const runSolver = async () => {
    if (!project || !matrix || inputReview.errors.length > 0) return;
    try {
      setBusy(true);
      setError(null);
      setCurrentSolution(null);
      const payload =
        solver === "nsga2"
          ? await api.solveNsga2(project.id, matrix.id, { pop_size: population, generations, seed: 0 })
          : await api.solveBloodhound(project.id, matrix.id, { num_hunts: hunts, explore_iterations: 120, num_wolves: 12 });
      setCurrentJobId(payload.job_id);
      onToast("Job queued", `${solver} job accepted by backend.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start optimization.");
    } finally {
      setBusy(false);
    }
  };

  const cancelJob = async () => {
    if (!currentJobId) return;
    try {
      await api.cancelJob(currentJobId);
      onToast("Cancellation requested", "Backend job marked for cancellation.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Cancellation failed.");
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
            {solver === "nsga2" ? (
              <>
                <Field label="Population">
                  <Input type="number" value={population} onChange={(event) => setPopulation(Number(event.target.value))} />
                </Field>
                <Field label="Generations">
                  <Input type="number" value={generations} onChange={(event) => setGenerations(Number(event.target.value))} />
                </Field>
              </>
            ) : (
              <>
                <Field label="Hunts">
                  <Input type="number" value={hunts} onChange={(event) => setHunts(Number(event.target.value))} />
                </Field>
                <Metric title="Fleet mode" value={fleetType} detail="Auto-detected from saved vehicle definitions" />
              </>
            )}
          </div>

          {(error || jobError) && (
            <div className="mt-4 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
              {error ?? jobError}
            </div>
          )}

          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Metric title="Problem type" value={fleetType} detail={solver === "bloodhound" ? "Demand + fleet aware" : "Unit-demand mode"} />
            <Metric title="Customers" value={String(project?.addresses.filter((item) => !item.is_depot).length ?? 0)} detail={depot ? `Depot: ${depot.label}` : "Depot missing"} />
            <Metric title="Matrix" value={matrix ? "Ready" : "Missing"} detail={matrix ? `${matrix.provider} ${matrix.size}x${matrix.size}` : "Generate in matrix workspace"} />
          </div>

          <ReviewLists warnings={inputReview.warnings} errors={inputReview.errors} />

          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={runSolver} disabled={!project || !matrix || busy || solverLocked || inputReview.errors.length > 0} className="gap-2">
              {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}
              Run {solver === "nsga2" ? "NSGA-II" : "Bloodhound"}
            </Button>
            <Button onClick={cancelJob} variant="secondary" disabled={!currentJobId} className="gap-2">
              <Ban size={16} />
              Cancel job
            </Button>
            <Button
              onClick={() => currentJobId && api.getJob(currentJobId).then(() => onToast("Job refreshed", "Fresh backend job snapshot loaded."))}
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
            <div className="mt-1 break-words text-sm text-slate-400">Persisted backend solution, route-level metrics, runtime summary and sequence visualization.</div>
          </div>
          <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{currentSolution?.solver_key ?? "No solution"}</Badge>
        </div>

        {!currentSolution ? (
          <div className="mt-4 text-sm text-slate-400">Run a backend optimization to inspect a real persisted solution here.</div>
        ) : (
          <div className="mt-5 space-y-5">
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <Metric title="Total cost" value={formatMetric(currentSolution.analytics.total_cost)} detail="Objective / total cost" />
              <Metric title="Distance" value={`${formatMetric(currentSolution.analytics.total_distance)} km`} detail="Total traveled distance" />
              <Metric title="Travel time" value={`${formatMetric(currentSolution.analytics.total_time)} min`} detail="Total route time" />
              <Metric title="Vehicles used" value={String(currentSolution.analytics.vehicles_used ?? currentSolution.routes.length)} detail={`Runtime ${formatMetric(currentSolution.summary.runtime_seconds)} s`} />
            </div>

            <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
              <div className="space-y-3">
                {currentSolution.routes.map((route, index) => {
                  const open = expandedRoute === index;
                  return (
                    <div key={`${route.vehicle_type_id}-${index}`} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                      <button className="flex w-full min-w-0 items-start justify-between gap-3 text-left" onClick={() => setExpandedRoute(open ? null : index)}>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium text-white">{route.vehicle_label ?? `Route ${index + 1}`}</div>
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
                <RouteCanvas project={project} solution={currentSolution} />
                <SummaryPanel summary={currentSolution.summary} />
              </div>
            </div>
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

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      {children}
    </div>
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

function SummaryPanel({ summary }: { summary: Record<string, unknown> }) {
  const entries = [
    ["Problem type", String(summary.problem_type ?? "-")],
    ["Runtime", `${formatMetric(summary.runtime_seconds)} s`],
    ["Warnings", Array.isArray(summary.warnings) ? summary.warnings.join(" | ") || "None" : "None"],
    ["Parameters", JSON.stringify(summary.algorithm_parameters ?? {}, null, 0)],
  ];
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="text-sm font-medium text-white">Solver summary</div>
      <div className="mt-4 space-y-3">
        {entries.map(([label, value]) => (
          <div key={label} className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
            <div className="mt-2 break-words text-sm text-slate-200">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function RouteCanvas({ project, solution }: { project: ProjectRecord | null; solution: SolutionResponse }) {
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
