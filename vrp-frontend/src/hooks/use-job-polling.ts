import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { JobResponse } from "@/types/api";

export function useJobPolling(jobId: string | null) {
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;
    let active = true;
    let timer: number | undefined;

    const poll = async () => {
      try {
        setLoading(true);
        const next = await api.getJob(jobId);
        if (!active) return;
        setJob(next);
        setError(null);
        if (!["completed", "failed", "cancelled"].includes(next.status)) {
          timer = window.setTimeout(poll, 1500);
        }
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Polling failed.");
      } finally {
        if (active) setLoading(false);
      }
    };

    poll();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  return { job, loading, error, setJob };
}
