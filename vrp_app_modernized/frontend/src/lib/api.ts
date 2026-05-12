import type {
  GeocodeResponse,
  GoogleSettingsResponse,
  HealthResponse,
  JobAcceptedResponse,
  JobResponse,
  MatrixResponse,
  ProjectCreatePayload,
  ProjectRecord,
  ProjectSolutionSummary,
  SolutionResponse,
} from "@/types/api";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "http://127.0.0.1:8000/api";

export class APIError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      message = payload.detail ?? message;
    } catch {
      // keep default
    }
    throw new APIError(message, response.status);
  }

  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  createProject: (payload: ProjectCreatePayload) =>
    request<ProjectRecord>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (projectId: string, payload: ProjectCreatePayload) =>
    request<ProjectRecord>(`/projects/${projectId}`, { method: "PUT", body: JSON.stringify(payload) }),
  getProject: (projectId: string) => request<ProjectRecord>(`/projects/${projectId}`),
  listProjectSolutions: (projectId: string) => request<ProjectSolutionSummary[]>(`/projects/${projectId}/solutions`),
  geocodeProject: (projectId: string, addressIds: string[] = []) =>
    request<GeocodeResponse>("/geocode", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, address_ids: addressIds }),
    }),
  generateMatrix: (projectId: string, speedKmh: number) =>
    request<MatrixResponse>("/matrix/generate", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, speed_kmh: speedKmh }),
    }),
  solveNsga2: (projectId: string, matrixId: string, solverParams: Record<string, unknown>) =>
    request<JobAcceptedResponse>("/solve/nsga2", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, matrix_id: matrixId, solver_params: solverParams }),
    }),
  solveBloodhound: (projectId: string, matrixId: string, solverParams: Record<string, unknown>) =>
    request<JobAcceptedResponse>("/solve/bloodhound", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, matrix_id: matrixId, solver_params: solverParams }),
    }),
  getJob: (jobId: string) => request<JobResponse>(`/jobs/${jobId}`),
  cancelJob: (jobId: string) => request<{ message: string }>(`/jobs/${jobId}/cancel`, { method: "POST" }),
  getSolution: (solutionId: string) => request<SolutionResponse>(`/solutions/${solutionId}`),
  getGoogleSettings: () => request<GoogleSettingsResponse>("/settings/google"),
  updateGoogleSettings: (googleApiKey: string) =>
    request<GoogleSettingsResponse>("/settings/google", {
      method: "PUT",
      body: JSON.stringify({ google_api_key: googleApiKey }),
    }),
};
