import type { InputHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "h-11 min-w-0 w-full rounded-2xl border border-white/10 bg-white/[0.04] px-4 text-sm text-white placeholder:text-slate-500",
        "outline-none transition-all duration-300 focus:border-accent/40 focus:bg-white/[0.06] focus:ring-2 focus:ring-accent/20",
        className,
      )}
      {...props}
    />
  );
}
