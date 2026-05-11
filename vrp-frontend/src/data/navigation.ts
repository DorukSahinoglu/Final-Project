export type AppView = "workflow" | "matrix" | "optimize";

export const navItems: { id: AppView; label: string; hint: string }[] = [
  { id: "workflow", label: "Workflow", hint: "Project, addresses, geocoding" },
  { id: "matrix", label: "Matrix", hint: "Distance and time generation" },
  { id: "optimize", label: "Optimize", hint: "Background jobs and solutions" },
];

export const deferredFeatures = [
  "Side-by-side multi-solution comparison workspace",
  "Fleet-wide analytics dashboard across many solutions",
  "CSV import/export management UI",
  "Interactive live map rendering layer",
  "Project gallery and saved scenario browser",
];
