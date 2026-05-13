import { useEffect, useMemo, useRef, useState, type Dispatch, type ReactNode, type SetStateAction } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  FileUp,
  LoaderCircle,
  MapPinned,
  PackageOpen,
  Plus,
  Save,
  ScanSearch,
  Sparkles,
  Trash2,
} from "lucide-react";
import { api } from "@/lib/api";
import { detectFleetType, findDuplicateValues, projectValidation } from "@/lib/vrp";
import { sampleProject } from "@/data/sample-project";
import type { AddressInput, FleetUnitInput, MatrixLoadJsonPayload, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";

type ProjectWorkflowProps = {
  project: ProjectRecord | null;
  setProject: (project: ProjectRecord) => void;
  matrix: MatrixResponse | null;
  setMatrix: (matrix: MatrixResponse | null) => void;
  setCurrentJobId: (jobId: string | null) => void;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

type DraftAddress = AddressInput & {
  id?: string;
  geocode_status?: string;
  geocode_provider?: string | null;
};

type DraftFleet = FleetUnitInput & {
  id?: string;
};

const emptyAddress = (index: number): DraftAddress => ({
  label: `Customer ${index + 1}`,
  address_line: "",
  demand: 1,
  is_depot: false,
  latitude: null,
  longitude: null,
  time_window_start_min: null,
  time_window_end_min: null,
  notes: "",
  geocode_status: "pending",
});

const emptyFleet = (index: number): DraftFleet => ({
  vehicle_type_id: `vehicle-${index + 1}`,
  label: index === 0 ? "Standard Van" : `Vehicle ${index + 1}`,
  count: 1,
  capacity: 10,
  fixed_cost: 45,
  cost_per_km: 8,
  speed_kmh: 35,
});

export function ProjectWorkflow({
  project,
  setProject,
  matrix,
  setMatrix,
  setCurrentJobId,
  setCurrentSolution,
  onToast,
}: ProjectWorkflowProps) {
  const csvInputRef = useRef<HTMLInputElement | null>(null);
  const matrixJsonInputRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState(sampleProject.name);
  const [description, setDescription] = useState(sampleProject.description ?? "");
  const [addresses, setAddresses] = useState<DraftAddress[]>(sampleProject.addresses);
  const [fleet, setFleet] = useState<DraftFleet[]>(sampleProject.fleet_units);
  const [loadingState, setLoadingState] = useState<"" | "project" | "geocode" | "matrix">("");
  const [error, setError] = useState<string | null>(null);
  const [matrixProgress, setMatrixProgress] = useState(0);
  const [csvPreview, setCsvPreview] = useState<DraftAddress[] | null>(null);
  const [pendingDeleteAddressIndex, setPendingDeleteAddressIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!project) return;
    setName(project.name);
    setDescription(project.description ?? "");
    setAddresses(project.addresses);
    setFleet(project.fleet_units);
  }, [project]);

  const fleetType = useMemo(() => detectFleetType(fleet), [fleet]);
  const duplicateLabels = useMemo(() => findDuplicateValues(addresses.map((item) => item.label)), [addresses]);
  const duplicateAddresses = useMemo(() => findDuplicateValues(addresses.map((item) => item.address_line)), [addresses]);
  const geocodedCount = useMemo(
    () => addresses.filter((item) => item.latitude != null && item.longitude != null).length,
    [addresses],
  );

  const draftProject = useMemo<ProjectRecord>(() => {
    return {
      id: project?.id ?? "draft-project",
      name,
      description,
      status: project?.status ?? "draft",
      settings: project?.settings ?? {},
      updated_at: project?.updated_at ?? new Date().toISOString(),
      addresses: addresses.map((item, index) => ({
        ...item,
        id: item.id ?? `draft-address-${index}`,
        geocode_status: item.geocode_status ?? (item.latitude != null && item.longitude != null ? "ready" : "pending"),
        geocode_provider: item.geocode_provider ?? null,
      })),
      fleet_units: fleet.map((item, index) => ({
        ...item,
        id: item.id ?? `draft-fleet-${index}`,
      })),
    };
  }, [addresses, description, fleet, name, project]);

  const validation = useMemo(() => projectValidation(draftProject, matrix), [draftProject, matrix]);
  const hasExistingProject = Boolean(project?.id);
  const matrixSourceLabel = matrix
    ? matrix.provider === "osrm"
      ? "OSRM generated"
      : matrix.provider === "json_import"
        ? "JSON imported"
        : matrix.provider
    : "Pending";

  const persistProject = async () => {
    try {
      setLoadingState("project");
      setError(null);
      const payload = {
        name,
        description,
        settings: {
          fleet_type: fleetType,
          updated_via: "desktop-workflow",
        },
        addresses: addresses.map(normalizeAddressPayload),
        fleet_units: fleet.map(normalizeFleetPayload),
      };
      const saved = hasExistingProject ? await api.updateProject(project!.id, payload) : await api.createProject(payload);
      setProject(saved);
      setMatrix(null);
      setCurrentJobId(null);
      setCurrentSolution(null);
      onToast(hasExistingProject ? "Project updated" : "Project created", "Address book and fleet state were saved to the backend.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Project save failed.");
    } finally {
      setLoadingState("");
    }
  };

  const geocodeAddresses = async () => {
    if (!project?.id) {
      const message = "Save the project first so geocoding has a real backend project to update.";
      console.warn("[workflow] geocode blocked:", message);
      setError(message);
      onToast("Save project first", message);
      return;
    }
    const pendingIds = addresses
      .filter((item) => item.latitude == null || item.longitude == null)
      .map((item) => item.id!)
      .filter(Boolean);
    if (pendingIds.length === 0) {
      onToast("Nothing to geocode", "All saved addresses already have coordinates.");
      return;
    }
    try {
      setLoadingState("geocode");
      setError(null);
      console.info("[workflow] geocode request", { projectId: project.id, addressCount: pendingIds.length });
      await api.geocodeProject(project.id, pendingIds);
      const refreshed = await api.getProject(project.id);
      setProject(refreshed);
      setAddresses(refreshed.addresses);
      onToast("Geocoding complete", `${refreshed.addresses.filter((item) => item.geocode_status === "ready").length} addresses now have coordinates.`);
    } catch (err) {
      console.error("[workflow] geocode failed", err);
      setError(err instanceof Error ? err.message : "Geocoding failed.");
      onToast("Geocoding failed", err instanceof Error ? err.message : "Geocoding failed.");
    } finally {
      setLoadingState("");
    }
  };

  const generateMatrix = async () => {
    if (!project?.id) {
      const message = "Save the project first so matrix generation can store a real backend snapshot.";
      console.warn("[workflow] matrix generation blocked:", message);
      setError(message);
      onToast("Save project first", message);
      return;
    }
    if (addresses.length <= 1) {
      const message = "Add a depot and at least one customer before generating a matrix.";
      setError(message);
      onToast("Matrix blocked", message);
      return;
    }
    const missingCoords = addresses.filter((item) => item.latitude == null || item.longitude == null).map((item) => item.label);
    if (missingCoords.length > 0) {
      const message = `Geocode all addresses first. Missing coordinates for: ${missingCoords.join(", ")}`;
      console.warn("[workflow] matrix generation blocked:", message);
      setError(message);
      onToast("Matrix blocked", message);
      return;
    }
    let timer: number | undefined;
    try {
      setLoadingState("matrix");
      setError(null);
      setMatrixProgress(8);
      timer = window.setInterval(() => {
        setMatrixProgress((value) => (value >= 88 ? value : value + 7));
      }, 180);
      console.info("[workflow] matrix generation request", { projectId: project.id, addressCount: addresses.length });
      const nextMatrix = await api.generateMatrix(project.id);
      setMatrixProgress(100);
      setMatrix(nextMatrix);
      onToast("Matrix generated", `${matrixSourceLabelFromResponse(nextMatrix)} matrix is ready for solver execution.`);
    } catch (err) {
      console.error("[workflow] matrix generation failed", err);
      setError(err instanceof Error ? err.message : "Matrix generation failed.");
      onToast("Matrix generation failed", err instanceof Error ? err.message : "Matrix generation failed.");
    } finally {
      if (timer) window.clearInterval(timer);
      window.setTimeout(() => setMatrixProgress(0), 500);
      setLoadingState("");
    }
  };

  const loadSample = () => {
    setName(sampleProject.name);
    setDescription(sampleProject.description ?? "");
    setAddresses(sampleProject.addresses);
    setFleet(sampleProject.fleet_units);
    setError(null);
    onToast("Sample loaded", "A demo-ready Istanbul scenario was loaded into the workspace.");
  };

  const onCsvPicked = async (file: File | null) => {
    if (!file) return;
    try {
      setError(null);
      const text = await file.text();
      const rows = parseCsvRows(text);
      if (rows.length === 0) {
        throw new Error("CSV is empty. Provide at least one depot row and one customer row.");
      }

      const firstRow = rows[0] ?? [];
      const hasHeader = looksLikeHeader(firstRow);
      const dataRows = hasHeader ? rows.slice(1) : rows;
      if (dataRows.length === 0) {
        throw new Error("CSV does not contain any address rows after the header.");
      }

      const rowErrors: string[] = [];
      const imported: DraftAddress[] = dataRows.map((cells, index) => {
        const name = (cells[0] ?? "").trim();
        const addressText = (cells[1] ?? "").trim();
        const rowNumber = hasHeader ? index + 2 : index + 1;

        if (!name) rowErrors.push(`Row ${rowNumber}: missing name/id in column 1.`);
        if (!addressText) rowErrors.push(`Row ${rowNumber}: missing address text in column 2.`);

        return {
          ...emptyAddress(addresses.length + index),
          label: name || `Imported ${index + 1}`,
          address_line: addressText,
          demand: index === 0 ? 0 : 1,
          is_depot: index === 0,
          geocode_status: "pending",
        } satisfies DraftAddress;
      });

      if (rowErrors.length > 0) {
        throw new Error(rowErrors.join(" "));
      }

      setCsvPreview(imported);
      onToast("CSV parsed", `${imported.length} rows are ready to import. Review and confirm below.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV import failed.");
      setCsvPreview(null);
      onToast("CSV import failed", err instanceof Error ? err.message : "CSV import failed.");
    } finally {
      if (csvInputRef.current) csvInputRef.current.value = "";
    }
  };

  const commitCsvImport = () => {
    if (!csvPreview || csvPreview.length === 0) return;
    setAddresses((items) => {
      const normalizedExisting = items.map((item) => ({ ...item, is_depot: false }));
      return [...normalizedExisting, ...csvPreview];
    });
    onToast("CSV imported", `${csvPreview.length} addresses were added to the project draft. The first imported row was marked as depot.`);
    setCsvPreview(null);
  };

  const cancelCsvImport = () => {
    setCsvPreview(null);
  };

  const onMatrixJsonPicked = async (file: File | null) => {
    if (!file || !project?.id) return;
    try {
      setLoadingState("matrix");
      setError(null);
      const text = await file.text();
      const parsed = JSON.parse(text) as Omit<MatrixLoadJsonPayload, "project_id"> | number[][];
      const payload = Array.isArray(parsed)
        ? { project_id: project.id, distance_matrix: parsed }
        : {
            project_id: project.id,
            distance_matrix: parsed.distance_matrix,
            time_matrix: parsed.time_matrix,
            node_ids: parsed.node_ids,
            address_ids: parsed.address_ids,
            metadata: parsed.metadata,
          };
      if (!payload.distance_matrix) {
        throw new Error("Matrix JSON must include at least distance_matrix.");
      }
      console.info("[workflow] matrix json load request", {
        projectId: project.id,
        hasTimeMatrix: Boolean("time_matrix" in payload && payload.time_matrix),
      });
      const loadedMatrix = await api.loadMatrixJson(payload);
      setMatrix(loadedMatrix);
      onToast("Matrix JSON loaded", `Imported ${loadedMatrix.size}x${loadedMatrix.size} matrix snapshot from file. Source: ${matrixSourceLabelFromResponse(loadedMatrix)}.`);
    } catch (err) {
      console.error("[workflow] matrix json load failed", err);
      setError(err instanceof Error ? err.message : "Matrix JSON import failed.");
      onToast("Matrix JSON import failed", err instanceof Error ? err.message : "Matrix JSON import failed.");
    } finally {
      setLoadingState("");
      if (matrixJsonInputRef.current) matrixJsonInputRef.current.value = "";
    }
  };

  const openMatrixJsonPicker = () => {
    if (loadingState !== "") return;
    if (!project?.id) {
      const message = "Save the project first before importing a matrix JSON file.";
      console.warn("[workflow] matrix picker blocked:", message);
      setError(message);
      onToast("Save project first", message);
      return;
    }
    matrixJsonInputRef.current?.click();
  };

  const requestDeleteAddress = (index: number) => {
    setPendingDeleteAddressIndex(index);
  };

  const confirmDeleteAddress = async () => {
    if (pendingDeleteAddressIndex == null) return;
    const index = pendingDeleteAddressIndex;
    const target = addresses[index];
    setPendingDeleteAddressIndex(null);
    if (!target) return;

    const nextAddresses = addresses
      .filter((_, itemIndex) => itemIndex !== index)
      .map((item, itemIndex, list) => ({
        ...item,
        is_depot: target.is_depot ? itemIndex === 0 : item.is_depot,
      }));

    if (nextAddresses.length === 0) {
      setError("At least one address must remain in the project.");
      onToast("Delete blocked", "At least one address must remain in the project.");
      return;
    }

    if (!project?.id) {
      setAddresses(nextAddresses);
      setMatrix(null);
      setCurrentJobId(null);
      setCurrentSolution(null);
      onToast("Address removed", target.is_depot ? "Depot deleted. The next address was promoted to depot and the matrix was cleared." : "Address removed from the draft and matrix state cleared.");
      return;
    }

    try {
      setLoadingState("project");
      setError(null);
      const saved = await api.updateProject(project.id, {
        name,
        description,
        settings: project.settings,
        addresses: nextAddresses.map(normalizeAddressPayload),
        fleet_units: fleet.map(normalizeFleetPayload),
      });
      setProject(saved);
      setAddresses(saved.addresses);
      setMatrix(null);
      setCurrentJobId(null);
      setCurrentSolution(null);
      onToast(
        "Address deleted",
        target.is_depot
          ? "Depot deleted. The next remaining address became the depot. Existing matrix and solution state were cleared."
          : "Address deleted. Existing matrix and solution state were cleared as outdated."
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Address deletion failed.");
      onToast("Delete failed", err instanceof Error ? err.message : "Address deletion failed.");
    } finally {
      setLoadingState("");
    }
  };

  const canSave = validation.errors.length === 0 && loadingState === "";
  const canGeocode = loadingState === "";
  const canGenerateMatrix = loadingState === "";

  return (
    <div className="space-y-5">
      <Card className="p-6">
        <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
          <div className="max-w-2xl">
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-accent/20 bg-accent/10 text-accent">
                <Sparkles size={18} />
              </div>
              <div>
                <div className="text-lg font-semibold text-white">Usable optimization workflow</div>
                <div className="mt-1 text-sm text-slate-400">
                  Save real fleets and addresses, geocode them with Google, generate an OSRM matrix or load JSON, then move directly into solver review.
                </div>
              </div>
            </div>
            <Progress value={validation.completeness} className="mt-5" />
          </div>
          <div className="flex flex-wrap gap-3">
            <Badge className="border-accent/20 bg-accent/10 text-accent">{fleetType}</Badge>
            <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{validation.completeness}% complete</Badge>
            <Button variant="secondary" className="gap-2" onClick={loadSample}>
              <Sparkles size={15} />
              Load sample
            </Button>
            <Button onClick={persistProject} disabled={!canSave} className="gap-2">
              {loadingState === "project" ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
              {hasExistingProject ? "Update project" : "Create project"}
            </Button>
          </div>
        </div>

        {(error || validation.errors.length > 0 || validation.warnings.length > 0) && (
          <div className="mt-5 grid gap-3 lg:grid-cols-2">
            <ValidationList title="Errors" tone="danger" items={error ? [error, ...validation.errors] : validation.errors} />
            <ValidationList title="Warnings" tone="warning" items={validation.warnings} />
          </div>
        )}
      </Card>

      <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
        <Card className="p-6">
          <SectionHeader
            title="Project profile"
            subtitle="Name, description, depot policy and backend persistence state."
            badge={project ? "Saved" : "Draft"}
          />
          <div className="mt-5 grid gap-4 md:grid-cols-2">
            <Field label="Project name">
              <Input value={name} onChange={(event) => setName(event.target.value)} />
            </Field>
            <Field label="Fleet mode">
              <div className="flex h-11 items-center rounded-2xl border border-white/10 bg-white/[0.03] px-4 text-sm text-slate-200">
                {fleetType === "homogeneous" ? "Homogeneous fleet detected" : "Heterogeneous fleet detected"}
              </div>
            </Field>
          </div>
          <Field label="Description" className="mt-4">
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="min-h-[110px] w-full rounded-[22px] border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-100 outline-none transition focus:border-accent/30"
            />
          </Field>

          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <Metric title="Addresses" value={String(addresses.length)} detail={`${geocodedCount}/${addresses.length} geocoded`} />
            <Metric title="Fleet units" value={String(fleet.reduce((sum, item) => sum + item.count, 0))} detail={`${fleet.length} vehicle profiles`} />
            <Metric title="Matrix" value={matrix ? "Ready" : "Pending"} detail={matrix ? `${matrixSourceLabel} ${matrix.size}x${matrix.size}` : "Generate after geocoding"} />
          </div>
        </Card>

        <Card className="p-6">
          <SectionHeader title="Backend actions" subtitle="Use real API actions only. No fake execution states remain." badge="Live" />
          <div className="mt-5 space-y-4">
            <div className="rounded-[24px] border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-300">
              Google API is used for geocoding only. Distance and time matrices are generated with OSRM.
            </div>
            <ActionRow
              title="Geocode addresses"
              description="Uses the saved Google Geocoding API key to turn address text into latitude and longitude."
              action={
                <Button onClick={geocodeAddresses} disabled={!canGeocode} variant="secondary" className="gap-2">
                  {loadingState === "geocode" ? <LoaderCircle size={16} className="animate-spin" /> : <MapPinned size={16} />}
                  Geocode addresses
                </Button>
              }
            />
            <ActionRow
              title="Generate distance/time matrix"
              description="Creates a real backend OSRM matrix snapshot from saved coordinates. No Google API is used here."
              action={
                <Button onClick={generateMatrix} disabled={!canGenerateMatrix} variant="secondary" className="gap-2">
                  {loadingState === "matrix" ? <LoaderCircle size={16} className="animate-spin" /> : <ScanSearch size={16} />}
                  Generate Matrix with OSRM
                </Button>
              }
            />
            <ActionRow
              title="Load matrix from JSON"
              description="Import a raw distance matrix or a distance+time matrix JSON file and use it exactly like a generated matrix."
              action={
                <>
                  <Button onClick={openMatrixJsonPicker} disabled={loadingState !== ""} variant="secondary" className="gap-2">
                    <PackageOpen size={16} />
                    Load Matrix JSON
                  </Button>
                  <input
                    ref={matrixJsonInputRef}
                    type="file"
                    accept=".json,application/json"
                    className="hidden"
                    onChange={(event) => void onMatrixJsonPicked(event.target.files?.[0] ?? null)}
                  />
                </>
              }
            />
            <AnimatePresence>
              {loadingState === "matrix" && (
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="rounded-[24px] border border-accent/20 bg-accent/10 p-4"
                >
                  <div className="flex items-center justify-between text-sm text-slate-200">
                    <span>Matrix generation progress</span>
                    <span>{matrixProgress}%</span>
                  </div>
                  <Progress value={matrixProgress} className="mt-3" />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </Card>
      </div>

      <Card className="p-6">
        <SectionHeader
          title="Address management"
          subtitle="Manual editing, CSV import, depot selection, demand validation, per-address geocoding state. CSV uses column 1 as name and column 2 as address."
          badge={`${addresses.length} rows`}
        />

        <div className="mt-5 flex flex-wrap gap-3">
          <Button variant="secondary" className="gap-2" onClick={() => setAddresses((items) => [...items, emptyAddress(items.length)])}>
            <Plus size={15} />
            Add address
          </Button>
          <Button variant="secondary" className="gap-2" onClick={() => csvInputRef.current?.click()}>
            <FileUp size={15} />
            Import CSV
          </Button>
          <input
            ref={csvInputRef}
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            onChange={(event) => void onCsvPicked(event.target.files?.[0] ?? null)}
          />
        </div>

        {matrix && (
          <div className="mt-5 rounded-[24px] border border-accent/20 bg-accent/10 p-4">
            <div className="text-sm font-medium text-white">Active matrix snapshot</div>
            <div className="mt-2 break-words text-sm text-slate-300">
              {matrixSourceLabel}. Google API is used only for geocoding. Distance and time matrices come from OSRM or imported JSON.
            </div>
          </div>
        )}

        <AnimatePresence>
          {csvPreview && (
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -8 }}
              className="mt-5 rounded-[28px] border border-accent/20 bg-accent/10 p-5"
            >
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-white">CSV import preview</div>
                  <div className="mt-1 text-sm text-slate-300">
                    First imported row will be the depot. Extra columns were ignored safely.
                  </div>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Button variant="secondary" onClick={cancelCsvImport}>
                    Cancel
                  </Button>
                  <Button onClick={commitCsvImport}>
                    Add Imported Rows
                  </Button>
                </div>
              </div>
              <div className="mt-4 overflow-x-auto rounded-[24px] border border-white/10">
                <table className="min-w-full divide-y divide-white/10 text-sm">
                  <thead className="bg-white/[0.03] text-slate-400">
                    <tr>
                      {["Type", "Name / ID", "Address", "Demand"].map((heading) => (
                        <th key={heading} className="px-3 py-3 text-left font-medium">
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/10 bg-[#09101c]/60">
                    {csvPreview.map((row, index) => (
                      <tr key={`csv-preview-${index}`}>
                        <td className="px-3 py-3">
                          <Badge className={row.is_depot ? "border-accent/20 bg-accent/10 text-accent" : "border-white/10 bg-white/[0.04] text-slate-300"}>
                            {row.is_depot ? "Depot" : "Customer"}
                          </Badge>
                        </td>
                        <td className="px-3 py-3 text-slate-100">{row.label}</td>
                        <td className="px-3 py-3 text-slate-300">{row.address_line}</td>
                        <td className="px-3 py-3 text-slate-300">{row.demand}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <div className="mt-5 overflow-x-auto rounded-[28px] border border-white/10">
          <table className="min-w-full divide-y divide-white/10 text-sm">
            <thead className="bg-white/[0.03] text-slate-400">
              <tr>
                {["Depot", "Label", "Address", "Demand", "Lat", "Lon", "Status", "Notes", ""].map((heading) => (
                  <th key={heading} className="px-3 py-3 text-left font-medium">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/10 bg-[#09101c]/60">
              {addresses.map((address, index) => (
                <tr key={address.id ?? `address-${index}`} className="align-top">
                  <td className="px-3 py-3">
                    <button
                      className={`rounded-full px-3 py-1 text-xs transition ${
                        address.is_depot ? "bg-accent/15 text-accent" : "bg-white/[0.05] text-slate-400"
                      }`}
                      onClick={() =>
                        setAddresses((items) => items.map((item, itemIndex) => ({ ...item, is_depot: itemIndex === index })))
                      }
                    >
                      {address.is_depot ? "Depot" : "Set"}
                    </button>
                  </td>
                  <td className="px-3 py-3">
                    <Input
                      value={address.label}
                      onChange={(event) => updateAddress(index, { label: event.target.value }, setAddresses)}
                    />
                  </td>
                  <td className="min-w-[260px] px-3 py-3">
                    <Input
                      value={address.address_line}
                      onChange={(event) => updateAddress(index, { address_line: event.target.value }, setAddresses)}
                    />
                  </td>
                  <td className="w-[100px] px-3 py-3">
                    <Input
                      type="number"
                      value={address.demand}
                      disabled={address.is_depot}
                      onChange={(event) => updateAddress(index, { demand: Number(event.target.value) }, setAddresses)}
                    />
                  </td>
                  <td className="w-[120px] px-3 py-3">
                    <Input
                      type="number"
                      value={address.latitude ?? ""}
                      onChange={(event) => updateAddress(index, { latitude: parseOptionalNumber(event.target.value) }, setAddresses)}
                    />
                  </td>
                  <td className="w-[120px] px-3 py-3">
                    <Input
                      type="number"
                      value={address.longitude ?? ""}
                      onChange={(event) => updateAddress(index, { longitude: parseOptionalNumber(event.target.value) }, setAddresses)}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <Badge className={statusClass(address.geocode_status ?? "pending")}>{address.geocode_status ?? "pending"}</Badge>
                  </td>
                  <td className="min-w-[220px] px-3 py-3">
                    <textarea
                      value={address.notes ?? ""}
                      onChange={(event) => updateAddress(index, { notes: event.target.value }, setAddresses)}
                      className="min-h-[64px] w-full rounded-[18px] border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-slate-100 outline-none transition focus:border-accent/30"
                    />
                  </td>
                  <td className="px-3 py-3">
                    <Button variant="ghost" className="px-3 py-2" onClick={() => requestDeleteAddress(index)}>
                      <Trash2 size={16} />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {(duplicateLabels.length > 0 || duplicateAddresses.length > 0) && (
          <div className="mt-4 flex flex-wrap gap-3">
            {duplicateLabels.length > 0 && <InlineWarning text={`Duplicate labels: ${duplicateLabels.join(", ")}`} />}
            {duplicateAddresses.length > 0 && <InlineWarning text={`Duplicate addresses: ${duplicateAddresses.join(", ")}`} />}
          </div>
        )}
      </Card>

      <Card className="p-6">
        <SectionHeader
          title="Fleet management"
          subtitle="Create homogeneous or heterogeneous fleets. Bloodhound uses this exactly as saved."
          badge={`${fleet.reduce((sum, item) => sum + item.count, 0)} vehicles`}
        />

        <div className="mt-5 flex flex-wrap gap-3">
          <Button variant="secondary" className="gap-2" onClick={() => setFleet((items) => [...items, emptyFleet(items.length)])}>
            <Plus size={15} />
            Add vehicle type
          </Button>
          <Badge className={fleetType === "homogeneous" ? "border-success/20 bg-success/10 text-success" : "border-warning/20 bg-warning/10 text-warning"}>
            {fleetType === "homogeneous" ? "NSGA-II available" : "NSGA-II locked"}
          </Badge>
        </div>

        <div className="mt-5 grid gap-4">
          {fleet.map((unit, index) => (
            <div key={unit.id ?? `fleet-${index}`} className="rounded-[26px] border border-white/10 bg-white/[0.03] p-4">
              <div className="grid gap-4 lg:grid-cols-7">
                <Field label="Vehicle type">
                  <Input value={unit.vehicle_type_id} onChange={(event) => updateFleet(index, { vehicle_type_id: event.target.value }, setFleet)} />
                </Field>
                <Field label="Label">
                  <Input value={unit.label} onChange={(event) => updateFleet(index, { label: event.target.value }, setFleet)} />
                </Field>
                <Field label="Count">
                  <Input type="number" value={unit.count} onChange={(event) => updateFleet(index, { count: Number(event.target.value) }, setFleet)} />
                </Field>
                <Field label="Capacity">
                  <Input type="number" value={unit.capacity} onChange={(event) => updateFleet(index, { capacity: Number(event.target.value) }, setFleet)} />
                </Field>
                <Field label="Fixed cost">
                  <Input type="number" value={unit.fixed_cost} onChange={(event) => updateFleet(index, { fixed_cost: Number(event.target.value) }, setFleet)} />
                </Field>
                <Field label="Variable cost">
                  <Input type="number" value={unit.cost_per_km} onChange={(event) => updateFleet(index, { cost_per_km: Number(event.target.value) }, setFleet)} />
                </Field>
                <Field label="Speed km/h">
                  <Input type="number" value={unit.speed_kmh} onChange={(event) => updateFleet(index, { speed_kmh: Number(event.target.value) }, setFleet)} />
                </Field>
              </div>
              <div className="mt-4 flex justify-end">
                <Button variant="ghost" className="gap-2" onClick={() => setFleet((items) => items.filter((_, itemIndex) => itemIndex !== index))}>
                  <Trash2 size={16} />
                  Remove
                </Button>
              </div>
            </div>
          ))}
        </div>
      </Card>
      <ConfirmDeleteModal
        open={pendingDeleteAddressIndex != null}
        title="Delete saved address"
        message={
          pendingDeleteAddressIndex != null && addresses[pendingDeleteAddressIndex]?.is_depot
            ? "You are deleting the current depot. The next remaining address will become the depot, and any existing matrix/solver state will be cleared."
            : "Delete this address from the project? Any existing matrix/solver state will be cleared because the address set changes."
        }
        confirmLabel="Delete Address"
        onCancel={() => setPendingDeleteAddressIndex(null)}
        onConfirm={() => void confirmDeleteAddress()}
      />
    </div>
  );
}

function SectionHeader({ title, subtitle, badge }: { title: string; subtitle: string; badge: string }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="text-lg font-semibold text-white">{title}</div>
        <div className="mt-1 break-words text-sm text-slate-400">{subtitle}</div>
      </div>
      <Badge className="max-w-full border-white/10 bg-white/[0.04] text-slate-300">{badge}</Badge>
    </div>
  );
}

function Field({
  label,
  children,
  className = "",
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">{label}</div>
      {children}
    </div>
  );
}

function Metric({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="min-w-0 rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="break-words text-xs uppercase tracking-[0.18em] text-slate-500">{title}</div>
      <div className="mt-2 break-words text-xl font-semibold leading-tight text-white">{value}</div>
      <div className="mt-2 break-words text-sm text-slate-400">{detail}</div>
    </div>
  );
}

function ValidationList({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "danger" | "warning";
  items: string[];
}) {
  if (items.length === 0) return null;
  const styles =
    tone === "danger"
      ? "border-danger/30 bg-danger/10 text-danger"
      : "border-warning/30 bg-warning/10 text-warning";
  return (
    <div className={`rounded-[24px] border p-4 ${styles}`}>
      <div className="flex items-center gap-2 text-sm font-medium">
        <AlertTriangle size={16} />
        {title}
      </div>
      <div className="mt-3 space-y-2 text-sm">
        {items.map((item) => (
          <div key={item} className="break-words">{item}</div>
        ))}
      </div>
    </div>
  );
}

function ActionRow({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action: ReactNode;
}) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="text-sm font-medium text-white">{title}</div>
          <div className="mt-1 break-words text-sm text-slate-400">{description}</div>
        </div>
        {action}
      </div>
    </div>
  );
}

function InlineWarning({ text }: { text: string }) {
  return (
    <div className="rounded-full border border-warning/30 bg-warning/10 px-4 py-2 text-sm text-warning">
      {text}
    </div>
  );
}

function statusClass(status: string) {
  if (status === "ready") return "border-success/20 bg-success/10 text-success";
  if (status === "failed") return "border-danger/20 bg-danger/10 text-danger";
  return "border-white/10 bg-white/[0.04] text-slate-300";
}

function parseOptionalNumber(value: string) {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeAddressPayload(item: DraftAddress) {
  return {
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
  };
}

function normalizeFleetPayload(item: DraftFleet) {
  return {
    id: item.id,
    vehicle_type_id: item.vehicle_type_id,
    label: item.label,
    count: item.count,
    capacity: item.capacity,
    fixed_cost: item.fixed_cost,
    cost_per_km: item.cost_per_km,
    speed_kmh: item.speed_kmh,
  };
}

function matrixSourceLabelFromResponse(matrix: MatrixResponse) {
  if (matrix.provider === "osrm") return "OSRM generated";
  if (matrix.provider === "json_import") return "JSON imported";
  return matrix.provider;
}

function updateAddress(index: number, patch: Partial<DraftAddress>, setAddresses: Dispatch<SetStateAction<DraftAddress[]>>) {
  setAddresses((items) =>
    items.map((item, itemIndex) => {
      if (itemIndex !== index) return item;
      const merged = { ...item, ...patch };
      if (merged.latitude != null && merged.longitude != null) {
        merged.geocode_status = "ready";
      } else if (merged.address_line.trim()) {
        merged.geocode_status = "pending";
      }
      return merged;
    }),
  );
}

function updateFleet(index: number, patch: Partial<DraftFleet>, setFleet: Dispatch<SetStateAction<DraftFleet[]>>) {
  setFleet((items) => items.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)));
}

function parseCsvRows(text: string) {
  const normalized = text.replace(/^\uFEFF/, "");
  const delimiter = detectCsvDelimiter(normalized);
  const rows: string[][] = [];
  let currentCell = "";
  let currentRow: string[] = [];
  let inQuotes = false;

  for (let index = 0; index < normalized.length; index += 1) {
    const char = normalized[index];
    const nextChar = normalized[index + 1];

    if (char === '"') {
      if (inQuotes && nextChar === '"') {
        currentCell += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === delimiter && !inQuotes) {
      currentRow.push(currentCell.trim());
      currentCell = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && nextChar === "\n") index += 1;
      currentRow.push(currentCell.trim());
      currentCell = "";
      if (currentRow.some((cell) => cell.length > 0)) rows.push(currentRow);
      currentRow = [];
      continue;
    }

    currentCell += char;
  }

  if (currentCell.length > 0 || currentRow.length > 0) {
    currentRow.push(currentCell.trim());
    if (currentRow.some((cell) => cell.length > 0)) rows.push(currentRow);
  }

  return rows;
}

function detectCsvDelimiter(text: string) {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? "";
  const commaCount = (firstLine.match(/,/g) ?? []).length;
  const semicolonCount = (firstLine.match(/;/g) ?? []).length;
  return semicolonCount > commaCount ? ";" : ",";
}

function looksLikeHeader(row: string[]) {
  const first = (row[0] ?? "").trim().toLowerCase();
  const second = (row[1] ?? "").trim().toLowerCase();
  const firstLooksLikeHeader = ["name", "customer", "customer/name/id", "id", "label"].includes(first);
  const secondLooksLikeHeader = ["address", "address text", "full address", "location"].includes(second);
  return firstLooksLikeHeader || secondLooksLikeHeader;
}

function ConfirmDeleteModal({
  open,
  title,
  message,
  confirmLabel,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.button
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onCancel}
            className="fixed inset-0 z-40 bg-slate-950/65 backdrop-blur-sm"
          />
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            className="fixed left-1/2 top-24 z-50 w-[min(560px,calc(100%-2rem))] -translate-x-1/2 rounded-[30px] border border-white/10 bg-[#09111f]/95 p-5 shadow-panel backdrop-blur-2xl"
          >
            <div className="text-lg font-semibold text-white">{title}</div>
            <div className="mt-2 text-sm leading-6 text-slate-400">{message}</div>
            <div className="mt-5 flex justify-end gap-3">
              <Button variant="secondary" onClick={onCancel}>
                Cancel
              </Button>
              <Button onClick={onConfirm} className="gap-2">
                <Trash2 size={16} />
                {confirmLabel}
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
