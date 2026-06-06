import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "glass-panel rounded-[28px] p-5 transition-all duration-300 hover:border-white/12 hover:bg-white/[0.06]",
        className,
      )}
      {...props}
    />
  );
}
