// Deep links: every view and its key state live in the URL (`/?view=<view>&<state>`), so a
// pasted link opens exactly that view. Switching views pushes a history entry (back/forward
// work); a state change inside a view replaces the URL, so the address is always shareable.
// Views read their state once at mount (AppShell renders them only after mount, so there is
// no server/client mismatch) and write it back whenever it changes.

/** The query parameters of the current URL (empty during prerender). */
export function urlParams(): URLSearchParams {
  return typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
}

/** One parameter, or `fallback` when absent. */
export function urlParam(key: string, fallback = ""): string {
  return urlParams().get(key) ?? fallback;
}

/** An integer parameter clamped to [0, max], or `fallback`. */
export function urlIndex(key: string, max: number, fallback = 0): number {
  const raw = urlParams().get(key);
  if (raw == null || raw === "") return fallback;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) ? Math.max(-1, Math.min(max, n)) : fallback;
}

/** Merge `updates` into the URL in place (null or "" removes a key); never adds history. */
export function writeUrlState(updates: Record<string, string | number | null | undefined>): void {
  if (typeof window === "undefined") return;
  const p = urlParams();
  for (const [k, v] of Object.entries(updates)) {
    if (v == null || v === "") p.delete(k);
    else p.set(k, String(v));
  }
  const q = p.toString();
  const url = `${window.location.pathname}${q ? `?${q}` : ""}`;
  if (url !== `${window.location.pathname}${window.location.search}`) window.history.replaceState(window.history.state, "", url);
}

/** The URL for a view with no view state: switching views starts from the view's defaults. */
export function viewUrl(view: string): string {
  return view === "home" ? "/" : `/?view=${encodeURIComponent(view)}`;
}
