import type { MatrixResponse, ProjectRecord } from "@/types/api";
import { getDepot, summarizeMatrix } from "@/lib/vrp";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

export function MatrixOverview({ project, matrix }: { project: ProjectRecord | null; matrix: MatrixResponse | null }) {
  if (!project) {
    return (
      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Matrix workspace</div>
        <div className="mt-2 text-sm text-slate-400">Create or load a project first. Matrix generation uses the saved project and geocoded coordinates.</div>
      </Card>
    );
  }

  const stats = summarizeMatrix(matrix);
  const depot = getDepot(project);
  const previewDistance = matrix?.distance_matrix.slice(0, 6).map((row) => row.slice(0, 6)) ?? [];
  const previewTime = matrix?.time_matrix.slice(0, 6).map((row) => row.slice(0, 6)) ?? [];
  const geocodedCount = project.addresses.filter((item) => item.latitude != null && item.longitude != null).length;

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-[0.95fr_1.05fr]">
        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-lg font-semibold text-white">Matrix readiness</div>
              <div className="mt-1 break-words text-sm text-slate-400">Inspect the saved coordinate coverage before launching solver jobs.</div>
            </div>
            <Badge className={matrix ? "border-success/20 bg-success/10 text-success" : "border-warning/20 bg-warning/10 text-warning"}>
              {matrix ? "Ready" : "Pending"}
            </Badge>
          </div>

          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Metric title="Project" value={project.name} detail={project.description ?? "No description"} />
            <Metric title="Depot" value={depot?.label ?? "Missing"} detail={depot?.address_line ?? "Select a depot in workflow"} />
            <Metric title="Coordinate coverage" value={`${geocodedCount}/${project.addresses.length}`} detail="Addresses with usable latitude/longitude" />
            <Metric title="Provider" value={matrix?.provider ?? "Waiting"} detail={matrix ? `Snapshot ${matrix.id.slice(0, 8)}` : "Generate a backend snapshot"} />
          </div>

          <div className="mt-5 rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="text-sm font-medium text-white">Address geocoding status</div>
            <div className="mt-3 space-y-2">
              {project.addresses.map((address) => (
                <div key={address.id} className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm text-white">{address.label}</div>
                    <div className="mt-1 break-words text-xs text-slate-500">{address.address_line}</div>
                  </div>
                  <Badge className={statusClass(address.geocode_status)}>{address.geocode_status}</Badge>
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="text-lg font-semibold text-white">Matrix summary stats</div>
              <div className="mt-1 break-words text-sm text-slate-400">Real snapshot metrics computed from the backend matrix payload.</div>
            </div>
            <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{matrix ? `${matrix.size} x ${matrix.size}` : "No snapshot"}</Badge>
          </div>
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Metric title="Min distance" value={`${stats.minDistance.toFixed(2)} km`} detail="Shortest non-zero pair" />
            <Metric title="Avg distance" value={`${stats.avgDistance.toFixed(2)} km`} detail="Average pairwise distance" />
            <Metric title="Max distance" value={`${stats.maxDistance.toFixed(2)} km`} detail="Longest pair in snapshot" />
            <Metric title="Avg time" value={`${stats.avgTime.toFixed(1)} min`} detail="Average pairwise travel time" />
            <Metric title="Max time" value={`${stats.maxTime.toFixed(1)} min`} detail="Longest pair travel time" />
            <Metric title="Missing pairs" value={String(stats.missingPairs)} detail={stats.missingPairs ? "Check provider warnings before solving" : "No failed pairs detected"} />
          </div>
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card className="p-6">
          <div className="text-lg font-semibold text-white">Distance matrix preview</div>
          <div className="mt-1 text-sm text-slate-400">Top-left snapshot section for quick inspection and debugging.</div>
          <MatrixGrid values={previewDistance} emptyMessage="Generate a matrix to inspect distance values." suffix="km" />
        </Card>
        <Card className="p-6">
          <div className="text-lg font-semibold text-white">Time matrix preview</div>
          <div className="mt-1 text-sm text-slate-400">Top-left time table using the exact backend snapshot used by the solvers.</div>
          <MatrixGrid values={previewTime} emptyMessage="Generate a matrix to inspect travel-time values." suffix="min" />
        </Card>
      </div>
    </div>
  );
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="break-words text-xs uppercase tracking-[0.18em] text-slate-500">{title}</div>
      <div className="mt-2 break-words text-lg font-semibold leading-tight text-white">{value}</div>
      <div className="mt-2 break-words text-sm text-slate-400">{detail}</div>
    </div>
  );
}

function MatrixGrid({ values, emptyMessage, suffix }: { values: number[][]; emptyMessage: string; suffix: string }) {
  if (!values.length) {
    return <div className="mt-4 text-sm text-slate-400">{emptyMessage}</div>;
  }
  return (
    <div className="mt-4 overflow-x-auto rounded-[22px] border border-white/10">
      <table className="min-w-full divide-y divide-white/10 text-sm">
        <tbody className="divide-y divide-white/10 bg-[#09101c]">
          {values.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((value, valueIndex) => (
                <td key={`${rowIndex}-${valueIndex}`} className="border-r border-white/10 px-3 py-3 text-slate-300 last:border-r-0">
                  {value.toFixed(2)} {suffix}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function statusClass(status: string) {
  if (status === "ready") return "border-success/20 bg-success/10 text-success";
  if (status === "failed") return "border-danger/20 bg-danger/10 text-danger";
  return "border-white/10 bg-white/[0.04] text-slate-300";
}
