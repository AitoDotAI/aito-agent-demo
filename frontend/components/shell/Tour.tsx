"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { trackEvent } from "@/lib/analytics";
import {
  autoStart, choseAView, escapeClosesTour, focusAfter, presenting, reCollapsePanel, restartEvent, stepsFor, targetFor, type Step, type Store,
} from "@/lib/tour";

export const START_TOUR_EVENT = "agent:start-tour";
const SPOT = "tour-spot";
const AUTO_START_DELAY_MS = 900;
/** The widths globals.css switches at: the menu is a drawer at 760 px or narrower, the Aito panel at 1180 px or narrower. */
const isPhone = () => window.matchMedia("(max-width: 760px)").matches;
const PANEL_DRAWER = "(max-width: 1180px)";
/** A touch screen, at any width: a phone turned sideways shows the menu inline, and is still tapped. */
const touchScreen = () => window.matchMedia("(pointer: coarse)").matches;

/** `localStorage`, or nothing where reading it throws (private window, blocked site data). */
function storage(): Store | undefined {
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/**
 * The first-visit tour: three steps, skippable at each, shown once (lib/tour.ts has the rules). The menu step shows the menu: on a phone it
 * opens the drawer. The Aito step on a wide desktop opens a collapsed Aito panel for the step without saving that (`previewPanel`, not the
 * edge tab's toggle, which writes `rcPanelCollapsed`), and collapses it again after unless the visitor has hidden it. The card sits below the
 * drawer (`.tour-card` in globals.css), so it never covers what it points at. Going to another view, or closing the drawer, ends or moves the
 * step on, so the card never describes a menu that is not there. A resize across 1180 px moves the Aito step between the panel and its button.
 * "Take the tour" in the menu starts it again, closing a running tour as skipped first.
 */
export default function Tour({ view, label, viewCount, navOpen, setNavOpen, panelOpen, previewPanel }: {
  view: string; label: string;
  /** How many views the menu lists now: it grows when the support view's data answers, so the steps are worded at each render. */
  viewCount: number;
  navOpen: boolean; setNavOpen: (open: boolean) => void;
  panelOpen: boolean; previewPanel: (open: boolean) => void;
}) {
  const [start, setStart] = useState<{ id: string; label: string; touch: boolean } | null>(null);
  const [index, setIndex] = useState<number | null>(null);
  const [inline, setInline] = useState(false);   // the Aito panel is on screen (wider than 1180 px), followed live
  const steps: Step[] = start ? stepsFor({ view: { id: start.id, label: start.label }, viewCount, touch: start.touch, panelInline: inline }) : [];
  const card = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const openedDrawer = useRef(false);
  const openedPanel = useRef(false);
  const panelSetTo = useRef<boolean | null>(null);   // the value the tour last gave the panel, so its own change is not read as the visitor's
  const visitorChangedPanel = useRef(false);
  const sawDrawerOpen = useRef(false);
  const startedOn = useRef(view);
  const latest = useRef({ view, label, navOpen, panelOpen, index, of: steps.length });
  latest.current = { view, label, navOpen, panelOpen, index, of: steps.length };

  useEffect(() => {
    const drawer = window.matchMedia(PANEL_DRAWER);
    const follow = () => setInline(!drawer.matches);
    follow();
    drawer.addEventListener("change", follow);
    return () => drawer.removeEventListener("change", follow);
  }, []);

  const begin = useCallback((auto: boolean) => {
    const { view: id, label: viewLabel } = latest.current;
    startedOn.current = id;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    returnFocus.current = focusAfter({ openerInDrawer: Boolean(opener?.closest(".rc-side")), phone: isPhone() }) === "burger"
      ? document.querySelector<HTMLElement>(".rc-burger") : opener;
    setStart({ id, label: viewLabel, touch: touchScreen() });
    setIndex(0);
    trackEvent("tour_started", { view: viewLabel, auto });
  }, []);

  // First visit: start by itself, once, unless the demo is being presented (`?demo=`).
  useEffect(() => {
    const timer = setTimeout(() => {
      if (autoStart({ store: storage(), demoMode: presenting(window.location.search) })) begin(true);
    }, AUTO_START_DELAY_MS);
    return () => clearTimeout(timer);
  }, [begin]);

  const step = index === null ? null : steps[index];
  const stepId = step?.id;

  // Put back what a step opened: the drawer, and a collapsed panel (lib/tour.ts reCollapsePanel).
  const restore = useCallback(() => {
    if (openedDrawer.current) {
      openedDrawer.current = false;
      if (latest.current.navOpen) setNavOpen(false);
    }
    if (reCollapsePanel({ openedByTour: openedPanel.current, visitorChanged: visitorChangedPanel.current, openNow: latest.current.panelOpen })) {
      panelSetTo.current = false;
      previewPanel(false);
    }
    openedPanel.current = false;
    visitorChangedPanel.current = false;
  }, [setNavOpen, previewPanel]);

  const finish = useCallback((how: "tour_skipped" | "tour_completed", reason?: string) => {
    trackEvent(how, { at_step: index === null ? null : index + 1, of: steps.length, ...(reason ? { reason } : {}) });
    document.querySelectorAll(`.${SPOT}`).forEach((el) => el.classList.remove(SPOT));
    restore();
    setIndex(null);
    returnFocus.current?.focus();
  }, [index, steps.length, restore]);

  // "Take the tour": a running tour is closed as skipped (reason restarted) and put back, then it starts over.
  useEffect(() => {
    const start = () => {
      const replaced = restartEvent({ index: latest.current.index, of: latest.current.of });
      if (replaced) {
        trackEvent("tour_skipped", replaced);
        document.querySelectorAll(`.${SPOT}`).forEach((el) => el.classList.remove(SPOT));
        restore();
      }
      setNavOpen(false);
      begin(false);
    };
    window.addEventListener(START_TOUR_EVENT, start);
    return () => window.removeEventListener(START_TOUR_EVENT, start);
  }, [begin, setNavOpen, restore]);

  const go = useCallback((next: number) => {
    setIndex(next);
    trackEvent("tour_step", { step: next + 1, of: steps.length, id: steps[next].id });
  }, [steps]);

  // What the step points at: outlined; the menu step opens the drawer on a phone, the Aito step a collapsed panel; the next step puts it back.
  // The Aito step runs again when the width crosses 1180 px, so it moves between the panel and its button.
  const whyInline = stepId === "why" && inline;
  useEffect(() => {
    document.querySelectorAll(`.${SPOT}`).forEach((el) => el.classList.remove(SPOT));
    sawDrawerOpen.current = false;
    if (!step) return;
    restore();
    if (step.id === "menu" && isPhone() && !latest.current.navOpen) { openedDrawer.current = true; setNavOpen(true); }
    if (whyInline && !latest.current.panelOpen) { openedPanel.current = true; panelSetTo.current = true; previewPanel(true); }
    const spot = targetFor(step.id, inline);
    if (spot) document.querySelector(spot)?.classList.add(SPOT);
    card.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId, whyInline]);

  // The panel changed: by the tour (the value it set), or by the visitor during the step, who then owns it (reCollapsePanel).
  useEffect(() => {
    if (panelSetTo.current === panelOpen) { panelSetTo.current = null; return; }
    if (openedPanel.current) visitorChangedPanel.current = true;
  }, [panelOpen]);

  // The card's height tells the drawer how much room to leave (`.tour-menu .rc-side` in globals.css).
  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle("tour-menu", stepId === "menu");
    if (card.current) root.style.setProperty("--tour-card-h", `${card.current.offsetHeight}px`);
    return () => { root.classList.remove("tour-menu"); };
  }, [stepId]);

  // Escape closes the tour wherever the focus is.
  useEffect(() => {
    if (index === null) return;
    const close = (press: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[role="dialog"]:not(.tour-card)').length;
      if (press.key === "Escape" && escapeClosesTour(dialogs)) finish("tour_skipped", "escape");
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [index, finish]);

  // Tapping a view in the menu ends the tour there. Without this the drawer closing would be read as the visitor moving on to the next step.
  useEffect(() => {
    if (index === null) return;
    const tapped = (tap: MouseEvent) => { if (choseAView(tap.target instanceof Element ? tap.target : null)) finish("tour_skipped", "chose_a_view"); };
    document.addEventListener("click", tapped, true);
    return () => document.removeEventListener("click", tapped, true);
  }, [index, finish]);

  // Going to another view (the overview's buttons, back/forward) ends the tour: its steps were written for the view it started on.
  useEffect(() => {
    if (index !== null && view !== startedOn.current) finish("tour_skipped", "left_the_view");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  // The visitor closed the drawer (the backdrop, or ☰) during the menu step: the menu is no longer what the card describes, so move on.
  useEffect(() => {
    if (stepId !== "menu" || index === null) return;
    if (navOpen) { sawDrawerOpen.current = true; return; }
    if (sawDrawerOpen.current) {
      openedDrawer.current = false;
      if (index < steps.length - 1) go(index + 1);
    }
  }, [navOpen, stepId, index, steps.length, go]);

  if (!step || index === null) return null;
  const last = index === steps.length - 1;
  return (
    <div className="tour-card" ref={card} role="dialog" aria-labelledby="tour-title" tabIndex={-1}>
      <div className="tour-count">{index + 1} of {steps.length}</div>
      <div className="tour-title" id="tour-title">{step.title}</div>
      <div className="tour-text" aria-live="polite">{step.text}</div>
      <div className="tour-actions">
        <button type="button" className="tour-skip" onClick={() => finish("tour_skipped")}>{last ? "Close" : "Skip tour"}</button>
        <button type="button" className="tour-next" onClick={() => (last ? finish("tour_completed") : go(index + 1))}>{last ? "Done" : "Next"}</button>
      </div>
    </div>
  );
}
