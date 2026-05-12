export type AppView = "workflow" | "matrix" | "optimize" | "compare";

export const navItems: { id: AppView; label: string; hint: string }[] = [
  { id: "workflow", label: "Workflow", hint: "Project, addresses, geocoding" },
  { id: "matrix", label: "Matrix", hint: "Distance and time generation" },
  { id: "optimize", label: "Optimize", hint: "Background jobs and solutions" },
  { id: "compare", label: "Compare", hint: "NSGA-II vs Bloodhound results" },
];

export const deferredFeatures = [
  "Fleet-wide analytics dashboard across many solutions",
  "Project gallery and saved scenario browser",
];
