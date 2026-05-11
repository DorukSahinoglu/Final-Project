import { Activity, Command, Search, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function Navbar({
  onCommandOpen,
  healthLabel,
}: {
  onCommandOpen: () => void;
  healthLabel: string;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-panel flex flex-col gap-4 rounded-[28px] p-4 lg:flex-row lg:items-center lg:justify-between"
    >
      <div>
        <div className="flex items-center gap-3">
          <h1 className="m-0 text-2xl font-semibold tracking-tight text-white md:text-3xl">
            VRP Optimization Control Plane
          </h1>
          <Badge className="hidden border-success/30 bg-success/10 text-success md:inline-flex">{healthLabel}</Badge>
        </div>
        <p className="mb-0 mt-2 max-w-3xl text-sm leading-6 text-slate-400">
          Real backend workflow for project storage, geocoding, matrix generation, solver jobs, progress polling, and
          persisted solution retrieval.
        </p>
      </div>

      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative min-w-[260px] flex-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
          <Input className="pl-11" placeholder="Search everywhere or jump with Ctrl+K..." readOnly onFocus={onCommandOpen} />
        </div>
        <Button variant="secondary" onClick={onCommandOpen} className="gap-2">
          <Command size={16} />
          Command Palette
        </Button>
        <Button className="gap-2" disabled>
          <Sparkles size={16} />
          Coming soon
        </Button>
        <button className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-slate-300 transition hover:bg-white/10 hover:text-white">
          <Activity size={18} />
        </button>
      </div>
    </motion.div>
  );
}
