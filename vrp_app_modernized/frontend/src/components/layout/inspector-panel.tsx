import { Database, FolderKanban, Radar, Route } from "lucide-react";
import type { MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function InspectorPanel({
  project,
  matrix,
  currentSolution,
}: {
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentSolution: SolutionResponse | null;
}) {
  return (
    <Card className="h-full rounded-[30px] p-5">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-lg font-semibold text-white">Inspector</div>
          <div className="mt-1 break-words text-sm text-slate-400">Persistent workspace metadata and docked details.</div>
        </div>
        <Badge className="border-white/10 bg-white/[0.04] text-slate-300">Docked</Badge>
      </div>

      <div className="space-y-4">
        <InspectorBlock
          icon={FolderKanban}
          title="Project"
          lines={
            project
              ? [project.name, `${project.addresses.length} addresses`, `${project.fleet_units.length} fleet profiles`]
              : ["No project loaded", "Create or load workspace snapshot"]
          }
        />
        <InspectorBlock
          icon={Database}
          title="Matrix"
          lines={matrix ? [`${matrix.size} x ${matrix.size}`, `Provider: ${matrix.provider}`, `Status: ${matrix.status}`] : ["No matrix generated yet"]}
        />
        <InspectorBlock
          icon={Route}
          title="Solution"
          lines={
            currentSolution
              ? [`Solver: ${currentSolution.solver_key}`, `${currentSolution.routes.length} routes persisted`, `Created: ${new Date(currentSolution.created_at).toLocaleString()}`]
              : ["No persisted solution loaded"]
          }
        />
        <InspectorBlock
          icon={Radar}
          title="Desktop notes"
          lines={[
            "Ctrl+B toggle sidebar",
            "Ctrl+\\ toggle inspector",
            "Ctrl+Shift+M toggle monitor",
            "Ctrl+Shift+S save workspace",
            "Ctrl+4 compare latest solutions",
          ]}
        />
      </div>
    </Card>
  );
}

function InspectorBlock({
  icon: Icon,
  title,
  lines,
}: {
  icon: typeof FolderKanban;
  title: string;
  lines: string[];
}) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-white/[0.05] text-accent">
          <Icon size={16} />
        </div>
        <div className="text-sm font-medium text-white">{title}</div>
      </div>
      <div className="mt-3 space-y-2">
        {lines.map((line) => (
          <div key={line} className="break-words text-sm text-slate-400">
            {line}
          </div>
        ))}
      </div>
    </div>
  );
}
