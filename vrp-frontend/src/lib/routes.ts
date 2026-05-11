import type { AppView } from "@/data/navigation";

export const viewPathMap: Record<AppView, string> = {
  workflow: "/workspace/workflow",
  matrix: "/workspace/matrix",
  optimize: "/workspace/optimize",
};

export function pathToView(pathname: string): AppView {
  if (pathname.includes("/matrix")) return "matrix";
  if (pathname.includes("/optimize")) return "optimize";
  return "workflow";
}
