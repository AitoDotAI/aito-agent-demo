/**
 * The first-visit tour's rules, without React so they can be tested without a browser (tests/tour.test.mts).
 *
 * A phone visitor who lands on a deep link (/sales/, ?view=…) sees one view and a ☰ button; the menu with every other view is behind it.
 * The tour is three skippable steps that say what this is, open the menu, and point at the Aito panel. It is shown once.
 * Ported from aito-ecommerce-demo's lib/tour.ts (PR #199): autoStart, choseAView and escapeClosesTour are its rules unchanged. The views
 * here are client state in AppShell, not routes, so a view is an id and a label rather than an href.
 */

export const STORAGE_KEY = "agent.tourSeen";

export interface View { id: string; label: string }
export interface Step { id: "what" | "here" | "menu" | "why"; title: string; text: string }
/** The part of `localStorage` the tour uses. */
export interface Store { getItem(key: string): string | null; setItem(key: string, value: string): void }

/** Whether to start the tour by itself. It does not when storage is missing or throws (a private window, blocked site data):
 *  it could not remember being dismissed, so it would come back on every page. The "Take the tour" link still works then. */
export function shouldAutoStart(store: Store | undefined, key = STORAGE_KEY): boolean {
  try {
    return store?.getItem(key) === null;   // no storage: undefined, which is not null
  } catch {
    return false;
  }
}

export function markSeen(store: Store | undefined, key = STORAGE_KEY): void {
  try {
    store?.setItem(key, "1");
  } catch {
    // The page works without storage; the tour only loses its memory.
  }
}

/** The decision to start the tour by itself, and its one side effect: starting marks it seen, so a reload does not start it again.
 *  A demo being presented (`?demo=`) is left alone and keeps the visitor's first visit for later. */
export function autoStart({ store, demoMode }: { store: Store | undefined; demoMode: boolean }): boolean {
  if (demoMode || !shouldAutoStart(store)) return false;
  markSeen(store);
  return true;
}

/** Whether the demo is being presented: `?demo=` in the address, as on the sibling demos. This demo has no server DEMO_MODE to wait for. */
export function presenting(search: string): boolean {
  return new URLSearchParams(search).has("demo");
}

/** A view's link in the menu. */
export const MENU_LINK = ".rc-side .rc-item";

/** Whether a tap landed on a view in the menu. That ends the tour at once, rather than letting the drawer's closing be read as a step. */
export function choseAView(target: { closest(selector: string): unknown } | null): boolean {
  return Boolean(target?.closest(MENU_LINK));
}

/** Escape belongs to an open dialog before the tour. */
export function escapeClosesTour(otherDialogsOpen: number): boolean {
  return otherDialogsOpen === 0;
}

/** After the Aito step: a panel the visitor had collapsed, and the tour opened for the step without saving that, is collapsed again,
 *  unless the visitor has already hidden it themselves. The visitor's saved preference (`rcPanelCollapsed`) is never written by the tour. */
export function reCollapsePanel({ openedByTour, openNow }: { openedByTour: boolean; openNow: boolean }): boolean {
  return openedByTour && openNow;
}

/** The steps for the view the visitor landed on: a deep link starts with the view they are on, the overview with what this is.
 *  `panelInline` is whether the Aito panel is on screen (a wide desktop) rather than behind the Aito button. */
export function stepsFor({ view, viewCount, touch = true, panelInline = false }:
  { view: View | undefined; viewCount: number; touch?: boolean; panelInline?: boolean }): Step[] {
  const what = "AI agents on fictional company data. Aito answers from that data with live queries, no training.";
  const first: Step = view && view.id !== "home"
    ? { id: "here", title: `You are on ${view.label}`, text: `${what} This is one of ${viewCount} views.` }
    : { id: "what", title: "Agents that answer from your data", text: what };
  return [
    first,
    { id: "menu", title: "All the views are in the menu", text: `There are ${viewCount} views: the agents, their toolboxes and the techniques behind them. ${touch ? "Tap" : "Click"} one to open it.` },
    { id: "why", title: "See the query behind it", text: panelInline
      ? "The Aito panel on the right shows the query behind each view and what it does."
      : "The Aito button, bottom right, opens a panel with the query behind each view and what it does." },
  ];
}
