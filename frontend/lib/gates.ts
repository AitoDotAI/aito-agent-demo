// The confidence gates, mirroring src/gates.py (tests/test_confidence_display.py
// checks they agree). At or above AUTO_GATE Aito's answer is served as is; below
// ASSIST_GATE a person decides; in between the LLM gets Aito's shortlist.
export const AUTO_GATE = 0.85;
export const ASSIST_GATE = 0.65;

/** A $p as shown: two decimals, three near 1 so 0.998 does not read as a certain 1.00. */
export function fmtP(p: number): string {
  return p >= 0.99 && p < 1 ? p.toFixed(3) : p.toFixed(2);
}

/** A $p as a percentage: one decimal above 99 for the same reason. */
export function pctP(p: number): string {
  const v = p * 100;
  return v >= 99 && v < 100 ? `${v.toFixed(1)}%` : `${Math.round(v)}%`;
}
