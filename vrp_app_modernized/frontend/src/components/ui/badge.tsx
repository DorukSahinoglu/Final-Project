import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

export function Badge({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "inline-flex max-w-full items-center rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium text-slate-200",
        "whitespace-normal break-words text-center leading-5",
        className,
      )}
      {...props}
    />
  );
}
