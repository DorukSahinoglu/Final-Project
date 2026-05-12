import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { KeyRound, LoaderCircle, Save } from "lucide-react";
import { api } from "@/lib/api";
import type { GoogleSettingsResponse } from "@/types/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function SettingsModal({
  open,
  onClose,
  onToast,
}: {
  open: boolean;
  onClose: () => void;
  onToast: (title: string, body: string) => void;
}) {
  const [settings, setSettings] = useState<GoogleSettingsResponse | null>(null);
  const [value, setValue] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    api
      .getGoogleSettings()
      .then((response) => {
        setSettings(response);
        setValue(response.google_api_key ?? "");
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load settings."))
      .finally(() => setLoading(false));
  }, [open]);

  const save = async () => {
    try {
      setSaving(true);
      const response = await api.updateGoogleSettings(value);
      setSettings(response);
      onToast("Settings saved", "Google API key stored locally for backend services.");
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings.");
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
            className="fixed left-1/2 top-24 z-50 w-[min(680px,calc(100%-2rem))] -translate-x-1/2 rounded-[30px] border border-white/10 bg-[#09111f]/95 p-5 shadow-panel backdrop-blur-2xl"
          >
            <div className="mb-5 flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                <KeyRound size={18} />
              </div>
              <div>
                <div className="text-lg font-semibold text-white">Google API Settings</div>
                <div className="text-sm text-slate-400">Stored locally in backend. No key is hardcoded in frontend code.</div>
              </div>
            </div>

            {loading ? (
              <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-5 text-sm text-slate-300">Loading settings...</div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                  <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Google API key</div>
                  <Input type="password" value={value} onChange={(event) => setValue(event.target.value)} placeholder="AIza..." />
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Geocoding provider</div>
                    <div className="mt-2 text-sm text-white">{settings?.geocode_provider ?? "unknown"}</div>
                  </div>
                  <div className="rounded-[24px] border border-white/10 bg-white/[0.03] p-4">
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500">Matrix provider</div>
                    <div className="mt-2 text-sm text-white">{settings?.matrix_provider ?? "unknown"}</div>
                  </div>
                </div>
                {error && <div className="rounded-2xl border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">{error}</div>}
                <div className="flex justify-end gap-3">
                  <Button variant="secondary" onClick={onClose}>
                    Close
                  </Button>
                  <Button onClick={save} className="gap-2" disabled={saving}>
                    {saving ? <LoaderCircle size={16} className="animate-spin" /> : <Save size={16} />}
                    Save key
                  </Button>
                </div>
              </div>
            )}
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
