import { Command, Search, Settings2, Sparkles } from "lucide-react";
import { motion } from "framer-motion";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

export function Navbar({
  onCommandOpen,
  healthLabel,
  onSettingsOpen,
}: {
  onCommandOpen: () => void;
  healthLabel: string;
  onSettingsOpen: () => void;
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      className="glass-panel flex flex-col gap-4 overflow-hidden rounded-[28px] p-4 lg:flex-row lg:items-start lg:justify-between"
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="m-0 min-w-0 max-w-full text-2xl font-semibold tracking-tight text-white md:text-3xl break-words">
            VRP Optimization Control Plane
          </h1>
          <Badge className="hidden max-w-full border-success/30 bg-success/10 text-success md:inline-flex">{healthLabel}</Badge>
        </div>
        <p className="mb-0 mt-2 max-w-3xl break-words text-sm leading-6 text-slate-400">
          Real backend workflow for project storage, geocoding, matrix generation, solver jobs, progress polling, and
          persisted solution retrieval.
        </p>
      </div>

      <div className="flex min-w-0 flex-col gap-3 md:flex-row md:flex-wrap md:items-center md:justify-end">
        <div className="relative min-w-0 md:min-w-[260px] md:flex-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" size={18} />
          <Input className="pl-11" placeholder="Search everywhere or jump with Ctrl+K..." readOnly onFocus={onCommandOpen} />
        </div>
        <Button variant="secondary" onClick={onCommandOpen} className="gap-2 whitespace-normal text-center">
          <Command size={16} />
          Command Palette
        </Button>
        <Button className="gap-2 whitespace-normal text-center" disabled>
          <Sparkles size={16} />
          Coming soon
        </Button>
        <button
          onClick={onSettingsOpen}
          className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/5 text-slate-300 transition hover:bg-white/10 hover:text-white"
        >
          <Settings2 size={18} />
        </button>
      </div>
    </motion.div>
  );
}
