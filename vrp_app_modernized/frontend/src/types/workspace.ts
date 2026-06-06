import type { MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";

export type WorkspaceSnapshot = {
  exported_at: string;
  version: 1;
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentJobId: string | null;
  currentSolution: SolutionResponse | null;
};
