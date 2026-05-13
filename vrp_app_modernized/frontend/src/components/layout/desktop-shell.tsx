import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Download, FolderOpen, Import, Menu, PanelRightClose, PanelRightOpen, Save, Trash2, WandSparkles, X } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { mergeAlgorithmParameters } from "@/lib/algorithm-parameters";
import { browserFileSystemAdapter } from "@/lib/filesystem";
import { pathToView, viewPathMap } from "@/lib/routes";
import type { HealthResponse, JobResponse, MatrixResponse, ProjectBundle, ProjectRecord, ProjectSavePayload, ProjectSummary, SolutionResponse } from "@/types/api";
import type { WorkspaceSnapshot } from "@/types/workspace";
import { CommandPalette } from "@/components/layout/command-palette";
import { FloatingMonitor } from "@/components/layout/floating-monitor";
import { InspectorPanel } from "@/components/layout/inspector-panel";
import { Navbar } from "@/components/layout/navbar";
import { SettingsModal } from "@/components/layout/settings-modal";
import { Sidebar } from "@/components/layout/sidebar";
import { SplitLayout } from "@/components/layout/split-layout";
import { WorkspaceTabs } from "@/components/layout/workspace-tabs";
import { ToastStack } from "@/components/dashboard/toast-stack";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

type ShellProps = {
  children: React.ReactNode;
  paletteOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (value: boolean | ((prev: boolean) => boolean)) => void;
  inspectorOpen: boolean;
  setInspectorOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  inspectorWidth: number;
  setInspectorWidth: (value: number) => void;
  monitorOpen: boolean;
  setMonitorOpen: (value: boolean | ((prev: boolean) => boolean)) => void;
  health: HealthResponse | null;
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentJob: JobResponse | null;
  currentJobId: string | null;
  currentSolution: SolutionResponse | null;
  toasts: { id: number; title: string; body: string }[];
  pushToast: (title: string, body: string) => void;
  setProject: (project: ProjectRecord | null) => void;
  setMatrix: (matrix: MatrixResponse | null) => void;
  setCurrentJobId: (jobId: string | null) => void;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
};

export function DesktopShell(props: ShellProps) {
  const {
    children,
    paletteOpen,
    setPaletteOpen,
    sidebarCollapsed,
    setSidebarCollapsed,
    inspectorOpen,
    setInspectorOpen,
    inspectorWidth,
    setInspectorWidth,
    monitorOpen,
    setMonitorOpen,
    health,
    project,
    matrix,
    currentJob,
    currentJobId,
    currentSolution,
    toasts,
    pushToast,
    setProject,
    setMatrix,
    setCurrentJobId,
    setCurrentSolution,
  } = props;
  const navigate = useNavigate();
  const location = useLocation();
  const activeView = useMemo(() => pathToView(location.pathname), [location.pathname]);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [projectLibraryOpen, setProjectLibraryOpen] = useState(false);
  const [projectLibrary, setProjectLibrary] = useState<ProjectSummary[]>([]);
  const [libraryLoading, setLibraryLoading] = useState(false);
  const [pendingDeleteProject, setPendingDeleteProject] = useState<ProjectSummary | null>(null);

  const currentFocus = {
    workflow: "Desktop workflow workspace with local save/load and persistent inspector",
    matrix: "Matrix lab inside a docked software-style shell",
    optimize: "Optimization command center with persistent floating monitor",
    compare: "Solver comparison studio with side-by-side persisted result review",
  }[activeView];

  const saveWorkspace = useCallback(async () => {
    const snapshot: WorkspaceSnapshot = {
      exported_at: new Date().toISOString(),
      version: 1,
      project,
      matrix,
      currentJobId,
      currentSolution,
    };
    await browserFileSystemAdapter.saveWorkspace(snapshot);
    pushToast("Workspace saved", "Local workspace snapshot exported to JSON.");
  }, [currentJobId, currentSolution, matrix, project, pushToast]);

  const buildProjectSavePayload = useCallback((): ProjectSavePayload | null => {
    if (!project) return null;
    return {
      project_id: project.id,
      project: {
        name: project.name,
        description: project.description ?? undefined,
        settings: project.settings,
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
          max_route_distance_km: item.max_route_distance_km ?? null,
          max_route_time_min: item.max_route_time_min ?? null,
        })),
      },
      matrix,
      solutions: currentSolution ? [currentSolution] : [],
      jobs: currentJob ? [currentJob] : [],
      include_google_api_key: false,
    };
  }, [currentJob, currentSolution, matrix, project]);

  useEffect(() => {
    const handleSave = () => {
      void saveWorkspace();
    };
    window.addEventListener("pulseroute:save-workspace", handleSave as EventListener);
    return () => window.removeEventListener("pulseroute:save-workspace", handleSave as EventListener);
  }, [saveWorkspace]);

  const loadWorkspace = async () => {
    const snapshot = await browserFileSystemAdapter.loadWorkspace();
    if (!snapshot) return;
    setProject(snapshot.project);
    setMatrix(snapshot.matrix);
    setCurrentJobId(snapshot.currentJobId);
    setCurrentSolution(snapshot.currentSolution);
    pushToast("Workspace loaded", "Local snapshot restored into desktop shell.");
  };

  const saveProject = async () => {
    const payload = buildProjectSavePayload();
    if (!payload) {
      pushToast("Nothing to save", "Create or load a project first.");
      return;
    }
    try {
      const saved = await api.saveProject(payload);
      setProject(saved);
      pushToast("Project saved", "Current project state was persisted to the local backend database.");
    } catch (error) {
      pushToast("Project save failed", error instanceof Error ? error.message : "Could not save the project.");
    }
  };

  const openProjectLibrary = async () => {
    try {
      setLibraryLoading(true);
      const items = await api.listProjects();
      setProjectLibrary(items);
      setProjectLibraryOpen(true);
    } catch (error) {
      pushToast("Load failed", error instanceof Error ? error.message : "Could not load saved projects.");
    } finally {
      setLibraryLoading(false);
    }
  };

  const applyBundle = (bundle: ProjectBundle, warning?: string) => {
    const mergedSettings = {
      ...bundle.project.settings,
      algorithm_parameters: mergeAlgorithmParameters(bundle.project.settings),
    };
    const lastJob = bundle.jobs[0] ?? null;
    const lastSolution = bundle.solutions[0] ?? null;
    setProject({ ...bundle.project, settings: mergedSettings });
    setMatrix(bundle.matrix);
    setCurrentJobId(lastJob?.id ?? null);
    setCurrentSolution(lastSolution);
    if (warning) {
      pushToast("Project loaded with defaults", warning);
    } else {
      pushToast("Project loaded", "Saved project state was restored into the desktop app.");
    }
  };

  const loadProjectFromLibrary = async (projectId: string) => {
    if (project && !window.confirm("Loading another project will replace the current in-memory workspace. Continue?")) {
      return;
    }
    try {
      const bundle = await api.exportProject(projectId);
      const hadParams =
        Boolean(((bundle.project.settings?.algorithm_parameters ?? {}) as { bloodhound?: unknown }).bloodhound) &&
        Boolean(((bundle.project.settings?.algorithm_parameters ?? {}) as { nsga2?: unknown }).nsga2);
      applyBundle(bundle, hadParams ? undefined : "Missing algorithm parameters were filled with safe defaults.");
      setProjectLibraryOpen(false);
    } catch (error) {
      pushToast("Project load failed", error instanceof Error ? error.message : "Could not load saved project.");
    }
  };

  const deleteProjectFromLibrary = async () => {
    if (!pendingDeleteProject) return;
    const target = pendingDeleteProject;
    setPendingDeleteProject(null);
    try {
      await api.deleteProject(target.id);
      setProjectLibrary((items) => items.filter((item) => item.id !== target.id));
      if (project?.id === target.id) {
        setProject(null);
        setMatrix(null);
        setCurrentJobId(null);
        setCurrentSolution(null);
      }
      pushToast("Project deleted", `${target.name} was removed from local project storage.`);
    } catch (error) {
      pushToast("Delete failed", error instanceof Error ? error.message : "Could not delete the project.");
    }
  };

  const exportProjectJson = async () => {
    if (!project) {
      pushToast("Nothing to export", "Create or load a project first.");
      return;
    }
    try {
      const bundle = await api.exportProject(project.id);
      const filename = `pulseroute-project-${project.name.toLowerCase().replace(/[^a-z0-9]+/gi, "-") || project.id}.json`;
      await browserFileSystemAdapter.exportProjectBundle(filename, bundle);
      pushToast("Project exported", "Project bundle exported to JSON.");
    } catch (error) {
      pushToast("Export failed", error instanceof Error ? error.message : "Could not export project JSON.");
    }
  };

  const importProjectJson = async () => {
    try {
      if (project && !window.confirm("Importing a project will replace the current in-memory workspace. Continue?")) {
        return;
      }
      const bundle = await browserFileSystemAdapter.importProjectBundle();
      if (!bundle) return;
      const addressCount = bundle.project.addresses.length;
      if (bundle.matrix && bundle.matrix.size !== addressCount) {
        throw new Error(`Imported matrix size ${bundle.matrix.size} does not match address count ${addressCount}.`);
      }
      const hadParams =
        Boolean(((bundle.project.settings?.algorithm_parameters ?? {}) as { bloodhound?: unknown }).bloodhound) &&
        Boolean(((bundle.project.settings?.algorithm_parameters ?? {}) as { nsga2?: unknown }).nsga2);
      const imported = await api.importProject({
        ...bundle,
        project: {
          ...bundle.project,
          settings: {
            ...bundle.project.settings,
            algorithm_parameters: mergeAlgorithmParameters(bundle.project.settings),
          },
        },
      });
      const hydrated = await api.exportProject(imported.id);
      applyBundle(hydrated, hadParams ? undefined : "Missing algorithm parameters were filled with safe defaults.");
    } catch (error) {
      pushToast("Import failed", error instanceof Error ? error.message : "Could not import project JSON.");
    }
  };

  const refreshJob = async () => {
    if (!currentJobId) return;
    try {
      const job = await api.getJob(currentJobId);
      if (job.solution_id) {
        const solution = await api.getSolution(job.solution_id);
        setCurrentSolution(solution);
      }
      pushToast("Monitor refreshed", "Latest backend job state pulled into desktop shell.");
    } catch (error) {
      pushToast("Refresh failed", error instanceof Error ? error.message : "Could not refresh job state.");
    }
  };

  return (
    <div className="min-h-screen px-4 py-4 md:px-6">
      <div className="mx-auto flex max-w-[1820px] items-start gap-4">
        <Sidebar
          active={activeView}
          onChange={(view) => navigate(viewPathMap[view])}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed((value) => !value)}
        />

        <div className="min-w-0 flex-1 space-y-4">
          <div className="flex items-center justify-between xl:hidden">
            <button
              onClick={() => setSidebarCollapsed((value) => !value)}
              className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-slate-300"
            >
              <Menu size={18} />
            </button>
            <div className="text-sm font-semibold text-white">PulseRoute OS</div>
          </div>

          <Navbar
            onCommandOpen={() => setPaletteOpen(true)}
            healthLabel={health ? `${health.app} ${health.status}` : "Backend not connected"}
            onSettingsOpen={() => setSettingsOpen(true)}
          />

          <WorkspaceTabs active={activeView} onChange={(view) => navigate(viewPathMap[view])} />

          <Card className="grid gap-4 overflow-hidden xl:grid-cols-[minmax(320px,1fr)_auto] xl:items-start">
            <div className="min-w-0">
              <div className="text-sm uppercase tracking-[0.22em] text-slate-500">Current focus</div>
              <div className="mt-2 text-xl font-semibold text-white xl:break-words">{currentFocus}</div>
              {project && (
                <div className="mt-2 text-sm text-slate-400">
                  Project: <span className="text-slate-200">{project.name}</span>
                  {"  "}Last saved: <span className="text-slate-200">{new Date(project.updated_at).toLocaleString()}</span>
                </div>
              )}
            </div>
            <div className="flex flex-wrap gap-3 xl:max-w-[980px] xl:justify-end">
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={saveProject}>
                <Save size={16} />
                Save Project
              </Button>
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={openProjectLibrary} disabled={libraryLoading}>
                <FolderOpen size={16} />
                Load Project
              </Button>
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={exportProjectJson}>
                <Download size={16} />
                Export Project JSON
              </Button>
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={importProjectJson}>
                <Import size={16} />
                Import Project JSON
              </Button>
              <Button variant="ghost" className="gap-2 whitespace-normal text-center" onClick={loadWorkspace}>
                <FolderOpen size={16} />
                Load workspace
              </Button>
              <Button variant="ghost" className="gap-2 whitespace-normal text-center" onClick={saveWorkspace}>
                <Save size={16} />
                Save workspace
              </Button>
              <Button className="gap-2 whitespace-normal text-center" disabled={!project || !matrix}>
                <WandSparkles size={16} />
                Ready after matrix
              </Button>
              <Button variant="ghost" className="gap-2 whitespace-normal text-center" onClick={() => setInspectorOpen((value) => !value)}>
                {inspectorOpen ? <PanelRightClose size={16} /> : <PanelRightOpen size={16} />}
                Inspector
              </Button>
            </div>
          </Card>

          <SplitLayout
            showRight={inspectorOpen}
            rightWidth={inspectorWidth}
            setRightWidth={setInspectorWidth}
            left={children}
            right={<InspectorPanel project={project} matrix={matrix} currentSolution={currentSolution} />}
          />
        </div>
      </div>

      {currentJobId && (
        <div className="fixed bottom-6 left-6 z-40 flex gap-3">
          <Button className="h-14 w-14 rounded-full p-0 shadow-[0_18px_55px_rgba(87,230,255,0.25)]" onClick={() => navigate(viewPathMap.workflow)}>
            +
          </Button>
          <Button variant="secondary" className="gap-2" onClick={() => setMonitorOpen((value) => !value)}>
            {monitorOpen ? "Hide Monitor" : "Show Monitor"}
          </Button>
          <Button variant="secondary" className="gap-2" onClick={refreshJob}>
            Refresh Job
          </Button>
        </div>
      )}

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} onSelect={(view) => navigate(viewPathMap[view])} />
      <ProjectLibraryModal
        open={projectLibraryOpen}
        loading={libraryLoading}
        projects={projectLibrary}
        onClose={() => setProjectLibraryOpen(false)}
        onSelect={loadProjectFromLibrary}
        onDelete={(item) => setPendingDeleteProject(item)}
      />
      <ConfirmProjectDeleteModal
        open={pendingDeleteProject != null}
        projectName={pendingDeleteProject?.name ?? ""}
        onCancel={() => setPendingDeleteProject(null)}
        onConfirm={() => void deleteProjectFromLibrary()}
      />
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} onToast={pushToast} />
      <FloatingMonitor job={currentJob} open={monitorOpen} onClose={() => setMonitorOpen(false)} />
      <ToastStack toasts={toasts} />
    </div>
  );
}

function ProjectLibraryModal({
  open,
  loading,
  projects,
  onClose,
  onSelect,
  onDelete,
}: {
  open: boolean;
  loading: boolean;
  projects: ProjectSummary[];
  onClose: () => void;
  onSelect: (projectId: string) => void;
  onDelete: (project: ProjectSummary) => void;
}) {
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
            initial={{ opacity: 0, y: 24, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            className="fixed left-1/2 top-20 z-50 w-[min(760px,calc(100%-2rem))] -translate-x-1/2 rounded-[30px] border border-white/10 bg-[#09111f]/95 p-5 shadow-panel backdrop-blur-2xl"
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-lg font-semibold text-white">Saved Projects</div>
                <div className="text-sm text-slate-400">Load a persisted VRP project with addresses, fleet, matrices, parameters, results, and logs.</div>
              </div>
              <Button variant="ghost" className="px-3" onClick={onClose}>
                <X size={16} />
              </Button>
            </div>
            <div className="mt-5 space-y-3">
              {loading ? (
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-300">Loading saved projects...</div>
              ) : projects.length === 0 ? (
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4 text-sm text-slate-300">No saved projects found yet.</div>
              ) : (
                projects.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-start justify-between gap-4 rounded-[24px] border border-white/10 bg-white/[0.03] px-4 py-4 transition hover:border-accent/20 hover:bg-white/[0.05]"
                  >
                    <button onClick={() => onSelect(item.id)} className="min-w-0 flex-1 text-left">
                      <div className="text-sm font-medium text-white">{item.name}</div>
                      <div className="mt-1 break-words text-xs text-slate-500">{item.description || "No description"}</div>
                    </button>
                    <div className="flex items-start gap-3">
                      <div className="text-right text-xs text-slate-400">
                        <div>{item.status}</div>
                        <div className="mt-1">{new Date(item.updated_at).toLocaleString()}</div>
                      </div>
                      <Button variant="ghost" className="px-3 py-2" onClick={() => onDelete(item)}>
                        <Trash2 size={16} />
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

function ConfirmProjectDeleteModal({
  open,
  projectName,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  projectName: string;
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
            <div className="text-lg font-semibold text-white">Delete saved project</div>
            <div className="mt-2 text-sm leading-6 text-slate-400">
              Delete <span className="text-slate-200">{projectName}</span> from local project storage? This removes the saved project bundle, including matrices, solutions, and logs.
            </div>
            <div className="mt-5 flex justify-end gap-3">
              <Button variant="secondary" onClick={onCancel}>
                Cancel
              </Button>
              <Button onClick={onConfirm} className="gap-2">
                <Trash2 size={16} />
                Delete Project
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
