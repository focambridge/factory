import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

/** Load JSON from the API, with reload and optional polling. */
export function useApi<T = any>(path: string | null, pollMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try {
      setData(await api.get<T>(path));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [path]);
  useEffect(() => {
    setData(null);
    reload();
  }, [reload]);
  useEffect(() => {
    if (!pollMs || !path) return;
    const t = setInterval(reload, pollMs);
    return () => clearInterval(t);
  }, [pollMs, path, reload]);
  return { data, error, loading, reload, setData };
}

export interface Job {
  id: string;
  kind: string;
  title: string;
  project: string | null;
  status: "running" | "succeeded" | "failed" | "paused";
  started: number;
  finished: number | null;
  exit_code: number | null;
  exit_meaning: string | null;
  lines: string[];
  line_count: number;
  result: any;
  meta: any;
}

/** Follow a background job until it finishes, collecting its output lines. */
export function useJob(jobId: string | null, onDone?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const count = useRef(0);
  const done = useRef(onDone);
  done.current = onDone;
  useEffect(() => {
    if (!jobId) return;
    count.current = 0;
    setLines([]);
    setJob(null);
    let stopped = false;
    const tick = async () => {
      try {
        const j = await api.get<Job>(`/api/jobs/${jobId}?since=${count.current}`);
        if (stopped) return;
        count.current = j.line_count;
        if (j.lines.length) setLines((prev) => [...prev, ...j.lines]);
        setJob(j);
        if (j.status !== "running") {
          done.current?.(j);
          return;
        }
      } catch {
        /* keep trying */
      }
      if (!stopped) setTimeout(tick, 1000);
    };
    tick();
    return () => {
      stopped = true;
    };
  }, [jobId]);
  return { job, lines };
}

export function useElapsed(start: number | null | undefined, end?: number | null) {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    if (end) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [end]);
  if (!start) return "";
  const s = Math.max(0, Math.round((end || now) - start));
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}
