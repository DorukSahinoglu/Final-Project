import type { MatrixResponse, ProjectRecord } from "@/types/api";
import { MatrixOverview } from "@/components/dashboard/matrix-overview";

export default function MatrixScreen({ project, matrix }: { project: ProjectRecord | null; matrix: MatrixResponse | null }) {
  return <MatrixOverview project={project} matrix={matrix} />;
}
