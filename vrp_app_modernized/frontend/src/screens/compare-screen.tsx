import { useEffect, useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import type { ProjectRecord, ProjectSolutionSummary, SolutionResponse } from "@/types/api";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

type Props = {
  project: ProjectRecord | null;
  currentSolution: SolutionResponse | null;
  onToast: (title: string, body: string) => void;
};

export default function CompareScreen({ project, currentSolution, onToast }: Props) {
  const [solutions, setSolutions] = useState<ProjectSolutionSummary[]>([]);

  useEffect(() => {
    if (!project?.id) return;
    api
      .listProjectSolutions(project.id)
      .then(setSolutions)
      .catch((error) => onToast("Comparison unavailable", error instanceof Error ? error.message : "Could not load saved solutions."));
  }, [onToast, project?.id, currentSolution?.id]);

  const latestBloodhound = useMemo(() => solutions.find((item) => item.solver_key === "bloodhound") ?? null, [solutions]);
  const latestNsga2 = useMemo(() => solutions.find((item) => item.solver_key === "nsga2") ?? null, [solutions]);
  const compareReady = Boolean(latestBloodhound && latestNsga2);

  if (!project) {
    return (
      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Comparison workspace</div>
        <div className="mt-2 text-sm text-slate-400">Save a project and run both algorithms to unlock side-by-side comparison.</div>
      </Card>
    );
  }

  if (!compareReady) {
    return (
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-lg font-semibold text-white">NSGA-II vs Bloodhound comparison</div>
            <div className="mt-1 break-words text-sm text-slate-400">This workspace becomes active once one saved result exists for each solver.</div>
          </div>
          <Badge className="border-warning/20 bg-warning/10 text-warning">Waiting</Badge>
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <PlaceholderCard title="Bloodhound" ready={Boolean(latestBloodhound)} />
          <PlaceholderCard title="NSGA-II" ready={Boolean(latestNsga2)} />
        </div>
      </Card>
    );
  }

  const bloodhoundSolution = latestBloodhound!;
  const nsga2Solution = latestNsga2!;

  const chartData = [
    {
      metric: "Total cost",
      bloodhound: numeric(bloodhoundSolution.analytics.total_cost),
      nsga2: numeric(nsga2Solution.analytics.total_cost),
    },
    {
      metric: "Distance",
      bloodhound: numeric(bloodhoundSolution.analytics.total_distance),
      nsga2: numeric(nsga2Solution.analytics.total_distance),
    },
    {
      metric: "Travel time",
      bloodhound: numeric(bloodhoundSolution.analytics.total_time),
      nsga2: numeric(nsga2Solution.analytics.total_time),
    },
    {
      metric: "Vehicles used",
      bloodhound: numeric(bloodhoundSolution.analytics.vehicles_used),
      nsga2: numeric(nsga2Solution.analytics.vehicles_used),
    },
  ];

  return (
    <div className="space-y-5">
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="text-lg font-semibold text-white">NSGA-II vs Bloodhound comparison</div>
            <div className="mt-1 break-words text-sm text-slate-400">
              NSGA-II uses unit customer demand and automatic vehicle count. Bloodhound uses the real fleet and customer demand profile.
            </div>
          </div>
          <Badge className="border-success/20 bg-success/10 text-success">Ready</Badge>
        </div>

        <div className="mt-5 grid gap-5 xl:grid-cols-2">
          <SolutionCard title="Bloodhound" solution={bloodhoundSolution} />
          <SolutionCard title="NSGA-II" solution={nsga2Solution} />
        </div>
      </Card>

      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Objective comparison</div>
        <div className="mt-1 text-sm text-slate-400">Saved normalized solution summaries from the backend, using km, minutes, cost, and runtime seconds consistently for both algorithms.</div>
        <div className="mt-5 h-[360px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#223045" />
              <XAxis dataKey="metric" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" />
              <Tooltip />
              <Bar dataKey="bloodhound" fill="#57e6ff" radius={[8, 8, 0, 0]} />
              <Bar dataKey="nsga2" fill="#a5b4fc" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
    </div>
  );
}

function SolutionCard({ title, solution }: { title: string; solution: ProjectSolutionSummary }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 break-words text-lg font-semibold text-white">{title}</div>
        <Badge className="max-w-full border-white/10 bg-white/[0.04] text-slate-300">{new Date(solution.created_at).toLocaleString()}</Badge>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Metric title="Algorithm" value={String(solution.summary.algorithm_name ?? solution.solver_key)} />
        <Metric title="Total cost" value={`${String(solution.analytics.total_cost ?? "-")} cost`} />
        <Metric title="Distance" value={`${String(solution.analytics.total_distance ?? "-")} km`} />
        <Metric title="Travel time" value={`${String(solution.analytics.total_time ?? "-")} min`} />
        <Metric title="Vehicles used" value={String(solution.analytics.vehicles_used ?? "-")} />
        <Metric title="Route count" value={String(solution.analytics.route_count ?? "-")} />
        <Metric title="Runtime" value={`${String(solution.summary.runtime_seconds ?? "-")} s`} />
      </div>
    </div>
  );
}

function PlaceholderCard({ title, ready }: { title: string; ready: boolean }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 break-words text-lg font-semibold text-white">{title}</div>
        <Badge className={ready ? "border-success/20 bg-success/10 text-success" : "border-white/10 bg-white/[0.04] text-slate-300"}>
          {ready ? "Ready" : "Missing result"}
        </Badge>
      </div>
    </div>
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[20px] border border-white/10 bg-[#09101c] p-4">
      <div className="break-words text-xs uppercase tracking-[0.18em] text-slate-500">{title}</div>
      <div className="mt-2 break-words text-lg font-semibold leading-tight text-white">{value}</div>
    </div>
  );
}

function numeric(value: unknown) {
  return typeof value === "number" ? value : Number(value ?? 0);
}
