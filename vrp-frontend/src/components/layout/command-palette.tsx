import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Command } from "lucide-react";
import { navItems, type AppView } from "@/data/navigation";

export function CommandPalette({
  open,
  onClose,
  onSelect,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (view: AppView) => void;
}) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    if (open) window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose, open]);

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
            className="fixed left-1/2 top-24 z-50 w-[min(680px,calc(100%-2rem))] -translate-x-1/2 rounded-[30px] border border-white/10 bg-[#09111f]/95 p-4 shadow-panel backdrop-blur-2xl"
          >
            <div className="mb-3 flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-slate-400">
              <Command size={18} />
              <span className="text-sm">Jump between active backend-supported workspaces</span>
            </div>
            <div className="space-y-2">
              {navItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    onSelect(item.id);
                    onClose();
                  }}
                  className="flex w-full items-start justify-between rounded-[22px] border border-transparent bg-white/[0.03] px-4 py-4 text-left transition hover:border-accent/20 hover:bg-white/[0.06]"
                >
                  <div>
                    <div className="text-sm font-medium text-white">{item.label}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.hint}</div>
                  </div>
                  <div className="rounded-full border border-white/10 px-2 py-1 text-[11px] text-slate-400">Open</div>
                </button>
              ))}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
