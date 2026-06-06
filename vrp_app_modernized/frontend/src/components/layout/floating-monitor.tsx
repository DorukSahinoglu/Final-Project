import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Grip, Minimize2, Radar, X } from "lucide-react";
import type { JobResponse } from "@/types/api";
import { Badge } from "@/components/ui/badge";

export function FloatingMonitor({
  job,
  open,
  onClose,
}: {
  job: JobResponse | null;
  open: boolean;
  onClose: () => void;
}) {
  const [pos, setPos] = useState({ x: 24, y: 120 });
  const latestLogs = useMemo(() => (job?.logs ?? []).slice(-6), [job]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          drag
          dragMomentum={false}
          initial={{ opacity: 0, y: 20, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, y: 20, scale: 0.98 }}
          style={{ x: pos.x, y: pos.y }}
          onDragEnd={(_, info) => setPos((prev) => ({ x: prev.x + info.offset.x, y: prev.y + info.offset.y }))}
          className="fixed left-0 top-0 z-50 w-[380px] rounded-[28px] border border-white/10 bg-[#08101c]/92 p-4 shadow-[0_30px_90px_rgba(0,0,0,0.45)] backdrop-blur-2xl"
        >
          <div className="monitor-handle mb-4 flex cursor-grab items-center justify-between active:cursor-grabbing">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-accent/10 text-accent">
                <Radar size={16} />
              </div>
              <div>
                <div className="text-sm font-medium text-white">Optimization Monitor</div>
                <div className="text-xs text-slate-500">Persistent floating runtime window</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button className="rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-400">
                <Grip size={14} />
              </button>
              <button className="rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-400">
                <Minimize2 size={14} />
              </button>
              <button onClick={onClose} className="rounded-xl border border-white/10 bg-white/[0.04] p-2 text-slate-400">
                <X size={14} />
              </button>
            </div>
          </div>

          <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-4">
            <div className="flex items-center justify-between">
              <div className="text-sm text-slate-400">Status</div>
              <Badge className="border-white/10 bg-white/[0.04] text-slate-300">{job?.status ?? "Idle"}</Badge>
            </div>
            <div className="mt-3 h-2 rounded-full bg-white/6">
              <div className="h-full rounded-full bg-gradient-to-r from-accent to-accent-2 transition-all" style={{ width: `${job?.progress ?? 0}%` }} />
            </div>
            <div className="mt-3 text-sm text-slate-400">{job?.message ?? "No active optimization job."}</div>
          </div>

          <div className="mt-4 space-y-2">
            {latestLogs.length > 0 ? (
              latestLogs.map((log) => (
                <div key={`${log.timestamp}-${log.message}`} className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3 text-sm text-slate-300">
                  {log.message}
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-white/8 bg-[#09101c] px-4 py-3 text-sm text-slate-400">
                Monitor waiting for first job.
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
