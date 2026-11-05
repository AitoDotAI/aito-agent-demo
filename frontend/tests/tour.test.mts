// Run: ./do frontend-test (node --test). The tour's rules live in lib/tour.ts without React, so they are tested without a browser.
import assert from "node:assert/strict";
import test from "node:test";

import {
  MENU_LINK, STORAGE_KEY, autoStart, choseAView, escapeClosesTour, markSeen, presenting, reCollapsePanel, shouldAutoStart, stepsFor, type View,
} from "../lib/tour.ts";

const HOME: View = { id: "home", label: "Overview" };
const SALES: View = { id: "sales", label: "Opportunity Assistant" };
const memory = (initial: Record<string, string> = {}) => {
  const data = { ...initial };
  return { getItem: (key: string) => data[key] ?? null, setItem: (key: string, value: string) => { data[key] = value; }, data };
};
const broken = { getItem: () => { throw new Error("storage blocked"); }, setItem: () => { throw new Error("storage blocked"); } };

test("a first visit starts the tour", () => {
  assert.equal(shouldAutoStart(memory()), true);
});

test("a visitor who has seen the tour is not shown it again", () => {
  const storage = memory();
  markSeen(storage);
  assert.equal(shouldAutoStart(storage), false);
});

test("the tour keeps its own storage key, apart from the Aito panel's", () => {
  const storage = memory();
  markSeen(storage);
  assert.deepEqual(Object.keys(storage.data), [STORAGE_KEY]);
  assert.notEqual(STORAGE_KEY, "rcPanelCollapsed");
});

test("the tour does not start when storage throws, since it could not remember being dismissed", () => {
  assert.equal(shouldAutoStart(broken), false);
});

test("the tour does not start when there is no storage at all, and nothing is written", () => {
  assert.equal(shouldAutoStart(undefined), false);
  assert.equal(autoStart({ store: undefined, demoMode: false }), false);
});

test("marking the tour seen does not throw when storage does", () => {
  assert.doesNotThrow(() => markSeen(broken));
});

test("starting by itself marks the tour seen, so a reload does not start it again", () => {
  const storage = memory();
  assert.equal(autoStart({ store: storage, demoMode: false }), true);
  assert.equal(shouldAutoStart(storage), false);
  assert.equal(autoStart({ store: storage, demoMode: false }), false);
});

test("a demo being presented (?demo=) does not start the tour and does not use up the visitor's first visit", () => {
  const storage = memory();
  assert.equal(autoStart({ store: storage, demoMode: true }), false);
  assert.deepEqual(storage.data, {});
});

test("?demo= in the address means the demo is being presented, whatever its value", () => {
  assert.equal(presenting("?demo=1"), true);
  assert.equal(presenting("?view=sales&demo="), true);
  assert.equal(presenting("?view=sales"), false);
  assert.equal(presenting(""), false);
});

test("broken storage does not start the tour and does not throw", () => {
  assert.equal(autoStart({ store: broken, demoMode: false }), false);
});

test("on the overview the tour starts with what this is, then the menu, then the Aito panel", () => {
  const steps = stepsFor({ view: HOME, viewCount: 12 });
  assert.deepEqual(steps.map((s) => s.id), ["what", "menu", "why"]);
  assert.match(steps[1].text, /12 views/);
});

test("on a deep link the tour starts with the view the visitor is on, then the menu", () => {
  const steps = stepsFor({ view: SALES, viewCount: 12 });
  assert.deepEqual(steps.map((s) => s.id), ["here", "menu", "why"]);
  assert.match(steps[0].title, /You are on Opportunity Assistant/);
  assert.match(steps[0].text, /one of 12 views/);
});

test("an unknown view gets the overview's tour", () => {
  assert.deepEqual(stepsFor({ view: undefined, viewCount: 12 }).map((s) => s.id), ["what", "menu", "why"]);
});

test("the menu step says tap on a phone and click on a desktop", () => {
  assert.match(stepsFor({ view: HOME, viewCount: 12, touch: true })[1].text, /Tap/);
  assert.match(stepsFor({ view: HOME, viewCount: 12, touch: false })[1].text, /Click/);
});

test("the Aito step points at the button where the panel is a drawer, and at the panel where it is on screen", () => {
  assert.match(stepsFor({ view: HOME, viewCount: 12, panelInline: false })[2].text, /Aito button/);
  assert.match(stepsFor({ view: HOME, viewCount: 12, panelInline: true })[2].text, /panel on the right/);
});

test("no step uses an em dash", () => {
  for (const view of [HOME, SALES]) for (const touch of [true, false]) for (const panelInline of [true, false]) {
    for (const s of stepsFor({ view, viewCount: 12, touch, panelInline })) assert.doesNotMatch(s.title + s.text, /—/);
  }
});

test("a tap on a view in the menu is recognised, a tap elsewhere is not", () => {
  const inMenu = { closest: (selector: string) => (selector === MENU_LINK ? {} : null) };
  const elsewhere = { closest: () => null };
  assert.equal(choseAView(inMenu), true);
  assert.equal(choseAView(elsewhere), false);
  assert.equal(choseAView(null), false);
});

test("Escape closes the tour only when no other dialog is open to take it", () => {
  assert.equal(escapeClosesTour(0), true);
  assert.equal(escapeClosesTour(1), false);
});

test("the panel the tour opened is hidden again after, unless the visitor hid it themselves", () => {
  assert.equal(reCollapsePanel({ openedByTour: true, visitorChanged: false, openNow: true }), true);
  assert.equal(reCollapsePanel({ openedByTour: true, visitorChanged: true, openNow: false }), false);   // the visitor hid it: nothing to undo
  assert.equal(reCollapsePanel({ openedByTour: false, visitorChanged: false, openNow: true }), false);  // it was open before the tour: leave it
});

test("a visitor who hides and re-shows the panel during the step keeps it shown, as they saved it", () => {
  assert.equal(reCollapsePanel({ openedByTour: true, visitorChanged: true, openNow: true }), false);
});
