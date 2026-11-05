"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { trackEvent } from "@/lib/analytics";
import { MENU_LINK, autoStart, choseAView, escapeClosesTour, presenting, reCollapsePanel, stepsFor, type Step, type Store } from "@/lib/tour";

export const START_TOUR_EVENT = "agent:start-tour";
const SPOT = "tour-spot";
const AUTO_START_DELAY_MS = 900;
/** The widths globals.css switches at: the menu is a drawer at 760 px or narrower, the Aito panel at 1180 px or narrower. */
const isPhone = () => window.matchMedia("(max-width: 760px)").matches;
const panelInline = () => !window.matchMedia("(max-width: 1180px)").matches;
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

/** The element a step points at, if it has one: the menu, or the Aito panel (its button where the panel is a drawer). */
function target(step: Step): Element | null {
  if (step.id === "menu") return document.querySelector(".rc-side");
  if (step.id === "why") return document.querySelector(panelInline() ? ".rc-panel" : ".rc-panel-fab");
  return null;
}

/**
 * The first-visit tour: three steps, skippable at each, shown once (lib/tour.ts has the rules). The menu step shows the menu: on a phone it
 * opens the drawer. The Aito step on a wide desktop opens a collapsed Aito panel for the step without saving that (`previewPanel`, not the
 * edge tab's toggle, which writes `rcPanelCollapsed`), and collapses it again after unless the visitor has hidden it. The card sits below the
 * drawer (`.tour-card` in globals.css), so it never covers what it points at. Going to another view, or closing the drawer, ends or moves the
 * step on, so the card never describes a menu that is not there. "Take the tour" in the menu starts it again.
 */
export default function Tour({ view, label, navOpen, setNavOpen, panelOpen, previewPanel }: {
  view: string; label: string;
  navOpen: boolean; setNavOpen: (open: boolean) => void;
  panelOpen: boolean; previewPanel: (open: boolean) => void;
}) {
  const [steps, setSteps] = useState<Step[]>([]);
  const [index, setIndex] = useState<number | null>(null);
  const card = useRef<HTMLDivElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const openedDrawer = useRef(false);
  const openedPanel = useRef(false);
  const sawDrawerOpen = useRef(false);
  const startedOn = useRef(view);
  const latest = useRef({ view, label, navOpen, panelOpen });
  latest.current = { view, label, navOpen, panelOpen };

  const begin = useCallback((auto: boolean) => {
    const { view: id, label: viewLabel } = latest.current;
    startedOn.current = id;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const viewCount = document.querySelectorAll(MENU_LINK).length;   // what the menu lists now (the support view only once its data is loaded)
    setSteps(stepsFor({ view: { id, label: viewLabel }, viewCount, touch: touchScreen(), panelInline: panelInline() }));
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

  useEffect(() => {
    const start = () => { setNavOpen(false); begin(false); };
    window.addEventListener(START_TOUR_EVENT, start);
    return () => window.removeEventListener(START_TOUR_EVENT, start);
  }, [begin, setNavOpen]);

  const step = index === null ? null : steps[index];
  const stepId = step?.id;

  // Put back what a step opened: the drawer, and a collapsed panel (lib/tour.ts reCollapsePanel).
  const restore = useCallback(() => {
    if (openedDrawer.current) {
      openedDrawer.current = false;
      if (latest.current.navOpen) setNavOpen(false);
    }
    if (reCollapsePanel({ openedByTour: openedPanel.current, openNow: latest.current.panelOpen })) previewPanel(false);
    openedPanel.current = false;
  }, [setNavOpen, previewPanel]);

  const finish = useCallback((how: "tour_skipped" | "tour_completed", reason?: string) => {
    trackEvent(how, { at_step: index === null ? null : index + 1, of: steps.length, ...(reason ? { reason } : {}) });
    document.querySelectorAll(`.${SPOT}`).forEach((el) => el.classList.remove(SPOT));
    restore();
    setIndex(null);
    returnFocus.current?.focus();
  }, [index, steps.length, restore]);

  const go = useCallback((next: number) => {
    setIndex(next);
    trackEvent("tour_step", { step: next + 1, of: steps.length, id: steps[next].id });
  }, [steps]);

  // What the step points at: outlined; the menu step opens the drawer on a phone, the Aito step a collapsed panel; the next step puts it back.
  useEffect(() => {
    document.querySelectorAll(`.${SPOT}`).forEach((el) => el.classList.remove(SPOT));
    sawDrawerOpen.current = false;
    if (!step) return;
    restore();
    if (step.id === "menu" && isPhone() && !latest.current.navOpen) { openedDrawer.current = true; setNavOpen(true); }
    if (step.id === "why" && panelInline() && !latest.current.panelOpen) { openedPanel.current = true; previewPanel(true); }
    target(step)?.classList.add(SPOT);
    card.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stepId]);

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
