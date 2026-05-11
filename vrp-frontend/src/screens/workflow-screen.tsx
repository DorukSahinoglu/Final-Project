import type { MatrixResponse, ProjectRecord } from "@/types/api";
import { ComingSoonCard } from "@/components/dashboard/coming-soon";
import { ProjectWorkflow } from "@/components/dashboard/project-workflow";

type Props = {
  project: ProjectRecord | null;
  setProject: (project: ProjectRecord) => void;
  matrix: MatrixResponse | null;
  setMatrix: (matrix: MatrixResponse | null) => void;
  onToast: (title: string, body: string) => void;
};

export default function WorkflowScreen({ project, setProject, matrix, setMatrix, onToast }: Props) {
  return (
    <div className="space-y-5">
      <ProjectWorkflow project={project} setProject={setProject} matrix={matrix} setMatrix={setMatrix} onToast={onToast} />
      <ComingSoonCard />
    </div>
  );
}
