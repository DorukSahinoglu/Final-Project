export type HealthResponse = {
  status: string;
  app: string;
  env: string;
};

export type AddressInput = {
  label: string;
  address_line: string;
  demand: number;
  is_depot: boolean;
  latitude?: number | null;
  longitude?: number | null;
  service_time_min?: number;
  time_window_start_min?: number | null;
  time_window_end_min?: number | null;
};

export type FleetUnitInput = {
  vehicle_type_id: string;
  label: string;
  count: number;
  capacity: number;
  fixed_cost: number;
  cost_per_km: number;
  speed_kmh: number;
};

export type ProjectCreatePayload = {
  name: string;
  description?: string;
  settings?: Record<string, unknown>;
  addresses: AddressInput[];
  fleet_units: FleetUnitInput[];
};

export type AddressRecord = AddressInput & {
  id: string;
  geocode_status: string;
  geocode_provider?: string | null;
};

export type FleetUnitRecord = FleetUnitInput & {
  id: string;
};

export type ProjectRecord = {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  settings: Record<string, unknown>;
  addresses: AddressRecord[];
  fleet_units: FleetUnitRecord[];
};

export type GeocodeResponse = {
  project_id: string;
  results: Array<{
    address_id: string;
    label: string;
    address_line: string;
    latitude?: number | null;
    longitude?: number | null;
    status: string;
    provider?: string | null;
    message?: string | null;
  }>;
};

export type MatrixResponse = {
  id: string;
  project_id: string;
  status: string;
  provider: string;
  size: number;
  metadata: Record<string, unknown>;
  distance_matrix: number[][];
  time_matrix: number[][];
};

export type JobAcceptedResponse = {
  job_id: string;
  status: string;
};

export type JobLog = {
  timestamp: string;
  level: string;
  message: string;
  context: Record<string, unknown>;
};

export type JobResponse = {
  id: string;
  project_id: string;
  matrix_snapshot_id?: string | null;
  solution_id?: string | null;
  job_type: string;
  solver_key?: string | null;
  status: string;
  progress: number;
  message?: string | null;
  cancel_requested: boolean;
  logs: JobLog[];
  result: Record<string, unknown>;
  error: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type SolutionRoute = {
  nodes: number[];
  vehicle_label?: string | null;
  vehicle_type_id?: string | null;
  route_distance?: number | null;
  route_time?: number | null;
  route_cost?: number | null;
  fixed_cost?: number | null;
  variable_cost?: number | null;
};

export type SolutionResponse = {
  id: string;
  project_id: string;
  solver_key: string;
  summary: Record<string, unknown>;
  routes: SolutionRoute[];
  analytics: Record<string, unknown>;
  raw_payload: Record<string, unknown>;
  created_at: string;
};
