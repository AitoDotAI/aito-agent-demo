// Aito client for the browser. Tiny — only what every demo actually needs.
// Server-side calls live in src/app.py (FastAPI), not here.
//
// Usage:
//   import { aitoPredict, aitoMatch, aitoSearch, aitoSchema } from "@/lib/aito";
//
//   const r = await aitoPredict<{success_bucket: string}>({
//     from: "submissions",
//     where: { title: "Hello world" },
//     predict: "success_bucket",
//     limit: 5,
//   });
//
// Configure via:
//   NEXT_PUBLIC_AITO_API_URL  (e.g. https://shared.aito.ai/db/your-db)
//   NEXT_PUBLIC_AITO_API_KEY  (read-only key — public exposure is the design)
//   NEXT_PUBLIC_AITO_API_VERSION (v1 by default; set v2 at cutover)
//
// In production these are baked at `next build` time from the same env the
// Python backend reads (the platform's `env:` block in demos.config.yaml).

const API_URL = (process.env.NEXT_PUBLIC_AITO_API_URL || "").replace(/\/$/, "");
const API_KEY = process.env.NEXT_PUBLIC_AITO_API_KEY || "";
const API_VERSION = process.env.NEXT_PUBLIC_AITO_API_VERSION || "v1";
if (API_VERSION !== "v1" && API_VERSION !== "v2") {
  throw new Error("NEXT_PUBLIC_AITO_API_VERSION must be v1 or v2");
}
const apiPath = (op: string) => `/api/${API_VERSION}/${op}`;

if (typeof window !== "undefined" && (!API_URL || !API_KEY)) {
  // Don't crash render — surface in console + return errors from the call below.
  // (Real fix: set NEXT_PUBLIC_AITO_API_URL / _API_KEY in your env.)
  console.warn(
    "lib/aito.ts: NEXT_PUBLIC_AITO_API_URL or NEXT_PUBLIC_AITO_API_KEY is unset. " +
      "Set them in .env or via the platform's demos.config.yaml `env:` block.",
  );
}

export type PredictHit<T = unknown> = {
  feature: T;
  $value: T;
  $p: number;
  $why?: unknown;
};

export type MatchHit = PredictHit;

async function post<R>(endpoint: string, body: unknown): Promise<R> {
  if (!API_URL || !API_KEY) {
    throw new Error("Aito client not configured (NEXT_PUBLIC_AITO_API_URL / _KEY missing)");
  }
  const r = await fetch(`${API_URL}${endpoint}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": API_KEY,
    },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    throw new Error(`Aito ${endpoint} returned ${r.status}: ${text.slice(0, 200)}`);
  }
  const result = await r.json();
  // Publish both spellings on v1 and v2, as the Python client does.
  for (const hit of result.hits || []) {
    if ("$value" in hit && !("feature" in hit)) hit.feature = hit.$value;
    if ("feature" in hit && !("$value" in hit)) hit.$value = hit.feature;
  }
  return result as R;
}

/** Predict the value of `predict` given the constraints in `where`. */
export function aitoPredict<T = unknown>(query: {
  from: string;
  where: Record<string, unknown>;
  predict: string;
  limit?: number;
}): Promise<{ hits: PredictHit<T>[] }> {
  return post(apiPath("_predict"), { limit: 5, ...query });
}

/** Rank values of the match field by probability. */
export function aitoMatch(query: {
  from: string;
  where: Record<string, unknown>;
  match: string;
  limit?: number;
}): Promise<{ hits: MatchHit[] }> {
  return post(apiPath("_match"), { limit: 5, ...query });
}

/** Full-text + filters; v2 similarity ordering requires a $match where term. */
export function aitoSearch<T = Record<string, unknown>>(query: {
  from: string;
  where?: Record<string, unknown>;
  orderBy?: string | { field: string; desc?: boolean };
  limit?: number;
}): Promise<{ hits: T[] }> {
  return post(apiPath("_search"), { limit: 10, ...query });
}

/** Schema of the configured DB (tables + column types). Cheap. */
export function aitoSchema(): Promise<{ schema: Record<string, unknown> }> {
  // GET, not POST — schema is special-cased
  if (!API_URL || !API_KEY) {
    return Promise.reject(new Error("Aito client not configured"));
  }
  return fetch(`${API_URL}${apiPath("schema")}`, {
    headers: { "x-api-key": API_KEY },
  }).then((r) => {
    if (!r.ok) throw new Error(`Aito /schema returned ${r.status}`);
    return r.json();
  });
}
