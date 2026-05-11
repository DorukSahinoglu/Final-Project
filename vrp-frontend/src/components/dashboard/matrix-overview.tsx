import type { MatrixResponse, ProjectRecord } from "@/types/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function MatrixOverview({ project, matrix }: { project: ProjectRecord | null; matrix: MatrixResponse | null }) {
  if (!project) {
    return (
      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Matrix workspace</div>
        <div className="mt-2 text-sm text-slate-400">Create a project first. Matrix generation activates after project and geocoding steps.</div>
      </Card>
    );
  }

  const previewDistance = matrix?.distance_matrix.slice(0, 5).map((row) => row.slice(0, 5)) ?? [];
  const previewTime = matrix?.time_matrix.slice(0, 5).map((row) => row.slice(0, 5)) ?? [];

  return (
    <div className="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
      <Card className="p-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-lg font-semibold text-white">Matrix metadata</div>
            <div className="mt-1 text-sm text-slate-400">Backend-generated matrix snapshot only. No mocked map or fabricated coverage stats.</div>
          </div>
          <Badge className={matrix ? "border-success/20 bg-success/10 text-success" : "border-white/10 bg-white/[0.04] text-slate-400"}>
            {matrix ? "Ready" : "Pending"}
          </Badge>
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Project</div>
            <div className="mt-2 text-lg font-semibold text-white">{project.name}</div>
          </div>
          <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Nodes</div>
            <div className="mt-2 text-lg font-semibold text-white">{project.addresses.length}</div>
          </div>
          <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Provider</div>
            <div className="mt-2 text-lg font-semibold text-white">{matrix?.provider ?? "Awaiting generation"}</div>
          </div>
          <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
            <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Status</div>
            <div className="mt-2 text-lg font-semibold text-white">{matrix?.status ?? "Blocked"}</div>
          </div>
        </div>
      </Card>

      <div className="space-y-5">
        <Card className="p-6">
          <div className="text-lg font-semibold text-white">Distance matrix preview</div>
          <MatrixGrid values={previewDistance} emptyMessage="Generate a matrix to inspect distance values." />
        </Card>
        <Card className="p-6">
          <div className="text-lg font-semibold text-white">Time matrix preview</div>
          <MatrixGrid values={previewTime} emptyMessage="Generate a matrix to inspect travel-time values." />
        </Card>
      </div>
    </div>
  );
}

function MatrixGrid({ values, emptyMessage }: { values: number[][]; emptyMessage: string }) {
  if (!values.length) {
    return <div className="mt-4 text-sm text-slate-400">{emptyMessage}</div>;
  }
  return (
    <div className="mt-4 overflow-hidden rounded-[22px] border border-white/10">
      {values.map((row, rowIndex) => (
        <div key={rowIndex} className="grid grid-cols-5 divide-x divide-white/10 border-b border-white/10 last:border-b-0">
          {row.map((value, valueIndex) => (
            <div key={`${rowIndex}-${valueIndex}`} className="px-3 py-3 text-sm text-slate-300">
              {value.toFixed(2)}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
