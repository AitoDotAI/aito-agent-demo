"use client";

/* Unified three-pane shell for the whole demo.

   One left nav lists every surface (Overview · the telco support views ·
   the sales assistant); the centre swaps the active view; the right Aito
   panel adapts its copy to whatever view is showing. Each route renders
   <AppShell initialView="…"> so deep links (and ?view=) still land on the
   right tab, but navigation between tabs is in-place client state — the nav
   and panel never unmount. */

import { useCallback, useEffect, useRef, useState } from "react";
import PredictionBadge from "@/components/prediction/PredictionBadge";
import ConfidenceBar from "@/components/prediction/ConfidenceBar";
import WhyCards from "@/components/prediction/WhyCards";
import { AugmentView } from "@/components/AugmentView";
import { HandoffView, type HandoffData } from "@/components/HandoffView";
import { OverviewView } from "@/components/OverviewView";
import { SalesView, type SalesMeta } from "@/components/SalesView";
import { SalesAgentView } from "@/components/SalesAgentView";
import { CompanyAgentView } from "@/components/CompanyAgentView";
import { ToolboxView, type ToolMeta } from "@/components/ToolboxView";
import { apiFetch, ApiError } from "@/lib/api";
import type { Alternative, WhyFactor } from "@/lib/types";

export type View = "home" | "resolve" | "augment" | "handoff" | "sales" | "agent" | "toolbox" | "company" | "company-toolbox";

type Aito = {
  intent: string; intent_p: number; intent_alts: Alternative[]; why: WhyFactor[];
  param_field: string | null; param: string | null; param_p: number | null; param_alts: Alternative[];
  aito_ms: number;
};
type Llm = {
  intent: string; param_field: string | null; param: string | null;
  model: string; latency_ms: number; tokens: number; cost_usd: number;
};

const SAMPLES: { label: string; text: string; sender: string }[] = [
  { label: "Outage · Helsinki", text: "Is there a network outage? Nothing works in Helsinki.", sender: "alerts.monitoring.io" },
  { label: "Repair · cracked screen", text: "My screen is cracked, the glass is shattered. Help?", sender: "tickets.helpdesk.io" },
  { label: "Cancel · broadband", text: "Please cancel my home internet, I'm moving abroad.", sender: "globex.com" },
  { label: "Refund · roaming", text: "Hi — please refund the €45 charge on my roaming pack.", sender: "acme.com" },
  { label: "Balance", text: "What's my current account balance?", sender: "stark.com" },
];
const ACTION: Record<string, (p: string | null) => string> = {
  cancel_service: (p) => `Cancel the ${p ?? "service"}`,
  refund: (p) => `Refund the ${p ?? "disputed"} charge`,
  check_outage: (p) => `Return outage status for ${p ?? "the area"}`,
  find_shop: (p) => `Find the nearest shop in ${p ?? "the city"}`,
  repair_help: (p) => `Send the ${p ?? "repair"} guide`,
  check_balance: () => `Return the account balance`,
};
const SENSITIVE = new Set(["refund", "cancel_service"]);
const actionText = (intent: string, param: string | null) =>
  (ACTION[intent] ?? ((p: string | null) => `${intent}${p ? " · " + p : ""}`))(param);

const isView = (v: string | null): v is View =>
  v === "home" || v === "resolve" || v === "augment" || v === "handoff" || v === "sales" || v === "agent" ||
  v === "toolbox" || v === "company" || v === "company-toolbox";

const SALES_EXAMPLES: Record<string, string> = {
  win_odds: "_predict outcome  →  $p(won) + $why drivers",
  estimate_effort: "_estimate effort_days  →  person-days",
  find_references: "_query  where outcome=won  →  3 briefs",
  recommend_outreach: "_recommend channel/angle toward meeting=yes",
  propose_send_email: "queues a draft for human approval — never sends",
};
const CO_EXAMPLES: Record<string, string> = {
  churn_risk: "_predict churned  →  $p + $why drivers",
  nps_drivers: "_predict score_band  →  detractor $p + drivers",
  estimate_mrr: "_estimate mrr_eur  →  expected € / month",
  find_accounts: "_query accounts  →  example rows",
  recommend_focus: "_recommend theme toward score_band=promoter",
  open_cs_task: "drafts a CS task for approval — never acts",
};

export default function AppShell({ initialView = "home" }: { initialView?: View }) {
  const [view, setView] = useState<View>(initialView);

  // resolve (telco) state
  const [text, setText] = useState(SAMPLES[0].text);
  const [sender, setSender] = useState(SAMPLES[0].sender);
  const [aito, setAito] = useState<Aito | null>(null);
  const [llm, setLlm] = useState<Llm | null>(null);
  const [llmErr, setLlmErr] = useState<string | null>(null);
  const [aitoLoading, setAitoLoading] = useState(false);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmElapsed, setLlmElapsed] = useState(0);
  const [showWhy, setShowWhy] = useState(true);
  const [active, setActive] = useState(0);
  const [augMs, setAugMs] = useState<number | null>(null);
  const [handoff, setHandoff] = useState<HandoffData | null>(null);
  const [handoffLoading, setHandoffLoading] = useState(true);
  const [sales, setSales] = useState<SalesMeta>({ loading: true, meeting_p: null, win_p: null });
  // sales-agent toolbox (shared between the Toolbox view and the chat): which
  // tools the agent may call. Default every tool on.
  const [tools, setTools] = useState<ToolMeta[]>([]);
  const [toolOn, setToolOn] = useState<Record<string, boolean>>({});
  const [coTools, setCoTools] = useState<ToolMeta[]>([]);
  const [coToolOn, setCoToolOn] = useState<Record<string, boolean>>({});
  const timer = useRef<number | null>(null);

  // handoff queue: fetched once for the sidebar badge + the view
  useEffect(() => {
    apiFetch<HandoffData>("/api/handoff").then(setHandoff).catch(() => {}).finally(() => setHandoffLoading(false));
  }, []);

  // toolbox catalogs, fetched once each; everything enabled to start
  useEffect(() => {
    apiFetch<{ tools: ToolMeta[] }>("/api/sales-agent/tools")
      .then((r) => { setTools(r.tools); setToolOn(Object.fromEntries(r.tools.map((t) => [t.name, true]))); })
      .catch(() => {});
    apiFetch<{ tools: ToolMeta[] }>("/api/company-agent/tools")
      .then((r) => { setCoTools(r.tools); setCoToolOn(Object.fromEntries(r.tools.map((t) => [t.name, true]))); })
      .catch(() => {});
  }, []);

  const toggleTool = (name: string) => setToolOn((s) => ({ ...s, [name]: !(s[name] ?? true) }));
  const setAllAito = (on: boolean) =>
    setToolOn((s) => { const n = { ...s }; tools.forEach((t) => { if (t.aito) n[t.name] = on; }); return n; });
  const toggleCoTool = (name: string) => setCoToolOn((s) => ({ ...s, [name]: !(s[name] ?? true) }));
  const setAllCoAito = (on: boolean) =>
    setCoToolOn((s) => { const n = { ...s }; coTools.forEach((t) => { if (t.aito) n[t.name] = on; }); return n; });

  const resolve = useCallback((t: string, s: string) => {
    setAito(null); setLlm(null); setLlmErr(null);
    setAitoLoading(true); setLlmLoading(true); setLlmElapsed(0);
    const t0 = performance.now();
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => setLlmElapsed(performance.now() - t0), 80);

    const qs = `text=${encodeURIComponent(t)}${s ? `&sender=${encodeURIComponent(s)}` : ""}`;
    apiFetch<Aito>(`/api/resolve?${qs}`)
      .then(setAito).catch(() => {}).finally(() => setAitoLoading(false));
    apiFetch<Llm>(`/api/resolve-llm?${qs}`)
      .then(setLlm)
      .catch((e: ApiError) => setLlmErr(e?.detail || "LLM agent unavailable"))
      .finally(() => { setLlmLoading(false); if (timer.current) window.clearInterval(timer.current); });
  }, []);

  // read deep-link params once (?view=, ?sample=, ?text=, ?sender=)
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const v = p.get("view");
    if (isView(v)) setView(v);
    const i = p.get("sample");
    const idx = i != null ? Math.max(0, Math.min(SAMPLES.length - 1, parseInt(i, 10) || 0)) : 0;
    const t = p.get("text") ?? SAMPLES[idx].text;
    const s = p.get("sender") ?? SAMPLES[idx].sender;
    setActive(p.get("text") ? -1 : idx); setText(t); setSender(s);
  }, []);

  // resolve runs a live gpt-5-mini call, so only fire it when the resolve view
  // is actually shown (and hasn't run yet) — not on landing at home/sales.
  useEffect(() => {
    if (view === "resolve" && !aito && !aitoLoading && !llmLoading) resolve(text, sender);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  const pick = (i: number) => { setActive(i); setText(SAMPLES[i].text); setSender(SAMPLES[i].sender); resolve(SAMPLES[i].text, SAMPLES[i].sender); };

  const aitoMs = aito?.aito_ms ?? null;
  const llmMs = llm?.latency_ms ?? null;
  const speedup = aitoMs && llmMs ? Math.max(1, Math.round(llmMs / aitoMs)) : null;

  const NavItem = ({ v, children }: { v: View; children: React.ReactNode }) => (
    <div className={`rc-item ${view === v ? "on" : ""}`} onClick={() => setView(v)}>{children}</div>
  );

  const telco = view === "resolve" || view === "augment" || view === "handoff";
  const hasTopbar = telco || view === "sales";
  const crumb = view === "sales"
    ? { grp: "Northlight · sales", page: "Opportunity Assistant", note: "live · _estimate · _recommend · _query" }
    : view === "handoff" ? { grp: "Escalate", page: "Human handoff", note: "live · calibrated triage" }
    : view === "augment" ? { grp: "Resolve", page: "Tool routing · short-list", note: "live · Aito augments the LLM" }
    : { grp: "Resolve", page: "Ticket resolution", note: "live · gpt-5-mini vs aito._predict" };

  return (
    <div className="rc-app">
      {/* ---------- sidebar: every demo, one menu ---------- */}
      <aside className="rc-side">
        <div className="rc-brand">
          <div className="ic"><svg viewBox="0 0 24 24" fill="none"><path d="M12 3C12 3 5 9 5 15a7 7 0 0 0 14 0c0-6-7-12-7-12Z" stroke="#3a2c08" strokeWidth="1.8" /><path d="M12 21v-9m0 2-3-2m3 4 3-2" stroke="#3a2c08" strokeWidth="1.8" strokeLinecap="round" /></svg></div>
          <div><div className="bt">Predictive<br />Agent</div><div className="bp">Powered by Aito.ai</div></div>
        </div>
        <nav className="rc-nav">
          <div className="rc-grp">Start here</div>
          <NavItem v="home">Overview</NavItem>

          <div className="rc-grp">Northlight · sales</div>
          <NavItem v="agent">Sales agent</NavItem>
          <NavItem v="sales">Opportunity Assistant</NavItem>
          <NavItem v="toolbox">Toolbox</NavItem>

          <div className="rc-grp">Northwind Cloud · company</div>
          <NavItem v="company">Company AI agent</NavItem>
          <NavItem v="company-toolbox">Toolbox</NavItem>

          <div className="rc-grp">Sonipra Telecom · support</div>
          <NavItem v="resolve">Ticket resolution</NavItem>
          <NavItem v="augment">Tool routing · short-list</NavItem>
          <div className={`rc-item ${view === "handoff" ? "on" : ""}`} onClick={() => setView("handoff")}>
            Human handoff{handoff && handoff.counts.handoff > 0 && <span className="bdg r">{handoff.counts.handoff}</span>}
          </div>
        </nav>
        <div style={{ marginTop: "auto", padding: "16px 18px", fontFamily: "'JetBrains Mono',monospace", fontSize: 10, color: "var(--side-label)", lineHeight: 1.6, borderTop: "1px solid var(--side-line)" }}>
          analyze · assist · automate<br />every view is live Aito + gpt-5-mini
        </div>
      </aside>

      {/* ---------- main ---------- */}
      <main className="rc-main">
        {view === "home" && <OverviewView onNavigate={(v) => setView(v)} />}
        {view === "agent" && <SalesAgentView tools={tools} toolOn={toolOn} />}
        {view === "toolbox" && <ToolboxView tools={tools} toolOn={toolOn} onToggle={toggleTool} onAllAito={setAllAito}
          agentLabel="Sales agent" examples={SALES_EXAMPLES}
          lead={<>The sales agent is a plain gpt-5-mini chat loop — what makes it useful is what&apos;s in its toolbox. Four of these tools are <b>Aito ops</b> over Northlight&apos;s own history; the model calls them when it needs a number it can&apos;t invent. Flip them off and ask the same question: it has to <b>guess</b>, and it&apos;ll tell you so.</>} />}
        {view === "company" && <CompanyAgentView tools={coTools} toolOn={coToolOn} />}
        {view === "company-toolbox" && <ToolboxView tools={coTools} toolOn={coToolOn} onToggle={toggleCoTool} onAllAito={setAllCoAito}
          agentLabel="Company AI agent" examples={CO_EXAMPLES}
          lead={<>The Company AI agent is a plain gpt-5-mini chat loop over Northwind&apos;s <b>accounts</b> and <b>feedback</b>. Five of these tools are <b>Aito ops</b>; the model calls them for the numbers a BI bot can&apos;t produce — churn, NPS drivers, MRR, themes to fix. Flip them off and it has to <b>guess</b>, and it&apos;ll tell you so.</>} />}

        {hasTopbar && (
          <div className="rc-topbar">
            <div className="rc-crumb">{crumb.grp} <span className="sep">›</span><b>{crumb.page}</b><span className="cnt">{crumb.note}</span></div>
            <div className="rc-tbtns">
              <div className="rc-pill"><span className="d" />Live</div>
              {telco && <div className="rc-pill mono">aito {(view === "augment" ? augMs : aitoMs) != null ? `${(view === "augment" ? augMs! : aitoMs!).toFixed(0)}ms` : "—"}</div>}
              {view === "sales" && <div className="rc-pill mono">{sales.loading ? "reading…" : sales.meeting_p != null ? `meeting ${Math.round(sales.meeting_p * 100)}%` : "—"}</div>}
              {view === "resolve" && (
                <>
                  <select className="rc-sel" value={active} onChange={(e) => pick(Number(e.target.value))}>
                    {SAMPLES.map((s, i) => <option key={s.label} value={i}>{s.label}</option>)}
                  </select>
                  <button className="rc-run" disabled={aitoLoading || llmLoading} onClick={() => resolve(text, sender)}>
                    {aitoLoading || llmLoading ? "Resolving…" : "▶ Resolve"}
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {view === "augment" && <AugmentView onAito={setAugMs} />}
        {view === "handoff" && <HandoffView data={handoff} loading={handoffLoading} />}
        {view === "sales" && <SalesView onMeta={setSales} />}

        {view === "resolve" && (
        <div className="rc-body">
          {/* KPIs */}
          <div className="rc-kpis">
            <div className="rc-kpi"><div className="kl">Aito · predict-first</div><div className="kv t">{aitoMs != null ? `${aitoMs.toFixed(0)}ms` : "—"}</div><div className="ks">two _predict calls · $0 LLM</div></div>
            <div className="rc-kpi"><div className="kl">LLM agent · live</div><div className="kv p">{llmLoading ? `${(llmElapsed / 1000).toFixed(1)}s` : llmMs != null ? `${(llmMs / 1000).toFixed(1)}s` : llmErr ? "n/a" : "—"}</div><div className="ks">{llm ? `${llm.tokens} tokens` : "gpt-5-mini, one call"}</div></div>
            <div className="rc-kpi"><div className="kl">Speed-up</div><div className="kv t">{speedup ? `${speedup}×` : "—"}</div><div className="ks">Aito vs one agent call</div></div>
            <div className="rc-kpi"><div className="kl">LLM cost / resolution</div><div className="kv">{llm ? `$${llm.cost_usd.toFixed(5)}` : "—"}</div><div className="ks"><span style={{ color: "var(--turq)", fontWeight: 700 }}>Aito $0</span> · per ticket</div></div>
          </div>

          <div className="rc-h">Same ticket, two engines</div>
          <div className="rc-sub">The <b>LLM agent</b> reasons the resolution out on every ticket — seconds and tokens. <code>aito._predict</code> reads the <b>intent</b> and the one parameter it needs straight from history — two calls, sub-second, $0, with a calibrated <b>why</b>. Watch the response rates live.</div>

          {/* intake */}
          <div className="rc-ctl">
            {SAMPLES.map((s, i) => <button key={s.label} className={`rc-chip ${active === i ? "on" : ""}`} onClick={() => pick(i)}>{s.label}</button>)}
          </div>
          <div className="rc-ticket">
            <textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} />
            <input className="from" value={sender} onChange={(e) => setSender(e.target.value)} style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11.5, padding: "8px 10px", border: "1px solid var(--rc-line)", borderRadius: 8 }} />
          </div>

          {/* race */}
          <div className="rc-cols">
            {/* LLM */}
            <div className="rc-col llm">
              <div className="rc-colh"><span className="tag">live llm</span><span className="ct">LLM Agent</span>
                <span className="ms">{llmLoading ? `${(llmElapsed / 1000).toFixed(1)}s` : llmMs != null ? `${(llmMs / 1000).toFixed(2)}s` : ""}</span></div>
              <div className="rc-cbody">
                {llmLoading && <div className="rc-typing"><i /><i /><i /><span>gpt-5-mini reasoning…</span></div>}
                {!llmLoading && llmErr && <div style={{ color: "var(--rc-rust)", fontSize: 13 }}>⚠ {llmErr}</div>}
                {!llmLoading && llm && (
                  <>
                    <div className="rc-act">{actionText(llm.intent, llm.param)}</div>
                    <div className="rc-row">
                      <span className="lbl">intent</span><span className="pred-badge">{llm.intent}</span>
                      {llm.param_field && (<><span className="lbl">{llm.param_field.replace(/_/g, " ")}</span><span className="pred-badge">{llm.param}</span></>)}
                    </div>
                    <div className="rc-meta">1 model call · {llm.tokens} tokens · ${llm.cost_usd.toFixed(5)} · {llm.model}</div>
                    <div style={{ marginTop: 12, fontSize: 11.5, color: "var(--rc-faint)", lineHeight: 1.5, borderTop: "1px dashed var(--rc-line)", paddingTop: 10 }}>
                      No calibrated confidence and no evidence to verify — the model just asserts. Aito returns a <b style={{ color: "var(--rc-ink2)" }}>$p</b> and the <b style={{ color: "var(--rc-ink2)" }}>why</b> →
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Aito */}
            <div className="rc-col aito">
              <div className="rc-colh"><span className="tag">+ predictive layer</span><span className="ct">Aito _predict</span>
                <span className="ms">{aito ? `${aito.aito_ms.toFixed(0)}ms` : aitoLoading ? "…" : ""}</span></div>
              <div className="rc-cbody">
                {aitoLoading && !aito && <div className="rc-typing"><span>predicting…</span></div>}
                {aito && (
                  <>
                    <div className="rc-act">{actionText(aito.intent, aito.param)}
                      {SENSITIVE.has(aito.intent) && <span className="rc-gate">🔒 verify + confirm before firing</span>}</div>
                    <div className="rc-row">
                      <span className="lbl">intent</span>
                      <span style={{ display: "flex", alignItems: "center", gap: 10 }}><PredictionBadge value={aito.intent} confidence={aito.intent_p} alternatives={aito.intent_alts} /><ConfidenceBar value={aito.intent_p} /></span>
                      {aito.param_field && (<>
                        <span className="lbl">{aito.param_field.replace(/_/g, " ")}</span>
                        <span style={{ display: "flex", alignItems: "center", gap: 10 }}><PredictionBadge value={aito.param ?? "—"} confidence={aito.param_p ?? 0} alternatives={aito.param_alts} />{aito.param_p != null && <ConfidenceBar value={aito.param_p} />}</span>
                      </>)}
                    </div>
                    {aito.why?.length > 0 && (
                      <div className="rc-whywrap">
                        <button className="rc-whytog" onClick={() => setShowWhy((v) => !v)}>{showWhy ? "▾" : "▸"} why — verifiable from history</button>
                        {showWhy && <WhyCards why={aito.why} confidence={aito.intent_p} />}
                      </div>
                    )}
                    <div className="rc-meta">0 model calls · $0 · calibrated $p</div>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="rc-foot">Aito predictions, latency and cost are live (real _predict + a real gpt-5-mini call). LLM latency varies with load; Aito serves confident tickets from history (a cache hit) and falls through to the LLM on a miss.</div>
        </div>
        )}
      </main>

      {/* ---------- right Aito panel (adapts per view) ---------- */}
      {view === "resolve" ? (
        <aside className="rc-panel">
          <div className="rc-ph"><div className="rc-aw">aito<span className="dots">..</span></div><div className="rc-pdb">The Predictive DB · _predict</div></div>
          <div className="rc-pstats">
            <div className="rc-pstat"><div className="pv">{aitoMs != null ? `${aitoMs.toFixed(0)}ms` : "—"}</div><div className="pl">aito latency</div></div>
            <div className="rc-pstat"><div className="pv">intent</div><div className="pl">predict field</div></div>
            <div className="rc-pstat"><div className="pv">{llmMs != null ? `${(llmMs / 1000).toFixed(1)}s` : "live"}</div><div className="pl">llm latency</div></div>
          </div>
          <div className="rc-pchip">_predict</div>
          <div className="rc-pdesc">Aito is a <b>predictive cache in front of the LLM</b>. Each ticket is resolved by reading the <b>intent</b> and the one parameter it needs from history — <b>two _predict calls, no chain</b>. A confident hit fires instantly and free; a miss falls through to the LLM, whose answer becomes the next cache entry.</div>
          <div className="rc-plabel">Live query</div>
          <div className="rc-code"><span className="m">POST</span> /api/v1/_predict{"\n"}{"{"}{"\n"}  <span className="k">&quot;from&quot;</span>: <span className="s">&quot;resolutions&quot;</span>,{"\n"}  <span className="k">&quot;where&quot;</span>: {"{"} <span className="k">&quot;text&quot;</span>: <span className="s">&quot;…ticket…&quot;</span>,{"\n"}            <span className="k">&quot;sender_domain&quot;</span>: <span className="s">&quot;…&quot;</span> {"}"},{"\n"}  <span className="k">&quot;predict&quot;</span>: <span className="s">&quot;intent&quot;</span>,{"\n"}  <span className="k">&quot;select&quot;</span>: [<span className="s">&quot;$p&quot;</span>, <span className="s">&quot;$why&quot;</span>]{"\n"}{"}"}{"\n"}<span className="c">// → {aito ? `${aito.intent} (p ≈ ${aito.intent_p.toFixed(2)})` : "intent + $why"}</span></div>
          <div className="rc-plabel">Verify yourself</div>
          <div className="rc-pdesc" style={{ paddingTop: 8 }}>Every routed call traces back to an Aito query — no model file, no retrain. A row added today is in the next prediction.</div>
          <PanelLinks />
        </aside>
      ) : (
        <aside className="rc-panel">
          <div className="rc-ph"><div className="rc-aw">aito<span className="dots">..</span></div><div className="rc-pdb">{PANEL[view].pdb}</div></div>
          <div className="rc-pstats">
            {PANEL[view].stats.map((st, i) => <div className="rc-pstat" key={i}><div className="pv">{st[0]}</div><div className="pl">{st[1]}</div></div>)}
          </div>
          <div className="rc-pchip">{PANEL[view].chip}</div>
          <div className="rc-pdesc" dangerouslySetInnerHTML={{ __html: PANEL[view].desc }} />
          <div className="rc-plabel">{PANEL[view].codeLabel}</div>
          <div className="rc-code">{PANEL[view].code}</div>
          <PanelLinks />
        </aside>
      )}
    </div>
  );
}

function PanelLinks() {
  return (
    <>
      <div className="rc-plabel">Learn more</div>
      <div className="rc-plinks">
        <a className="rc-plink" href="/api/schema" target="_blank" rel="noreferrer"><span className="ar">↗</span> View live schema (JSON)</a>
        <div className="rc-plink"><span className="ar">↗</span> Predict API reference</div>
        <div className="rc-plink"><span className="ar">{"{}"}</span> Source on GitHub</div>
      </div>
      <div className="rc-cta"><button>Start free trial →</button></div>
    </>
  );
}

const PANEL: Record<Exclude<View, "resolve">, {
  pdb: string; stats: [string, string][]; chip: string; desc: string; codeLabel: string; code: React.ReactNode;
}> = {
  home: {
    pdb: "The Predictive DB",
    stats: [["5", "core ops"], ["$p", "calibrated"], ["$why", "explained"]],
    chip: "one query · no training",
    desc: "Aito turns your rows into an <b>instant, calibrated answer</b> — the same act as a neural net, but live and over <b>your</b> data, with nothing to train. Every demo in the menu is a real call to one of five ops.",
    codeLabel: "The five ops",
    code: "_predict   class + $p + $why\n_match     relevant memory\n_relate    drivers / lift\n_estimate  a number\n_recommend best next action",
  },
  augment: {
    pdb: "_predict · short-list",
    stats: [["240→5", "tools"], ["~16×", "fewer tokens"], ["1", "LLM call"]],
    chip: "augment, not compete",
    desc: "The agent keeps reasoning — Aito just hands it a <b>shorter menu</b>. <code>_predict</code> narrows the full tool catalog to the handful that fit this ticket, so the LLM picks from 5, not 240: smaller prompt, same answer, lower cost.",
    codeLabel: "Live query",
    code: "POST /api/v1/_predict\n{\n  \"from\": \"tool_calls\",\n  \"where\": { \"ticket\": \"…\" },\n  \"predict\": \"tool\",\n  \"limit\": 5\n}\n// → 5-tool short-list",
  },
  handoff: {
    pdb: "_predict · $p gate",
    stats: [["$p", "calibrated"], ["auto", "≥ 0.85"], ["ask", "< 0.65"]],
    chip: "_predict + $p",
    desc: "Calibrated confidence is <b>governance</b>. A confident prediction auto-resolves; a borderline one is handed to a human with the tentative read attached; anything sensitive (refund, cancel) is gated regardless. The number decides who acts.",
    codeLabel: "Live query",
    code: "POST /api/v1/_predict\n{\n  \"from\": \"resolutions\",\n  \"where\": { \"text\": \"…\" },\n  \"predict\": \"intent\",\n  \"select\": [\"$p\"]\n}\n// $p ≥ .85 auto · else escalate",
  },
  sales: {
    pdb: "estimate · recommend · query",
    stats: [["_estimate", "effort"], ["_recommend", "way in"], ["_query", "refs"]],
    chip: "analyze · automate",
    desc: "The same index, asked four ways over the firm's own history: <b>win odds</b> (<code>_predict</code>+<code>$why</code>), <b>effort</b> (<code>_estimate</code>), <b>references</b> (<code>_query</code>) and the <b>best way in</b> (<code>_recommend</code>) — the numbers an LLM can't invent. This dashboard calls them <b>directly</b>; the Sales agent calls them as <b>tools</b>.",
    codeLabel: "Live query",
    code: "POST /api/v1/_estimate\n{\n  \"from\": \"engagements\",\n  \"where\": { \"service_line\": \"…\",\n            \"complexity\": \"…\" },\n  \"estimate\": \"effort_days\"\n}\n// → person-days, from history",
  },
  agent: {
    pdb: "Aito in the toolbox",
    stats: [["assist", "→ optimize"], ["+yield", "outcome"], ["live", "gpt-5-mini"]],
    chip: "it optimizes, not just informs",
    desc: "A plain gpt-5-mini chat loop that <b>calls Aito ops as tools</b>. It doesn't only answer — it <b>optimizes the outcome</b>: <code>_recommend</code> picks the approach that books the most meetings and quantifies the <b>lift</b> over the unoptimised baseline (live, from history). Better, faster, cheaper — and higher-yield.",
    codeLabel: "Optimize, not describe",
    code: "recommend_outreach({industry,role})\n// ⇒ aito._recommend → meeting=yes\n//   Warm intro · Case study\n//   59% vs 16% → 3.7× more meetings",
  },
  toolbox: {
    pdb: "the agent's tools",
    stats: [["_predict", "win"], ["_estimate", "effort"], ["_recommend", "reach"]],
    chip: "one toggle",
    desc: "Each tool the agent can call. Four are <b>Aito ops</b> over Northlight's history; one is a gated action that only drafts. Flip the Aito tools off to see the agent fall back to <b>flagged guesses</b> — the augment thesis, A/B in one switch.",
    codeLabel: "Tool → op",
    code: "win_odds          → _predict\nestimate_effort   → _estimate\nfind_references   → _query\nrecommend_outreach→ _recommend\npropose_send_email→ action (gated)",
  },
  company: {
    pdb: "talk to your numbers",
    stats: [["churn", "+ why"], ["NPS", "drivers"], ["MRR", "estimate"]],
    chip: "not a BI bot — it predicts",
    desc: "A SQL+LLM chatbot can <code>COUNT(*)</code>. This agent calls Aito to do what it can't: <b>which accounts churn and why</b> (<code>_predict</code>+<code>$why</code>), <b>what drags NPS</b>, <b>expected MRR</b> (<code>_estimate</code>), and the <b>themes to fix</b> (<code>_recommend</code>) — calibrated, no training. Toggle the tools in the Toolbox.",
    codeLabel: "A tool the model calls",
    code: "churn_risk({plan:\"Free\",\n  health:\"Red\", onboarding:\"None\"})\n// ⇒ aito._predict churned\n//   → 0.92 + $why drivers",
  },
  "company-toolbox": {
    pdb: "the analyst's tools",
    stats: [["_predict", "churn"], ["_estimate", "mrr"], ["_recommend", "fix"]],
    chip: "one toggle",
    desc: "The Company AI agent's tools over <b>accounts</b> + <b>feedback</b>. Five are Aito ops; one is a gated CS-task draft. Turn the Aito tools off and the same agent has to guess the numbers — and flags that it's guessing.",
    codeLabel: "Tool → op",
    code: "churn_risk      → _predict\nnps_drivers     → _predict + $why\nestimate_mrr    → _estimate\nfind_accounts   → _query\nrecommend_focus → _recommend\nopen_cs_task    → action (gated)",
  },
};
