import { useCallback, useEffect, useRef, useState } from "react";

export class ApiError extends Error {}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const res = await fetch("/api" + path, {
    method,
    headers: body && !isForm ? { "Content-Type": "application/json" } : undefined,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `The server answered ${res.status}.`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") detail = j.detail;
    } catch {}
    throw new ApiError(detail);
  }
  return res.json();
}

export const api = {
  get: <T,>(path: string) => call<T>("GET", path),
  post: <T,>(path: string, body?: unknown) => call<T>("POST", path, body ?? {}),
  put: <T,>(path: string, body?: unknown) => call<T>("PUT", path, body ?? {}),
};

/** The upload endpoint predates the JSON API and lives outside /api. */
export async function upload(aid: number, files: File[], mode: string) {
  const fd = new FormData();
  fd.append("mode", mode);
  files.forEach((f) => fd.append("files", f));
  const res = await fetch(`/a/${aid}/upload`, { method: "POST", body: fd });
  if (!res.ok) throw new ApiError(`The server answered ${res.status}.`);
  return (await res.json()) as { added: string[]; skipped: string[]; errors: string[] };
}

export type Loaded<T> = { data: T | null; error: string; loading: boolean; reload: () => Promise<void> };

/** GET a path and keep the previous data on screen while it reloads, so polling never flashes. */
export function useGet<T>(path: string | null): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const latest = useRef(path);
  latest.current = path;

  const reload = useCallback(async () => {
    if (path === null) return;
    try {
      const d = await api.get<T>(path);
      if (latest.current === path) {
        setData(d);
        setError("");
      }
    } catch (e) {
      if (latest.current === path) setError((e as Error).message);
    } finally {
      if (latest.current === path) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(true);
    reload();
  }, [reload]);

  return { data, error, loading, reload };
}

export function useInterval(fn: () => void, ms: number | null) {
  const saved = useRef(fn);
  saved.current = fn;
  useEffect(() => {
    if (ms === null) return;
    const id = setInterval(() => saved.current(), ms);
    return () => clearInterval(id);
  }, [ms]);
}

export type Status = { queued: number; processing: number; done: number; failed: number; stamp: string; rescanning: boolean };
export const isBusy = (s: Status | null) => !!s && (s.queued > 0 || s.processing > 0 || s.rescanning);
