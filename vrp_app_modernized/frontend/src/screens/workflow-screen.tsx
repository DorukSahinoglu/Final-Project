import type { MatrixResponse, ProjectRecord, SolutionResponse } from "@/types/api";
import { ProjectWorkflow } from "@/components/dashboard/project-workflow";

type Props = {
  project: ProjectRecord | null;
  setProject: (project: ProjectRecord) => void;
  matrix: MatrixResponse | null;
  setMatrix: (matrix: MatrixResponse | null) => void;
  setCurrentJobId: (jobId: string | null) => void;
  setCurrentSolution: (solution: SolutionResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

export default function WorkflowScreen(props: Props) {
  return <ProjectWorkflow {...props} />;
}
