import { confClass } from "@/lib/api";
import { fmtP } from "@/lib/gates";

export default function ConfidenceBar({ value }: { value: number }) {
  // The real $p, never capped: near 1 it shows three decimals (0.998), so a very
  // sure answer does not round to a certain-looking 1.00.
  const pct = Math.round(value * 100);
  return (
    <div className="conf">
      <div className="conf-bar">
        <div className={`conf-fill ${confClass(value)}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="conf-val">{fmtP(value)}</span>
    </div>
  );
}
