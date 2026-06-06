/**
 * Lightweight analytics for the Aito agent demo.
 *
 * The reference shell shipped an Amplitude integration; this demo doesn't carry
 * an Amplitude workspace, so we keep the same public API (initAnalytics /
 * trackPage / trackEvent / identifyUser) but back it with GA4 `gtag` only — no
 * external package, no build-time dependency. If/when this demo gets an
 * Amplitude key, reintroduce `@amplitude/analytics-browser` here behind a
 * dynamic import so the build never hard-fails on a missing module.
 *
 * Everything is a no-op off production hosts (localhost, *.local) and for bots.
 */

const SURFACE = "agent-demo";

type Props = Record<string, unknown>;
type Traits = Record<string, unknown>;

declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

let initialized = false;

function isProductionHost(): boolean {
  if (typeof window === "undefined") return false;
  const host = window.location.hostname;
  return host !== "localhost" && host !== "127.0.0.1" && !host.endsWith(".local");
}

function isBotUserAgent(): boolean {
  if (typeof navigator === "undefined") return false;
  return /bot|crawler|spider|crawling|preview|headless/i.test(navigator.userAgent);
}

function gtagSafe(...args: unknown[]): void {
  if (typeof window !== "undefined" && window.gtag) {
    window.gtag(...args);
  }
}

/** Idempotent; safe under React strict-mode double effects. */
export function initAnalytics(): void {
  if (initialized) return;
  if (typeof window === "undefined") return;
  if (!isProductionHost()) return;
  if (isBotUserAgent()) return;
  initialized = true;
}

export function trackPage(pageName: string, properties: Props = {}): void {
  if (typeof window === "undefined") return;
  gtagSafe("event", "page_view", { page_title: pageName, surface: SURFACE, ...properties });
}

export function trackEvent(event: string, properties: Props = {}): void {
  if (typeof window === "undefined") return;
  gtagSafe("event", event, { surface: SURFACE, ...properties });
}

export function identifyUser(userId: string, traits: Traits = {}): void {
  if (!userId) return;
  if (typeof window === "undefined") return;
  gtagSafe("set", { user_id: userId, ...traits });
}
