import type { ProjectBundle } from "@/types/api";
import type { WorkspaceSnapshot } from "@/types/workspace";

export type FileSystemAdapter = {
  saveWorkspace(snapshot: WorkspaceSnapshot): Promise<void>;
  loadWorkspace(): Promise<WorkspaceSnapshot | null>;
  exportProjectBundle(filename: string, bundle: ProjectBundle): Promise<void>;
  importProjectBundle(): Promise<ProjectBundle | null>;
  saveTextFile(filename: string, content: string, mimeType?: string): Promise<void>;
  saveJsonFile(filename: string, data: unknown): Promise<void>;
};

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function downloadJson(filename: string, data: unknown) {
  downloadBlob(filename, new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
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
  async exportProjectBundle(filename, bundle) {
    downloadJson(filename, bundle);
  },
  async importProjectBundle() {
    const file = await promptJsonFile();
    if (!file) return null;
    const text = await file.text();
    return JSON.parse(text) as ProjectBundle;
  },
  async saveTextFile(filename, content, mimeType = "text/plain;charset=utf-8") {
    downloadBlob(filename, new Blob([content], { type: mimeType }));
  },
  async saveJsonFile(filename, data) {
    downloadJson(filename, data);
  },
};
