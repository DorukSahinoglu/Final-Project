import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, Sparkles } from "lucide-react";

export type ToastItem = {
  id: number;
  title: string;
  body: string;
};

export function ToastStack({ toasts }: { toasts: ToastItem[] }) {
  return (
    <div className="pointer-events-none fixed bottom-6 right-6 z-50 space-y-3">
      <AnimatePresence>
        {toasts.map((toast) => (
          <motion.div
            key={toast.id}
            initial={{ opacity: 0, y: 20, x: 20 }}
            animate={{ opacity: 1, y: 0, x: 0 }}
            exit={{ opacity: 0, y: 12, x: 20 }}
            className="glass-panel flex w-[340px] items-start gap-3 rounded-[24px] p-4"
          >
            <div className="mt-0.5 rounded-2xl bg-success/10 p-2 text-success">
              <CheckCircle2 size={16} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-sm font-medium text-white">
                {toast.title}
                <Sparkles size={14} className="text-accent" />
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-400">{toast.body}</div>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
