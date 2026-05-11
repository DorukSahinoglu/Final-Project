import { motion } from "framer-motion";
import { FolderKanban, Map, Radar } from "lucide-react";
import { navItems, type AppView } from "@/data/navigation";
import { cn } from "@/lib/utils";

const icons = {
  workflow: FolderKanban,
  matrix: Map,
  optimize: Radar,
};

export function WorkspaceTabs({
  active,
  onChange,
}: {
  active: AppView;
  onChange: (view: AppView) => void;
}) {
  return (
    <div className="glass-panel flex flex-wrap items-center gap-2 rounded-[24px] p-2">
      {navItems.map((item) => {
        const Icon = icons[item.id];
        const isActive = item.id === active;
        return (
          <button
            key={item.id}
            onClick={() => onChange(item.id)}
            className={cn(
              "relative flex items-center gap-2 rounded-[18px] px-4 py-3 text-sm transition",
              isActive ? "text-white" : "text-slate-400 hover:text-white",
            )}
          >
            {isActive && (
              <motion.span
                layoutId="workspace-tab"
                className="absolute inset-0 rounded-[18px] border border-accent/20 bg-gradient-to-r from-accent/15 to-accent-2/10 shadow-glow"
              />
            )}
            <span className="relative flex items-center gap-2">
              <Icon size={16} />
              {item.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
