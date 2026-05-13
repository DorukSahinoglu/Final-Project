import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { RotateCcw, Save, Settings2, X } from "lucide-react";
import {
  defaultAlgorithmParameters,
  mergeAlgorithmParameters,
  parameterFields,
  solverLabel,
  validateAlgorithmParameters,
  type AlgorithmParameterState,
  type SolverKey,
} from "@/lib/algorithm-parameters";
import type { ProjectRecord } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Props = {
  open: boolean;
  project: ProjectRecord | null;
  selectedSolver: SolverKey;
  onClose: () => void;
  onSave: (next: AlgorithmParameterState) => Promise<void>;
  onToast: (title: string, body: string) => void;
};

export function AlgorithmParametersModal({
  open,
  project,
  selectedSolver,
  onClose,
  onSave,
  onToast,
}: Props) {
  const [activeTab, setActiveTab] = useState<SolverKey>(selectedSolver);
  const [draft, setDraft] = useState<AlgorithmParameterState>(mergeAlgorithmParameters(project?.settings));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setActiveTab(selectedSolver);
    setDraft(mergeAlgorithmParameters(project?.settings));
    setError(null);
  }, [open, project?.settings, selectedSolver]);

  const activeFields = useMemo(() => parameterFields[activeTab], [activeTab]);
  const validationErrors = useMemo(() => validateAlgorithmParameters(draft), [draft]);

  const setField = (solver: SolverKey, key: string, value: string | boolean) => {
    setDraft((current) => {
      const currentValue = current[solver][key as keyof typeof current[typeof solver]];
      let nextValue: string | number | boolean = value;
      if (typeof currentValue === "number" && typeof value === "string") {
        nextValue = value === "" ? 0 : Number(value);
      }
      return {
        ...current,
        [solver]: {
          ...current[solver],
          [key]: nextValue,
        },
      };
    });
  };

  const resetDefaults = () => {
    setDraft((current) => ({
      ...current,
      [activeTab]: { ...defaultAlgorithmParameters[activeTab] },
    }));
    onToast("Defaults restored", `${solverLabel(activeTab)} parameters were reset to their safe defaults.`);
  };

  const save = async () => {
    if (validationErrors.length > 0) {
      setError(validationErrors[0]);
      return;
    }
    try {
      setSaving(true);
      setError(null);
      await onSave(draft);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save algorithm parameters.");
    } finally {
      setSaving(false);
    }
  };

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
            className="fixed left-1/2 top-16 z-50 w-[min(980px,calc(100%-2rem))] -translate-x-1/2 rounded-[30px] border border-white/10 bg-[#09111f]/95 p-5 shadow-panel backdrop-blur-2xl"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3">
                <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                  <Settings2 size={18} />
                </div>
                <div>
                  <div className="text-lg font-semibold text-white">Algorithm Parameters</div>
                  <div className="text-sm text-slate-400">
                    Every field here is connected to the real solver execution path and is saved into the current project settings.
                  </div>
                </div>
              </div>
              <Button variant="ghost" className="px-3" onClick={onClose}>
                <X size={16} />
              </Button>
            </div>

            <div className="mt-5 flex flex-wrap gap-3">
              {(["bloodhound", "nsga2"] as SolverKey[]).map((solverKey) => (
                <button
                  key={solverKey}
                  onClick={() => setActiveTab(solverKey)}
                  className={`rounded-2xl border px-4 py-2 text-sm transition ${
                    activeTab === solverKey
                      ? "border-accent/30 bg-accent/10 text-accent"
                      : "border-white/10 bg-white/[0.03] text-slate-300 hover:border-accent/20 hover:text-white"
                  }`}
                >
                  {solverLabel(solverKey)}
                </button>
              ))}
            </div>

            <div className="mt-5 grid max-h-[60vh] gap-4 overflow-y-auto pr-1 md:grid-cols-2">
              {activeFields.map((field) => (
                <div key={field.key} className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                  <div className="flex items-center gap-2">
                    <div className="text-sm font-medium text-white">{field.label}</div>
                    <div className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-slate-500" title={field.description}>
                      info
                    </div>
                  </div>
                  <div className="mt-2 text-xs leading-5 text-slate-500">{field.description}</div>
                  <div className="mt-4">
                    {field.type === "boolean" ? (
                      <button
                        onClick={() => setField(activeTab, field.key, !Boolean(draft[activeTab][field.key as keyof typeof draft[typeof activeTab]]))}
                        className={`rounded-2xl border px-4 py-2 text-sm transition ${
                          draft[activeTab][field.key as keyof typeof draft[typeof activeTab]]
                            ? "border-accent/30 bg-accent/10 text-accent"
                            : "border-white/10 bg-white/[0.03] text-slate-300"
                        }`}
                      >
                        {Boolean(draft[activeTab][field.key as keyof typeof draft[typeof activeTab]]) ? "Enabled" : "Disabled"}
                      </button>
                    ) : field.type === "select" ? (
                      <select
                        value={String(draft[activeTab][field.key as keyof typeof draft[typeof activeTab]])}
                        onChange={(event) => setField(activeTab, field.key, event.target.value)}
                        className="h-11 w-full rounded-2xl border border-white/10 bg-white/[0.04] px-4 text-sm text-white outline-none"
                      >
                        {field.options?.map((option) => (
                          <option key={option.value} value={option.value} className="bg-[#09111f]">
                            {option.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <Input
                        type="number"
                        min={field.min}
                        max={field.max}
                        step={field.step ?? (field.type === "integer" ? 1 : 0.01)}
                        value={String(draft[activeTab][field.key as keyof typeof draft[typeof activeTab]])}
                        onChange={(event) => setField(activeTab, field.key, event.target.value)}
                      />
                    )}
                  </div>
                </div>
              ))}
            </div>

            {(error || validationErrors.length > 0) && (
              <div className="mt-4 rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
                {error ?? validationErrors[0]}
              </div>
            )}

            <div className="mt-5 flex flex-wrap justify-end gap-3">
              <Button variant="secondary" className="gap-2" onClick={resetDefaults}>
                <RotateCcw size={16} />
                Reset to Defaults
              </Button>
              <Button onClick={save} className="gap-2" disabled={saving}>
                <Save size={16} className={saving ? "animate-pulse" : ""} />
                Save Parameters
              </Button>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
