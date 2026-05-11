import type { WorkspaceSnapshot } from "@/types/workspace";

export type FileSystemAdapter = {
  saveWorkspace(snapshot: WorkspaceSnapshot): Promise<void>;
  loadWorkspace(): Promise<WorkspaceSnapshot | null>;
};

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function promptJsonFile(): Promise<File | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "application/json,.json";
    input.onchange = () => resolve(input.files?.[0] ?? null);
    input.click();
  });
}

export const browserFileSystemAdapter: FileSystemAdapter = {
  async saveWorkspace(snapshot) {
    const name = `pulseroute-workspace-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.json`;
    downloadJson(name, snapshot);
  },
  async loadWorkspace() {
    const file = await promptJsonFile();
    if (!file) return null;
    const text = await file.text();
    return JSON.parse(text) as WorkspaceSnapshot;
  },
};
