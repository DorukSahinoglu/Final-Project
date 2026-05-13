import type { AddressRecord, FleetUnitRecord, MatrixResponse, ProjectRecord } from "@/types/api";

export type FleetKind = "homogeneous" | "heterogeneous";

export function detectFleetType(fleet: Array<FleetUnitRecord | {
  capacity: number;
  fixed_cost: number;
  cost_per_km: number;
  speed_kmh: number;
}>): FleetKind {
  if (fleet.length <= 1) return "homogeneous";
  const signature = new Set(
    fleet.map((item) =>
      [
        item.capacity,
        item.fixed_cost,
        item.cost_per_km,
        item.speed_kmh,
      ].join("|"),
    ),
  );
  return signature.size === 1 ? "homogeneous" : "heterogeneous";
}

export function projectValidation(project: ProjectRecord | null, matrix: MatrixResponse | null) {
  if (!project) {
    return {
      completeness: 0,
      warnings: ["Project has not been saved yet."],
      errors: ["Create and save a project before running optimization."],
    };
  }

  const depotCount = project.addresses.filter((item) => item.is_depot).length;
  const customerCount = project.addresses.filter((item) => !item.is_depot).length;
  const geocodedCount = project.addresses.filter((item) => item.latitude != null && item.longitude != null).length;
  const duplicateAddresses = findDuplicateValues(project.addresses.map((item) => item.address_line));
  const invalidDemands = project.addresses.filter((item) => !item.is_depot && item.demand < 0);
  const warnings: string[] = [];
  const errors: string[] = [];

  if (duplicateAddresses.length) warnings.push(`Duplicate addresses detected: ${duplicateAddresses.join(", ")}`);
  if (invalidDemands.length) errors.push(`Invalid negative demand on ${invalidDemands.map((item) => item.label).join(", ")}`);
  if (depotCount !== 1) errors.push("Exactly one depot must be selected.");
  if (!project.fleet_units.length) errors.push("At least one fleet entry is required.");
  if (!customerCount) errors.push("At least one customer is required.");
  if (geocodedCount !== project.addresses.length) warnings.push("Some addresses are still missing coordinates.");
  if (!matrix) warnings.push("Distance/time matrix has not been generated yet.");

  const stepsDone = [
    Boolean(project.id),
    depotCount === 1 && customerCount > 0,
    geocodedCount === project.addresses.length,
    Boolean(matrix),
  ].filter(Boolean).length;

  return {
    completeness: Math.round((stepsDone / 4) * 100),
    warnings,
    errors,
  };
}

export function findDuplicateValues(values: string[]) {
  const seen = new Set<string>();
  const dupes = new Set<string>();
  values.forEach((value) => {
    const normalized = value.trim().toLowerCase();
    if (!normalized) return;
    if (seen.has(normalized)) dupes.add(value.trim());
    seen.add(normalized);
  });
  return [...dupes];
}

export function summarizeMatrix(matrix: MatrixResponse | null) {
  if (!matrix) {
    return {
      minDistance: 0,
      maxDistance: 0,
      avgDistance: 0,
      minTime: 0,
      maxTime: 0,
      avgTime: 0,
      missingPairs: 0,
    };
  }

  const distances = matrix.distance_matrix.flat().filter((value) => Number.isFinite(value) && value > 0);
  const times = matrix.time_matrix.flat().filter((value) => Number.isFinite(value) && value > 0);
  return {
    minDistance: distances.length ? Math.min(...distances) : 0,
    maxDistance: distances.length ? Math.max(...distances) : 0,
    avgDistance: distances.length ? distances.reduce((sum, value) => sum + value, 0) / distances.length : 0,
    minTime: times.length ? Math.min(...times) : 0,
    maxTime: times.length ? Math.max(...times) : 0,
    avgTime: times.length ? times.reduce((sum, value) => sum + value, 0) / times.length : 0,
    missingPairs: matrix.distance_matrix.flat().filter((value) => !Number.isFinite(value)).length,
  };
}

export function getDepot(project: ProjectRecord | null): AddressRecord | null {
  return project?.addresses.find((item) => item.is_depot) ?? null;
}
