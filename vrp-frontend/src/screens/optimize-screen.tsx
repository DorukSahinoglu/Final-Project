import type { MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { OptimizationConsole } from "@/components/dashboard/optimization-console";

type Props = {
  project: ProjectRecord | null;
  matrix: MatrixResponse | null;
  currentJobId: string | null;
  setCurrentJobId: (jobId: string | null) => void;
  currentSolution: SolutionResponse | null;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

export default function OptimizeScreen(props: Props) {
  return <OptimizationConsole {...props} />;
}
