import { ASSIST_GATE, AUTO_GATE } from "@/lib/gates";

const API_BASE = typeof window !== "undefined"
  ? `${window.location.protocol}//${window.location.host}`
  : "";

export class ApiError extends Error {
  status: number;
  detail: string | null;
  constructor(status: number, detail: string | null, path: string) {
    super(detail || `API ${status}: ${path}`);
    this.status = status;
    this.detail = detail;
  }
}

export interface AitoLatencySample {
  ms: number;
  calls: number;
  path: string;
  at: number;
  /** Per-Aito-call breakdown: e.g. [{op:"_predict", ms:28.4}, {op:"_relate", ms:142.0}].
   *  Sourced from the X-Aito-Ops response header. Empty when the request
   *  didn't hit Aito or the backend is older than the per-op breakdown. */
  ops: { op: string; ms: number }[];
}

type LatencyListener = (sample: AitoLatencySample) => void;
const latencyListeners = new Set<LatencyListener>();

/** One Aito request a route sent (src/query_log.py): the exact body, no credentials. */
export interface AitoQuery { op: string; path: string; env: string; body: Record<string, unknown> | null; ms: number; status: number }
type QueryListener = (path: string, queries: AitoQuery[]) => void;
const queryListeners = new Set<QueryListener>();

/** Subscribe to the queries each /api/* response reports in `_queries` (the side panels render them). */
export function onAitoQueries(fn: QueryListener): () => void {
  queryListeners.add(fn);
  return () => { queryListeners.delete(fn); };
}

export function onAitoLatency(fn: LatencyListener): () => void {
  latencyListeners.add(fn);
  return () => {
    // Set.delete() returns boolean; a void cleanup callback is what
    // React effects expect, so wrap explicitly rather than rely on
    // type coercion.
    latencyListeners.delete(fn);
  };
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  // Surface Aito round-trip ms whenever the backend signals it via
  // X-Aito-Ms (set per-request when any AitoClient call ran). Listeners
  // power the topbar latency badge; endpoints that didn't hit Aito
  // simply emit nothing.
  const ms = res.headers.get("X-Aito-Ms");
  const calls = res.headers.get("X-Aito-Calls");
  const opsHeader = res.headers.get("X-Aito-Ops");
  if (ms != null) {
    const ops = opsHeader
      ? opsHeader.split(",").map((entry) => {
          const i = entry.lastIndexOf(":");
          return i < 0
            ? { op: entry, ms: NaN }
            : { op: entry.slice(0, i), ms: parseFloat(entry.slice(i + 1)) };
        })
      : [];
    const sample: AitoLatencySample = {
      ms: parseFloat(ms),
      calls: parseInt(calls || "1", 10) || 1,
      path,
      at: Date.now(),
      ops,
    };
    for (const fn of latencyListeners) {
      try { fn(sample); } catch { /* listener error must not break API call */ }
    }
  }
  if (!res.ok) {
    let detail: string | null = null;
    try {
      const body = await res.clone().json();
      detail = body?.error || body?.detail || null;
    } catch {}
    throw new ApiError(res.status, detail, path);
  }
  const data = await res.json();
  const queries = data && typeof data === "object" ? (data as { _queries?: AitoQuery[] })._queries : undefined;
  if (Array.isArray(queries) && queries.length) {
    const endpoint = path.split("?")[0];
    for (const fn of queryListeners) {
      try { fn(endpoint, queries); } catch { /* listener error must not break API call */ }
    }
  }
  return data;
}

export function fmtAmount(n: number): string {
  return "\u20AC" + n.toLocaleString("fi-FI", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Colour by the routing gates (lib/gates.ts): green is "would be served as is". */
export function confClass(p: number): string {
  if (p >= AUTO_GATE) return "conf-high";
  if (p >= ASSIST_GATE) return "conf-mid";
  return "conf-low";
}
