import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

export function Progress({ value, className }: { value: number; className?: string }) {
  return (
    <div className={cn("h-2 overflow-hidden rounded-full bg-white/6", className)}>
      <motion.div
        className="h-full rounded-full bg-gradient-to-r from-accent via-cyan-300 to-accent-2"
        initial={{ width: 0 }}
        animate={{ width: `${value}%` }}
        transition={{ duration: 0.9, ease: "easeOut" }}
      />
    </div>
  );
}
