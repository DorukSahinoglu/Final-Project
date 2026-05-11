import { useMemo, useState } from "react";
import { LoaderCircle, MapPinned, Plus, Save, ScanSearch } from "lucide-react";
import { api } from "@/lib/api";
import type { MatrixResponse, ProjectRecord } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

type ProjectWorkflowProps = {
  project: ProjectRecord | null;
  setProject: (project: ProjectRecord) => void;
  matrix: MatrixResponse | null;
  setMatrix: (matrix: MatrixResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

type DraftAddress = {
  label: string;
  address_line: string;
  demand: number;
  is_depot: boolean;
};

const initialAddresses: DraftAddress[] = [
  { label: "Main Depot", address_line: "", demand: 0, is_depot: true },
  { label: "Customer 1", address_line: "", demand: 1, is_depot: false },
  { label: "Customer 2", address_line: "", demand: 1, is_depot: false },
];

export function ProjectWorkflow({ project, setProject, matrix, setMatrix, onToast }: ProjectWorkflowProps) {
  const [name, setName] = useState("Istanbul Distribution Run");
  const [description, setDescription] = useState("Starter scenario for route optimization.");
  const [addresses, setAddresses] = useState<DraftAddress[]>(initialAddresses);
  const [loadingState, setLoadingState] = useState<"" | "project" | "geocode" | "matrix">("");
  const [error, setError] = useState<string | null>(null);
  const [speedKmh, setSpeedKmh] = useState(35);

  const readiness = useMemo(() => {
    const total = 3;
    const done =
      (project ? 1 : 0) +
      (project && project.addresses.every((item) => item.geocode_status === "ready") ? 1 : 0) +
      (matrix ? 1 : 0);
    return Math.round((done / total) * 100);
  }, [matrix, project]);

  const createProject = async () => {
    try {
      setLoadingState("project");
      setError(null);
      const created = await api.createProject({
        name,
        description,
        addresses: addresses.filter((item) => item.address_line.trim()),
        fleet_units: [
          {
            vehicle_type_id: "standard-van",
            label: "Standard Van",
            count: 3,
            capacity: 25,
            fixed_cost: 45,
            cost_per_km: 18,
            speed_kmh: speedKmh,
          },
        ],
      });
      setProject(created);
      setMatrix(null);
      onToast("Project saved", "Backend project created successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project creation failed.");
    } finally {
      setLoadingState("");
    }
  };

  const geocodeAll = async () => {
    if (!project) return;
    try {
      setLoadingState("geocode");
      setError(null);
      await api.geocodeProject(project.id);
      const refreshed = await api.getProject(project.id);
      setProject(refreshed);
      onToast("Geocoding complete", "Address coordinates refreshed from backend.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Geocoding failed.");
    } finally {
      setLoadingState("");
    }
  };

  const generateMatrix = async () => {
    if (!project) return;
    try {
      setLoadingState("matrix");
      setError(null);
      const nextMatrix = await api.generateMatrix(project.id, speedKmh);
      setMatrix(nextMatrix);
      onToast("Matrix ready", "Distance and time matrix generated successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Matrix generation failed.");
    } finally {
      setLoadingState("");
    }
  };

  return (
    <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
      <Card className="p-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="text-lg font-semibold text-white">Project bootstrap</div>
            <div className="mt-1 text-sm text-slate-400">Create a real backend project, then geocode and generate a matrix.</div>
          </div>
          <Badge className="border-accent/20 bg-accent/10 text-accent">{readiness}% ready</Badge>
        </div>

        <div className="mt-5 space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Project name</div>
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </div>
            <div>
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Baseline speed km/h</div>
              <Input type="number" value={speedKmh} onChange={(event) => setSpeedKmh(Number(event.target.value))} />
            </div>
          </div>

          <div>
            <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Description</div>
            <Input value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>

          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-white">Addresses</div>
              <Button
                variant="ghost"
                className="gap-2"
                onClick={() =>
                  setAddresses((items) => [...items, { label: `Customer ${items.length}`, address_line: "", demand: 1, is_depot: false }])
                }
              >
                <Plus size={14} />
                Add stop
              </Button>
            </div>

            {addresses.map((address, index) => (
              <div key={`${address.label}-${index}`} className="grid gap-3 rounded-[24px] border border-white/10 bg-white/[0.03] p-4 md:grid-cols-[140px_1fr_90px]">
                <Input
                  value={address.label}
                  onChange={(event) =>
                    setAddresses((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, label: event.target.value } : item)))
                  }
                />
                <Input
                  value={address.address_line}
                  placeholder={address.is_depot ? "Depot address" : "Customer address"}
                  onChange={(event) =>
                    setAddresses((items) =>
                      items.map((item, itemIndex) => (itemIndex === index ? { ...item, address_line: event.target.value } : item)),
                    )
                  }
                />
                <Input
                  type="number"
                  value={address.demand}
                  onChange={(event) =>
                    setAddresses((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, demand: Number(event.target.value) } : item)))
                  }
                />
              </div>
            ))}
          </div>
        </div>

        {error && <div className="mt-4 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div>}

        <div className="mt-6 flex flex-wrap gap-3">
          <Button onClick={createProject} disabled={loadingState !== ""} className="gap-2">
            {loadingState === "project" ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
            Save project
          </Button>
          <Button onClick={geocodeAll} variant="secondary" disabled={!project || loadingState !== ""} className="gap-2">
            {loadingState === "geocode" ? <LoaderCircle size={16} className="animate-spin" /> : <MapPinned size={16} />}
            Geocode all
          </Button>
          <Button onClick={generateMatrix} variant="secondary" disabled={!project || loadingState !== ""} className="gap-2">
            {loadingState === "matrix" ? <LoaderCircle size={16} className="animate-spin" /> : <ScanSearch size={16} />}
            Generate matrix
          </Button>
        </div>
      </Card>

      <Card className="p-6">
        <div className="text-lg font-semibold text-white">Workflow status</div>
        <div className="mt-1 text-sm text-slate-400">Only active backend-supported steps remain enabled.</div>
        <Progress value={readiness} className="mt-5" />

        <div className="mt-5 space-y-4">
          {[
            { label: "Project created", ready: Boolean(project), detail: project ? project.name : "Not created yet" },
            {
              label: "Addresses geocoded",
              ready: Boolean(project && project.addresses.length > 0 && project.addresses.every((item) => item.geocode_status === "ready")),
              detail: project ? `${project.addresses.filter((item) => item.geocode_status === "ready").length}/${project.addresses.length} ready` : "Waiting for project",
            },
            { label: "Matrix generated", ready: Boolean(matrix), detail: matrix ? `${matrix.size} x ${matrix.size} via ${matrix.provider}` : "No matrix yet" },
          ].map((step) => (
            <div key={step.label} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-white">{step.label}</div>
                <Badge className={step.ready ? "border-success/20 bg-success/10 text-success" : "border-white/10 bg-white/[0.04] text-slate-400"}>
                  {step.ready ? "Ready" : "Waiting"}
                </Badge>
              </div>
              <div className="mt-2 text-sm text-slate-400">{step.detail}</div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
