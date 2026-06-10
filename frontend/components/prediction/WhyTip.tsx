"use client";

/* A compact "?" explanation popover — the $why affordance other Aito demos use,
   generalised for both predictions (root-cause drivers) and recommendations
   (ranked options). Self-contained inline styling so it works wherever it's
   portaled (it renders to document.body to escape card overflow). */

import { useState, useRef, useEffect, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type WhyRow = {
  label: ReactNode;
  weight: string;                 // e.g. "×1.92" or "85%"
  tone?: "up" | "down" | "best" | "muted";
};

const TONE: Record<string, string> = {
  up: "#c2410c", down: "#1f6f4a", best: "#04221f", muted: "#928d80",
};
const TONE_BG: Record<string, string> = {
  up: "#fbe4d8", down: "#e3f4ea", best: "#d6f3f0", muted: "#f1eee8",
};

export function WhyTip({ title, subtitle, rows, body, footer }: {
  title: string; subtitle?: string; rows?: WhyRow[]; body?: ReactNode; footer?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);

  const place = useCallback(() => {
    if (!btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const W = 300, m = 12, half = W / 2;
    const x = Math.max(half + m, Math.min(window.innerWidth - half - m, r.left + r.width / 2));
    setPos({ top: r.top - 8, left: x });
  }, []);

  useEffect(() => {
    if (!open) return;
    place();
    const onDoc = (e: MouseEvent) => {
      if (pop.current && !pop.current.contains(e.target as Node) && btn.current && !btn.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => { document.removeEventListener("mousedown", onDoc); window.removeEventListener("scroll", place, true); window.removeEventListener("resize", place); };
  }, [open, place]);

  return (
    <>
      <button ref={btn} onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }} title={title}
        style={{
          width: 16, height: 16, borderRadius: "50%", border: "none", cursor: "pointer",
          background: open ? "#16c2b9" : "#cfe9e6", color: open ? "#fff" : "#04221f",
          fontSize: 10, fontWeight: 800, lineHeight: 1, display: "inline-flex", alignItems: "center", justifyContent: "center",
          marginLeft: 5, flexShrink: 0, verticalAlign: "middle",
        }}>?</button>
      {open && pos && createPortal(
        <div ref={pop} style={{
          position: "fixed", top: pos.top, left: pos.left, transform: "translate(-50%, -100%)",
          width: 300, background: "#fff", border: "1px solid #d6cfbe", borderRadius: 10,
          boxShadow: "0 10px 30px rgba(0,0,0,.18)", padding: "13px 15px", zIndex: 10000,
          fontFamily: "'Figtree',ui-sans-serif,system-ui,sans-serif", color: "#16140f",
        }}>
          <div style={{ fontWeight: 800, fontSize: 13 }}>{title}</div>
          {subtitle && <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: "#928d80", marginTop: 2, marginBottom: 9 }}>{subtitle}</div>}
          {body}
          {rows && <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {rows.length === 0 && <div style={{ fontSize: 12, color: "#928d80", fontStyle: "italic" }}>No strong driver beyond the segment / the lever itself.</div>}
            {rows.map((r, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, background: "#faf9f6", border: "1px solid #efeadd", borderRadius: 6, padding: "5px 8px" }}>
                <span style={{ flex: 1, minWidth: 0, fontSize: 12, color: "#56524a" }}>{r.label}</span>
                <span style={{
                  fontFamily: "'JetBrains Mono',monospace", fontSize: 11, fontWeight: 700,
                  color: TONE[r.tone ?? "muted"], background: TONE_BG[r.tone ?? "muted"], padding: "2px 7px", borderRadius: 5,
                }}>{r.weight}</span>
              </div>
            ))}
          </div>}
          {footer && <div style={{ fontSize: 10.5, color: "#928d80", marginTop: 10, lineHeight: 1.5 }}>{footer}</div>}
          <div style={{ position: "absolute", top: "100%", left: "50%", transform: "translateX(-50%)", borderLeft: "6px solid transparent", borderRight: "6px solid transparent", borderTop: "6px solid #d6cfbe" }} />
        </div>,
        document.body,
      )}
    </>
  );
}

export default WhyTip;
