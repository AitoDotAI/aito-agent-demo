"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ConfidenceBar from "@/components/prediction/ConfidenceBar";
import { apiFetch, ApiError } from "@/lib/api";

type Pick = { tool: string; latency_ms: number; tokens: number; cost_usd: number; n_tools: number };
type Route = {
  text: string; catalog_size: number; shortlist: { tool: string; p: number }[];
  aito_ms: number | null; aito_top_p: number | null; llm_full: Pick; llm_coop: Pick | null; model: string;
};

const SAMPLES = [
  "Data is crawling whenever I travel abroad.",
  "I was billed twice for September.",
  "My replacement SIM still has no signal.",
  "I'd like to order the new 5G router.",
  "Switch me to the unlimited data plan.",
];

export function AugmentView({ onAito }: { onAito?: (ms: number | null) => void }) {
  const [text, setText] = useState(SAMPLES[0]);
  const [active, setActive] = useState(0);
  const [r, setR] = useState<Route | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const timer = useRef<number | null>(null);

  const run = useCallback((t: string) => {
    setR(null); setErr(null); setLoading(true); setElapsed(0);
    const t0 = performance.now();
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => setElapsed(performance.now() - t0), 80);
    apiFetch<Route>(`/api/route?text=${encodeURIComponent(t)}`)
      .then((d) => { setR(d); onAito?.(d.aito_ms); })
      .catch((e: ApiError) => setErr(e?.detail || "route failed"))
      .finally(() => { setLoading(false); if (timer.current) window.clearInterval(timer.current); });
  }, [onAito]);

  useEffect(() => { run(SAMPLES[0]); }, [run]);

  const pick = (i: number) => { setActive(i); setText(SAMPLES[i]); run(SAMPLES[i]); };

  const full = r?.llm_full;
  const coop = r?.llm_coop;
  const tokFactor = full && coop && coop.tokens ? Math.round(full.tokens / coop.tokens) : null;
  const speedFactor = full && coop && coop.latency_ms ? (full.latency_ms / coop.latency_ms) : null;
  const top = r?.aito_top_p ?? null;

  return (
    <div className="rc-body">
      <div className="rc-kpis">
        <div className="rc-kpi"><div className="kl">Tool catalog</div><div className="kv">{r?.catalog_size ?? 240}</div><div className="ks">backend tools the LLM must consider</div></div>
        <div className="rc-kpi"><div className="kl">Prompt tokens</div><div className="kv t">{tokFactor ? `${tokFactor}× less` : "—"}</div><div className="ks">{full && coop ? `${full.tokens.toLocaleString()} → ${coop.tokens}` : "after Aito shortlists"}</div></div>
        <div className="rc-kpi"><div className="kl">Latency</div><div className="kv t">{speedFactor ? `${speedFactor.toFixed(1)}×` : "—"}</div><div className="ks">faster on the shortlist</div></div>
        <div className="rc-kpi"><div className="kl">Aito top confidence</div><div className="kv">{top != null ? `${Math.round(Math.min(top, 0.99) * 100)}%` : "—"}</div><div className="ks">{top != null && top >= 0.9 ? "above gate — LLM optional" : "→ hand the shortlist to the LLM"}</div></div>
      </div>

      <div className="rc-h">Aito augments the LLM — it doesn&apos;t replace it</div>
      <div className="rc-sub">The same model, two ways. <b>Alone</b>, the LLM weighs all {r?.catalog_size ?? 240} tools every time. <b>With Aito</b>, <code>_predict</code> short-lists the handful history says are relevant — the LLM then decides over just those, so it&apos;s faster, far cheaper, and grounded. When Aito is confident enough, the LLM isn&apos;t needed at all.</div>

      <div className="rc-ctl">
        {SAMPLES.map((s, i) => <button key={i} className={`rc-chip ${active === i ? "on" : ""}`} onClick={() => pick(i)}>{s.length > 30 ? s.slice(0, 30) + "…" : s}</button>)}
      </div>
      <div className="rc-ticket">
        <textarea rows={1} value={text} onChange={(e) => setText(e.target.value)} />
        <button className="rc-run" disabled={loading} onClick={() => run(text)}>{loading ? "Routing…" : "▶ Route"}</button>
      </div>

      {/* Aito shortlist */}
      <div className="rc-col aito" style={{ marginBottom: 16 }}>
        <div className="rc-colh"><span className="tag">aito._predict</span><span className="ct">Short-list · {r?.catalog_size ?? 240} → {r?.shortlist.length ?? 5}</span><span className="ms">{r?.aito_ms != null ? `${r.aito_ms.toFixed(0)}ms` : loading ? "…" : ""}</span></div>
        <div className="rc-cbody" style={{ minHeight: 0 }}>
          {!r && loading && <div className="rc-typing"><span>predicting…</span></div>}
          {r && r.shortlist.map((s, i) => (
            <div key={s.tool} style={{ display: "flex", alignItems: "center", gap: 12, padding: "5px 0", opacity: i === 0 ? 1 : 0.72 }}>
              <span className="pred-badge" style={{ minWidth: 150 }}>{s.tool}</span>
              <div style={{ flex: 1, maxWidth: 220 }}><ConfidenceBar value={s.p} /></div>
            </div>
          ))}
          <div className="rc-meta">history says these are the relevant tools — the other {(r?.catalog_size ?? 240) - (r?.shortlist.length ?? 5)} never apply here</div>
        </div>
      </div>

      {/* two LLM runs */}
      <div className="rc-cols">
        <div className="rc-col llm">
          <div className="rc-colh"><span className="tag">llm alone</span><span className="ct">LLM · all {r?.catalog_size ?? 240} tools</span><span className="ms">{loading ? `${(elapsed / 1000).toFixed(1)}s` : full ? `${(full.latency_ms / 1000).toFixed(2)}s` : ""}</span></div>
          <div className="rc-cbody">
            {loading && <div className="rc-typing"><i /><i /><i /><span>reasoning over {r?.catalog_size ?? 240} tools…</span></div>}
            {err && !loading && <div style={{ color: "var(--rc-rust)", fontSize: 13 }}>⚠ {err}</div>}
            {full && (<>
              <div className="rc-act">{full.tool}()</div>
              <div className="rc-meta">{full.n_tools} tools in prompt · <b style={{ color: "var(--rc-ink2)" }}>{full.tokens.toLocaleString()} tokens</b> · ${full.cost_usd.toFixed(5)} · {full.latency_ms.toFixed(0)}ms</div>
            </>)}
          </div>
        </div>
        <div className="rc-col aito">
          <div className="rc-colh"><span className="tag">llm + aito</span><span className="ct">LLM · Aito&apos;s {r?.shortlist.length ?? 5}</span><span className="ms">{coop ? `${(coop.latency_ms / 1000).toFixed(2)}s` : ""}</span></div>
          <div className="rc-cbody">
            {loading && <div className="rc-typing"><i /><i /><i /><span>picking from {r?.shortlist.length ?? 5}…</span></div>}
            {coop && (<>
              <div className="rc-act">{coop.tool}() {full && coop.tool === full.tool && <span style={{ color: "var(--rc-green-ink)", fontSize: 12 }}>· same answer ✓</span>}</div>
              <div className="rc-meta">{coop.n_tools} tools in prompt · <b style={{ color: "var(--turq)" }}>{coop.tokens} tokens</b> · ${coop.cost_usd.toFixed(5)} · {coop.latency_ms.toFixed(0)}ms</div>
              <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--rc-faint)", lineHeight: 1.5, borderTop: "1px dashed var(--rc-line)", paddingTop: 10 }}>
                Same LLM, same answer — but {tokFactor ?? "many"}× fewer tokens and grounded in Aito&apos;s calibrated shortlist. {top != null && top >= 0.9 ? "Here Aito's top confidence clears the gate, so you could skip this call entirely." : ""}
              </div>
            </>)}
          </div>
        </div>
      </div>

      <div className="rc-foot">All live: Aito `_predict` over learned tool history + two real gpt-5-mini calls. Augmentation, not competition — Aito shrinks the LLM&apos;s job; the LLM keeps the judgment.</div>
    </div>
  );
}
