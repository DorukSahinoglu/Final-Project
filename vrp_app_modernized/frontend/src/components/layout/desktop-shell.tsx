import { useCallback, useEffect, useMemo, useState } from "react";
import { Download, FolderOpen, Menu, PanelRightClose, PanelRightOpen, Save, WandSparkles } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { browserFileSystemAdapter } from "@/lib/filesystem";
import { pathToView, viewPathMap } from "@/lib/routes";
import type { HealthResponse, JobResponse, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
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

          <Card className="flex flex-col gap-3 overflow-hidden md:flex-row md:items-start md:justify-between">
            <div className="min-w-0 flex-1">
              <div className="text-sm uppercase tracking-[0.22em] text-slate-500">Current focus</div>
              <div className="mt-2 break-words text-xl font-semibold text-white">{currentFocus}</div>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={loadWorkspace}>
                <FolderOpen size={16} />
                Load workspace
              </Button>
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" onClick={saveWorkspace}>
                <Save size={16} />
                Save workspace
              </Button>
              <Button variant="secondary" className="gap-2 whitespace-normal text-center" disabled>
                <Download size={16} />
                Export coming soon
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
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} onToast={pushToast} />
      <FloatingMonitor job={currentJob} open={monitorOpen} onClose={() => setMonitorOpen(false)} />
      <ToastStack toasts={toasts} />
    </div>
  );
}
