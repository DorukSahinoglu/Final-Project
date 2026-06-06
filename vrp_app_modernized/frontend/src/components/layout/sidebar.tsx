import { motion } from "framer-motion";
import { Boxes, Columns2, Map, Sparkles } from "lucide-react";
import { navItems, type AppView } from "@/data/navigation";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

const iconMap = {
  workflow: Boxes,
  matrix: Map,
  optimize: Sparkles,
  compare: Columns2,
};

export function Sidebar({
  active,
  onChange,
  collapsed,
  onToggle,
}: {
  active: AppView;
  onChange: (view: AppView) => void;
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <motion.aside
      animate={{ width: collapsed ? 94 : 296 }}
      className="glass-panel sticky top-4 hidden h-[calc(100vh-2rem)] shrink-0 overflow-hidden rounded-[30px] p-4 xl:block"
    >
      <div className="mb-8 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-accent to-accent-2 text-slate-950 shadow-glow">
            PR
          </div>
          {!collapsed && (
            <div>
              <div className="text-sm font-semibold text-white">PulseRoute OS</div>
              <div className="text-xs text-slate-400">Backend-first optimizer</div>
            </div>
          )}
        </div>
        <button
          onClick={onToggle}
          className="shrink-0 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 transition hover:bg-white/10 hover:text-white"
        >
          {collapsed ? "Expand" : "Collapse"}
        </button>
      </div>

      <div className="space-y-2">
        {navItems.map((item) => {
          const Icon = iconMap[item.id];
          const isActive = item.id === active;
          return (
            <button
              key={item.id}
              onClick={() => onChange(item.id)}
              className={cn(
                "group flex w-full items-center gap-3 rounded-[22px] border px-3 py-3 text-left transition-all duration-300",
                isActive
                  ? "border-accent/30 bg-gradient-to-r from-accent/15 to-accent-2/10 text-white shadow-glow"
                  : "border-transparent text-slate-400 hover:border-white/10 hover:bg-white/[0.04] hover:text-white",
              )}
            >
              <div
                className={cn(
                  "flex h-11 w-11 items-center justify-center rounded-2xl",
                  isActive ? "bg-white/10 text-accent" : "bg-white/[0.05] text-slate-400 group-hover:text-white",
                )}
              >
                <Icon size={18} />
              </div>
              {!collapsed && (
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium">{item.label}</div>
                  <div className="line-clamp-2 text-xs text-slate-500">{item.hint}</div>
                </div>
              )}
            </button>
          );
        })}
      </div>

      {!collapsed && (
        <div className="mt-8 rounded-[26px] border border-accent/15 bg-gradient-to-br from-accent/15 via-white/5 to-accent-2/15 p-4">
          <Badge className="mb-3 border-accent/20 bg-accent/10 text-accent">Backend Parity</Badge>
          <div className="text-lg font-semibold">Supported now</div>
          <p className="mt-2 break-words text-sm leading-6 text-slate-300">
            Projects, geocoding, matrix generation, queued solves, progress polling, cancellation, and persisted
            solutions.
          </p>
        </div>
      )}
    </motion.aside>
  );
}
