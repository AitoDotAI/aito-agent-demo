// Run: node --test tests/ (./do frontend-test once the tour's PR lands). How a $p is printed beside the band it decides (lib/gates.ts).
import assert from "node:assert/strict";
import test from "node:test";

import { ASSIST_GATE, AUTO_GATE, fmtP, pctP } from "../lib/gates.ts";

test("a $p just under a gate never prints as the gate: the number and the band cannot seem to disagree", () => {
  assert.equal(pctP(0.8496), "84.96%");   // assist band; a rounded "85%" would read as auto
  assert.equal(pctP(0.6496), "64.96%");   // handoff band; a rounded "65%" would read as assist
  assert.equal(fmtP(0.8496), "0.8496");
  assert.equal(fmtP(0.6496), "0.6496");
});

test("a $p a hair under the gate is truncated, not rounded, so it stays under", () => {
  assert.equal(pctP(0.849999), "84.99%");
  assert.equal(fmtP(0.849999), "0.8499");
});

test("at a gate and away from one, the plain format stays", () => {
  assert.equal(pctP(AUTO_GATE), "85%");
  assert.equal(pctP(ASSIST_GATE), "65%");
  assert.equal(pctP(0.8443), "84%");
  assert.equal(pctP(0.8512), "85%");
  assert.equal(pctP(0.42), "42%");
  assert.equal(fmtP(0.85), "0.85");
  assert.equal(fmtP(0.844), "0.84");
});

test("near 1 the extra digit stays, so 0.998 does not read as certain", () => {
  assert.equal(pctP(0.9984), "99.8%");
  assert.equal(fmtP(0.998), "0.998");
});

test("whatever the $p, the printed value is on the same side of each gate as the $p", () => {
  for (let i = 0; i <= 10000; i++) {
    const p = i / 10000;
    for (const g of [AUTO_GATE, ASSIST_GATE]) {
      assert.equal(parseFloat(pctP(p)) / 100 < g, p < g, `pctP(${p}) = ${pctP(p)} vs gate ${g}`);
      assert.equal(parseFloat(fmtP(p)) < g, p < g, `fmtP(${p}) = ${fmtP(p)} vs gate ${g}`);
    }
  }
});
