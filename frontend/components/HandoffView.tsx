"use client";

import { useState } from "react";
import ConfidenceBar from "@/components/prediction/ConfidenceBar";
import PredictionBadge from "@/components/prediction/PredictionBadge";
import type { Alternative } from "@/lib/types";

type HItem = { text: string; intent: string; p: number; alts: Alternative[]; reason: string; team: string };
export type HandoffData = { total: number; counts: { auto: number; assist: number; handoff: number }; handoff: HItem[] };

const ACTION: Record<string, string> = {
  cancel_service: "cancel a service", refund: "issue a refund", check_outage: "outage status",
  find_shop: "shop lookup", repair_help: "device repair", check_balance: "account balance",
};

export function HandoffView({ data, loading }: { data: HandoffData | null; loading: boolean }) {
  const c = data?.counts;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  return (
    <div className="rc-body">
      <div className="rc-kpis">
        <div className="rc-kpi"><div className="kl">In the queue</div><div className="kv">{data?.total ?? "—"}</div><div className="ks">incoming tickets, triaged by confidence</div></div>
        <div className="rc-kpi"><div className="kl">Auto-resolved</div><div className="kv t">{c ? c.auto : "—"}</div><div className="ks">no human, no LLM, Aito was sure</div></div>
        <div className="rc-kpi"><div className="kl">Assisted</div><div className="kv">{c ? c.assist : "—"}</div><div className="ks">Aito + LLM on the shortlist</div></div>
        <div className="rc-kpi"><div className="kl">Handed to you</div><div className="kv p">{c ? c.handoff : "—"}</div><div className="ks">unsure, or money/state-change</div></div>
      </div>

      <div className="rc-h">The agent knows what it doesn&apos;t know</div>
      <div className="rc-sub">Aito triages the queue by its own <b>calibrated confidence</b>. It resolves the sure ones outright, and <b>hands you only the rest</b>: the genuinely ambiguous, and anything that touches money or state. It never guesses on those. And it doesn&apos;t hand them over blank: you get its <b>tentative read, its confidence, and why</b>, so you start informed.</div>
      <div className="rc-caveat" role="note">
        <b>Known limit, being fixed:</b>{" "}a vague or off-topic ticket that shares a few words with past ones can still get a
        confident answer (&ldquo;What&apos;s the weather like in Oulu tomorrow?&rdquo; reads as a cancellation at 91%), so some
        tickets below are resolved that should come to you. Aito is adding a measure of how much of a ticket&apos;s wording it
        has seen, which this queue will route on.
      </div>

      {loading && !data && <div className="rc-typing" style={{ padding: "20px 0" }}><span>triaging the queue…</span></div>}

      {data && (
        <div className="rc-col aito" style={{ borderTopColor: "var(--purple)" }}>
          <div className="rc-colh"><span className="tag" style={{ background: "rgba(124,108,255,.13)", color: "var(--plight)" }}>human handoff</span><span className="ct">Your queue · {data.handoff.length}</span></div>
          <div className="rc-cbody" style={{ minHeight: 0, padding: 0 }}>
            {data.handoff.map((h, i) => {
              const lowconf = h.reason.startsWith("low confidence");
              return (
                <div key={i} style={{ padding: "14px 16px", borderBottom: i < data.handoff.length - 1 ? "1px solid #f1efe8" : "none" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, flexWrap: "wrap" }}>
                    <span style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 10, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase", padding: "3px 8px", borderRadius: 6,
                      background: lowconf ? "#fff3e7" : "var(--gold-soft)", color: lowconf ? "#9a5512" : "var(--gold-ink)", border: `1px solid ${lowconf ? "#f0d4b0" : "var(--gold-line)"}` }}>
                      {lowconf ? "⚠ unsure" : "🔒 verify"}
                    </span>
                    <span style={{ fontSize: 12.5, color: "var(--rc-ink2)" }}>{h.reason}</span>
                    <span style={{ marginLeft: "auto", fontFamily: "'JetBrains Mono',monospace", fontSize: 11, color: "var(--rc-faint)" }}>→ {h.team}</span>
                  </div>
                  <div style={{ fontSize: 14, color: "var(--rc-ink)", marginBottom: 10 }}>{h.text}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 11.5, color: "var(--rc-faint)" }}>Aito&apos;s tentative read</span>
                    <PredictionBadge value={h.intent} confidence={h.p} alternatives={h.alts} />
                    <div style={{ width: 150 }}><ConfidenceBar value={h.p} /></div>
                    {picked.has(h.text)
                      ? <span style={{ marginLeft: "auto", fontSize: 12, color: "var(--rc-faint)" }}>✓ Yours (demo: nothing was assigned)</span>
                      : <button onClick={() => setPicked((s) => new Set(s).add(h.text))} style={{ marginLeft: "auto", fontWeight: 700, fontSize: 12.5, background: "var(--purple)", color: "#fff", border: "none", borderRadius: 7, padding: "7px 14px", cursor: "pointer" }}>Pick up →</button>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="rc-foot">Live: each ticket scored by a real Aito `_predict` over learned history. The split is the calibration doing governance: auto when sure, human when not, verification on anything that changes money or state.</div>
    </div>
  );
}
