import { forwardRef } from "react";
import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost";
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", ...props }, ref) => (
    <button
      ref={ref}
      type={props.type ?? "button"}
      className={cn(
        "inline-flex items-center justify-center rounded-2xl border px-4 py-2.5 text-sm font-medium transition-all duration-300",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/60",
        "disabled:cursor-not-allowed disabled:pointer-events-none disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none",
        variant === "primary" &&
          "border-accent/40 bg-gradient-to-r from-accent/80 to-accent-2/80 text-slate-950 shadow-glow hover:-translate-y-0.5 hover:shadow-[0_18px_45px_rgba(87,230,255,0.22)]",
        variant === "secondary" &&
          "border-white/10 bg-white/5 text-white hover:border-accent/30 hover:bg-white/10",
        variant === "ghost" && "border-transparent bg-transparent text-slate-300 hover:bg-white/5 hover:text-white",
        className,
      )}
      {...props}
    />
  ),
);

Button.displayName = "Button";
