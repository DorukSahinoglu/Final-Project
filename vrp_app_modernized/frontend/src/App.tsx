import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Card } from "@/components/ui/card";
import { DesktopShell } from "@/components/layout/desktop-shell";
import { api } from "@/lib/api";
import { pathToView, viewPathMap } from "@/lib/routes";
import { useJobPolling } from "@/hooks/use-job-polling";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { useToast } from "@/hooks/use-toast";
import type { HealthResponse, MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";

const WorkflowScreen = lazy(() => import("@/screens/workflow-screen"));
const MatrixScreen = lazy(() => import("@/screens/matrix-screen"));
const OptimizeScreen = lazy(() => import("@/screens/optimize-screen"));
const CompareScreen = lazy(() => import("@/screens/compare-screen"));

function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useLocalStorage("pulseroute.sidebar-collapsed", false);
  const [inspectorOpen, setInspectorOpen] = useLocalStorage("pulseroute.inspector-open", true);
  const [inspectorWidth, setInspectorWidth] = useLocalStorage("pulseroute.inspector-width", 360);
  const [monitorOpen, setMonitorOpen] = useLocalStorage("pulseroute.monitor-open", true);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [matrix, setMatrix] = useState<MatrixResponse | null>(null);
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [currentSolution, setCurrentSolution] = useState<SolutionResponse | null>(null);
  const { toasts, pushToast, removeToast } = useToast();
  const { job: currentJob } = useJobPolling(currentJobId);

  useEffect(() => {
    api
      .health()
      .then((response) => setHealth(response))
      .catch(() => {
        pushToast("Backend offline", "Start FastAPI server to enable live workflow actions.");
      });
  }, [pushToast]);

  useEffect(() => {
    if (toasts.length === 0) return;
    const timer = window.setTimeout(() => removeToast(toasts[0].id), 4200);
    return () => window.clearTimeout(timer);
  }, [removeToast, toasts]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      if (mod && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
      }
      if (mod && event.key.toLowerCase() === "b") {
        event.preventDefault();
        setSidebarCollapsed((value) => !value);
      }
      if (mod && event.key === "\\") {
        event.preventDefault();
        setInspectorOpen((value) => !value);
      }
      if (mod && event.shiftKey && event.key.toLowerCase() === "m") {
        event.preventDefault();
        setMonitorOpen((value) => !value);
      }
      if (mod && event.shiftKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        const shellSaveEvent = new CustomEvent("pulseroute:save-workspace");
        window.dispatchEvent(shellSaveEvent);
      }
      if (mod && !event.shiftKey && event.key === "1") navigate(viewPathMap.workflow);
      if (mod && !event.shiftKey && event.key === "2") navigate(viewPathMap.matrix);
      if (mod && !event.shiftKey && event.key === "3") navigate(viewPathMap.optimize);
      if (mod && !event.shiftKey && event.key === "4") navigate(viewPathMap.compare);
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [navigate, setInspectorOpen, setMonitorOpen, setSidebarCollapsed]);

  useEffect(() => {
    if (currentJob && ["running", "queued", "cancelling"].includes(currentJob.status)) {
      setMonitorOpen(true);
    }
  }, [currentJob, setMonitorOpen]);

  const activeView = useMemo(() => pathToView(location.pathname), [location.pathname]);

  const shellContent = (
    <AnimatePresence mode="wait">
      <motion.div
        key={activeView}
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -10 }}
        transition={{ duration: 0.28, ease: "easeOut" }}
      >
        <Suspense
          fallback={
            <Card className="p-8">
              <div className="text-sm uppercase tracking-[0.22em] text-slate-500">Loading view</div>
              <div className="mt-3 text-2xl font-semibold text-white">Preparing desktop workspace</div>
              <div className="mt-2 text-sm text-slate-400">
                Fetching project state, matrix snapshots, job status, and solution details.
              </div>
            </Card>
          }
        >
          <Routes>
            <Route
              path="/workspace/workflow"
              element={
                <WorkflowScreen
                  project={project}
                  setProject={setProject}
                  matrix={matrix}
                  setMatrix={setMatrix}
                  setCurrentJobId={setCurrentJobId}
                  setCurrentSolution={setCurrentSolution}
                  onToast={pushToast}
                />
              }
            />
            <Route path="/workspace/matrix" element={<MatrixScreen project={project} matrix={matrix} />} />
            <Route
              path="/workspace/optimize"
              element={
                <OptimizeScreen
                  project={project}
                  setProject={setProject}
                  matrix={matrix}
                  currentJobId={currentJobId}
                  setCurrentJobId={setCurrentJobId}
                  currentSolution={currentSolution}
                  setCurrentSolution={setCurrentSolution}
                  onToast={pushToast}
                />
              }
            />
            <Route
              path="/workspace/compare"
              element={<CompareScreen project={project} currentSolution={currentSolution} onToast={pushToast} />}
            />
            <Route path="*" element={<Navigate to={viewPathMap.workflow} replace />} />
          </Routes>
        </Suspense>
      </motion.div>
    </AnimatePresence>
  );

  return (
    <DesktopShell
      paletteOpen={paletteOpen}
      setPaletteOpen={setPaletteOpen}
      sidebarCollapsed={sidebarCollapsed}
      setSidebarCollapsed={setSidebarCollapsed}
      inspectorOpen={inspectorOpen}
      setInspectorOpen={setInspectorOpen}
      inspectorWidth={inspectorWidth}
      setInspectorWidth={setInspectorWidth}
      monitorOpen={monitorOpen}
      setMonitorOpen={setMonitorOpen}
      health={health}
      project={project}
      matrix={matrix}
      currentJob={currentJob}
      currentJobId={currentJobId}
      currentSolution={currentSolution}
      toasts={toasts}
      pushToast={pushToast}
      setProject={setProject}
      setMatrix={setMatrix}
      setCurrentJobId={setCurrentJobId}
      setCurrentSolution={setCurrentSolution}
    >
      {shellContent}
    </DesktopShell>
  );
}

export default App;
