import type { ProjectCreatePayload } from "@/types/api";

export const sampleProject: ProjectCreatePayload = {
  name: "Istanbul Premium Demo Run",
  description: "Sample urban distribution scenario for exhibition demos.",
  settings: {
    scenario_tag: "demo",
  },
  addresses: [
    {
      label: "Central Depot",
      address_line: "Maslak Mahallesi, Sariyer, Istanbul, Turkiye",
      demand: 0,
      is_depot: true,
      notes: "Primary dispatch depot",
    },
    {
      label: "Sisli Medical",
      address_line: "Halaskargazi Cd. 198, Sisli, Istanbul, Turkiye",
      demand: 4,
      is_depot: false,
      notes: "Timed retail delivery",
    },
    {
      label: "Kadikoy Retail Hub",
      address_line: "Bagdat Cd. 312, Kadikoy, Istanbul, Turkiye",
      demand: 6,
      is_depot: false,
      notes: "High-priority customer",
    },
    {
      label: "Bakirkoy Clinic",
      address_line: "Fisekhane Cd. 12, Bakirkoy, Istanbul, Turkiye",
      demand: 3,
      is_depot: false,
    },
    {
      label: "Besiktas Office",
      address_line: "Barbaros Blv. 74, Besiktas, Istanbul, Turkiye",
      demand: 2,
      is_depot: false,
    },
  ],
  fleet_units: [
    {
      vehicle_type_id: "van-standard",
      label: "Standard Van",
      count: 3,
      capacity: 14,
      fixed_cost: 65,
      cost_per_km: 9.5,
      speed_kmh: 32,
    },
  ],
};
