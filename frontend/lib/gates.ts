// The confidence gates, mirroring src/gates.py (tests/test_confidence_display.py
// checks they agree). At or above AUTO_GATE Aito's answer is served as is; below
// ASSIST_GATE a person decides; in between the LLM gets Aito's shortlist.
export const AUTO_GATE = 0.85;
export const ASSIST_GATE = 0.65;

/** Whether a printed value sits on the other side of a gate from the $p it prints: 0.8496 rounded to "0.85" or "85%" reads as auto
 *  beside the assist band it is in. */
function crossesGate(p: number, shown: number): boolean {
  return [AUTO_GATE, ASSIST_GATE].some((g) => (p < g) !== (shown < g));
}

/** The $p cut (not rounded) to four decimals, so a value under a gate stays under it. Rounded to 6 places first so float noise
 *  (0.6496 * 10000 = 6495.999…) does not cut a digit off. */
const truncated4 = (p: number) => Math.floor(Math.round(p * 1e6) / 100) / 1e4;

/** A $p as shown: two decimals, three near 1 so 0.998 does not read as a certain 1.00; four, cut, where two would cross a gate. */
export function fmtP(p: number): string {
  const shown = p >= 0.99 && p < 1 ? p.toFixed(3) : p.toFixed(2);
  return crossesGate(p, parseFloat(shown)) ? truncated4(p).toFixed(4) : shown;
}

/** A $p as a percentage: one decimal above 99 for the same reason; two, cut, where a whole percent would cross a gate ("84.96%"). */
export function pctP(p: number): string {
  const v = p * 100;
  const shown = v >= 99 && v < 100 ? v.toFixed(1) : `${Math.round(v)}`;
  return crossesGate(p, parseFloat(shown) / 100) ? `${(truncated4(p) * 100).toFixed(2)}%` : `${shown}%`;
}
