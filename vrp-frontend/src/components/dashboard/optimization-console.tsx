import { useEffect, useState } from "react";
import { Ban, LoaderCircle, Play, RefreshCcw } from "lucide-react";
import { api } from "@/lib/api";
import { useJobPolling } from "@/hooks/use-job-polling";
import type { JobResponse, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
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

export function OptimizationConsole({
  project,
  matrix,
  currentJobId,
  setCurrentJobId,
  currentSolution,
  setCurrentSolution,
  onToast,
}: Props) {
  const [solver, setSolver] = useState<"nsga2" | "bloodhound">("nsga2");
  const [population, setPopulation] = useState(60);
  const [generations, setGenerations] = useState(120);
  const [hunts, setHunts] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { job, error: jobError } = useJobPolling(currentJobId);

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
      onToast("Optimization failed", "Check backend logs and solver settings.");
    }
  }, [job, onToast]);

  const runSolver = async () => {
    if (!project || !matrix) return;
    try {
      setBusy(true);
      setError(null);
      setCurrentSolution(null);
      const payload =
        solver === "nsga2"
          ? await api.solveNsga2(project.id, matrix.id, { pop_size: population, generations, seed: 0 })
          : await api.solveBloodhound(project.id, matrix.id, { num_hunts: hunts, explore_iterations: 120 });
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
    <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Optimization execution</div>
        <div className="mt-1 text-sm text-slate-400">Only real backend-backed solvers remain active: `NSGA2-Better` and `bloodhoundtest3_for_app`.</div>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <button
            onClick={() => setSolver("nsga2")}
            className={`rounded-[24px] border p-4 text-left transition ${solver === "nsga2" ? "border-accent/30 bg-accent/10" : "border-white/10 bg-white/[0.03]"}`}
          >
            <div className="text-sm font-medium text-white">NSGA-II</div>
            <div className="mt-1 text-xs text-slate-400">Homogeneous fleet multi-objective solve</div>
          </button>
          <button
            onClick={() => setSolver("bloodhound")}
            className={`rounded-[24px] border p-4 text-left transition ${solver === "bloodhound" ? "border-accent/30 bg-accent/10" : "border-white/10 bg-white/[0.03]"}`}
          >
            <div className="text-sm font-medium text-white">Bloodhound</div>
            <div className="mt-1 text-xs text-slate-400">Hunt-based search with route-level progression logs</div>
          </button>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {solver === "nsga2" ? (
            <>
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Population</div>
                <Input type="number" value={population} onChange={(event) => setPopulation(Number(event.target.value))} />
              </div>
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Generations</div>
                <Input type="number" value={generations} onChange={(event) => setGenerations(Number(event.target.value))} />
              </div>
            </>
          ) : (
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Hunts</div>
              <Input type="number" value={hunts} onChange={(event) => setHunts(Number(event.target.value))} />
            </div>
          )}
        </div>

        {(error || jobError) && (
          <div className="mt-4 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error ?? jobError}
          </div>
        )}

        <div className="mt-6 flex flex-wrap gap-3">
          <Button onClick={runSolver} disabled={!project || !matrix || busy} className="gap-2">
            {busy ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}
            Start optimization
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

      <div className="space-y-5">
        <Card className="p-6">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-lg font-semibold text-white">Job progress</div>
              <div className="mt-1 text-sm text-slate-400">Immediate `job_id`, progress polling, log stream, cancellation state.</div>
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
            {(activeJob?.logs ?? []).slice(-8).map((log) => (
              <div key={`${log.timestamp}-${log.message}`} className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3 text-sm text-slate-300">
                {log.message}
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-6">
          <div className="text-lg font-semibold text-white">Solution snapshot</div>
          {!currentSolution ? (
            <div className="mt-3 text-sm text-slate-400">Run an optimization job to fetch persisted backend solution details.</div>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="grid gap-4 md:grid-cols-3">
                {Object.entries(currentSolution.analytics).map(([key, value]) => (
                  <div key={key} className="rounded-[22px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">{key}</div>
                    <div className="mt-2 text-lg font-semibold text-white">{String(value)}</div>
                  </div>
                ))}
              </div>
              <div className="space-y-3">
                {currentSolution.routes.map((route, index) => (
                  <div key={`${route.vehicle_type_id}-${index}`} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="flex items-center justify-between">
                      <div className="text-sm font-medium text-white">{route.vehicle_label ?? `Route ${index + 1}`}</div>
                      <Badge className="border-white/10 bg-white/[0.04] text-slate-300">
                        cost {route.route_cost?.toFixed(2) ?? "-"}
                      </Badge>
                    </div>
                    <div className="mt-2 text-sm text-slate-400">Nodes: {route.nodes.join(" -> ")}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
