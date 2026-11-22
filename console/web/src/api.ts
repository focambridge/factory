// Thin client for the console's local API.

export class ApiError extends Error {}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError((data as { error?: string }).error || `Request failed (${res.status})`);
  return data as T;
}

export const api = {
  get: <T = any>(path: string) => request<T>("GET", path),
  post: <T = any>(path: string, body: unknown = {}) => request<T>("POST", path, body),
  put: <T = any>(path: string, body: unknown) => request<T>("PUT", path, body),
  del: <T = any>(path: string) => request<T>("DELETE", path),
};

export const enc = encodeURIComponent;

export function projectPath(p: string) {
  return `/api/projects/${enc(p)}`;
}
export function batchPath(p: string, u: string, b: string) {
  return `${projectPath(p)}/units/${enc(u)}/batches/${enc(b)}`;
}
export function projectFileUrl(p: string, rel: string) {
  return `${projectPath(p)}/file?path=${enc(rel)}`;
}
export function workspaceFileUrl(p: string, rel: string) {
  return `${projectPath(p)}/workspace/file?path=${enc(rel)}`;
}

export async function openInFinder(path: string) {
  return api.post("/api/open", { path });
}
