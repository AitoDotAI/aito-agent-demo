"use client";

/* 360 Dashboard — Aito called DIRECTLY (no agent), the company analog of the
   Opportunity Assistant. Pick a customer segment and see every KPI with the lever
   that moves it + the projected lift, plus a spotlight at-risk customer joined
   across every domain. Same ops as the Company agent, just without the LLM. */

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { WhyTip } from "@/components/prediction/WhyTip";

type Cause = { field: string; value: string; lift: number; mode: "rate" | "share"; p_with: number; p_without: number };
type Lever = { value: string; p: number; lift: number };
type KpiWhy = { base: number | null; factors: { field: string; value: string; lift: number }[] };
type Kpi = {
  key: string; kpi: string; headline: { metric: string; now: number; then: number; lower_is_better: boolean };
  lift_pp: number; current: number; bad_label: string; good_label: string; kpi_why: KpiWhy;
  causes: Cause[];
  levers: { lever: string; items: Lever[] };
  recommended_play: { lever: string; change_to: string };
};

// the KPI rate's own $why: base × the segment attributes' lifts = the rate
function KpiWhyBody({ w, now }: { w: KpiWhy; now: number }) {
  if (w.base == null) return <div style={{ fontSize: 12, color: "#56524a" }}>This rate is the base — the segment&apos;s attributes don&apos;t move this KPI.</div>;
  return (
    <div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 9 }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#56524a" }}><span>base rate</span><b>{Math.round(w.base * 100)}%</b></div>
        {w.factors.map((f, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#56524a", gap: 8 }}>
            <span>{f.field.replace(/_/g, " ")} = {f.value}</span>
            <b style={{ fontFamily: "'JetBrains Mono',monospace", color: f.lift >= 1 ? "#c2410c" : "#1f6f4a" }}>×{f.lift}</b>
          </div>
        ))}
      </div>
      <div style={{ fontFamily: "'JetBrains Mono',monospace", fontSize: 11.5, color: "#56524a", borderTop: "1px solid #efeadd", paddingTop: 7 }}>
        {Math.round(w.base * 100)}%{w.factors.map((f, i) => <span key={i}> × {f.lift}</span>)} = <b style={{ color: "#16140f" }}>{Math.round(now * 100)}%</b>
      </div>
    </div>
  );
}

// ── per-row "?" explanation (two-bar comparison, like the other demos' $why) ──
function CmpBar({ label, p, color }: { label: string; p: number; color: string }) {
  const w = Math.round(p * 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11 }}>
      <span style={{ width: 104, color: "#928d80", flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 8, background: "#efeadd", borderRadius: 4, overflow: "hidden" }}>
        <span style={{ display: "block", height: "100%", width: `${w}%`, background: color, borderRadius: 4 }} />
      </div>
      <b style={{ width: 32, textAlign: "right", fontFamily: "'JetBrains Mono',monospace", fontSize: 11 }}>{w}%</b>
    </div>
  );
}
function CmpBody({ a, b, note }: { a: { label: string; p: number; color: string }; b: { label: string; p: number; color: string }; note: React.ReactNode }) {
  return (
    <div>
      <div style={{ display: "flex", flexDirection: "column", gap: 7, marginBottom: 9 }}><CmpBar {...a} /><CmpBar {...b} /></div>
      <div style={{ fontSize: 12, color: "#56524a", lineHeight: 1.5 }}>{note}</div>
    </div>
  );
}

function CauseRow({ c, bad, good }: { c: Cause; bad: string; good: string }) {
  const driver = c.lift >= 1;
  const name = `${c.field.replace(/_/g, " ")} = ${c.value}`;
  const aColor = driver ? "#c2410c" : "#1f6f4a";
  const body = c.mode === "rate"
    ? <CmpBody a={{ label: `with ${c.value}`, p: c.p_with, color: aColor }} b={{ label: "everyone else", p: c.p_without, color: "#cfcabf" }}
        note={<>In this segment, {bad} run <b>{Math.round(c.p_with * 100)}%</b> with this vs <b>{Math.round(c.p_without * 100)}%</b> otherwise → <b>×{c.lift}</b>.</>} />
    : <CmpBody a={{ label: `among ${bad}`, p: c.p_with, color: aColor }} b={{ label: `among ${good}`, p: c.p_without, color: "#cfcabf" }}
        note={<><b>×{c.lift}</b> {driver ? "over" : "under"}-represented among {bad}.</>} />;
  return (
    <div className="fr">
      <span className="fl">{name}</span>
      <span className={`fx ${driver ? "risk" : "prot"}`}>×{c.lift}</span>
      <WhyTip title={name} subtitle={`live _relate · ${driver ? "raises" : "lowers"} ${bad}`} body={body}
        footer={c.mode === "rate" ? "rate within the segment · Aito _relate $on" : "share of the outcome · Aito _relate"} />
    </div>
  );
}

function LeverRow({ l, lever, current, good, top }: { l: Lever; lever: string; current: number; good: string; top: boolean }) {
  return (
    <div className="fr">
      <span className="fl">{lever} → {l.value}</span>
      <span className={`fx ${top ? "best" : "good"}`}>×{l.lift}</span>
      <WhyTip title={`${lever} → ${l.value}`} subtitle={`live _recommend · toward ${good}`}
        body={<CmpBody a={{ label: `with ${l.value}`, p: l.p, color: "#16c2b9" }}
          b={{ label: "segment now", p: current, color: "#cfcabf" }}
          note={<>Predicted {good} <b>{Math.round(l.p * 100)}%</b> vs {Math.round(current * 100)}% baseline → <b>×{l.lift}</b>.{top ? " The top-ranked action." : ""}</>} />}
        footer="P(good) for this lever value vs the segment baseline · live Aito _recommend" />
    </div>
  );
}
type Customer = {
  profile: Record<string, unknown>;
  domains: Record<string, { count: number; examples: Record<string, unknown>[] }>;
};
type Sheet = { segment: Record<string, string> | string; kpis: Kpi[]; customer: Customer | null };

const OPTS = {
  industry: ["Any", "SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"],
  size: ["Any", "SMB", "Mid-market", "Enterprise"],
  plan: ["Any", "Free", "Starter", "Pro", "Enterprise"],
};
type Seg = { industry: string; size: string; plan: string };
const SAMPLES: { label: string; s: Seg }[] = [
  { label: "SMB · Free", s: { industry: "Any", size: "SMB", plan: "Free" } },
  { label: "Enterprise · Pro", s: { industry: "Any", size: "Enterprise", plan: "Pro" } },
  { label: "Banking · Mid-market", s: { industry: "Banking", size: "Mid-market", plan: "Any" } },
  { label: "All customers", s: { industry: "Any", size: "Any", plan: "Any" } },
];

// per-KPI display: nice label + what the % counts
const META: Record<string, { label: string; sub: string }> = {
  conversion: { label: "Conversion", sub: "trials → paid" },
  churn: { label: "Churn", sub: "accounts lost" },
  nps: { label: "NPS detractors", sub: "share detracting" },
  csat: { label: "CSAT", sub: "good ratings" },
  adoption: { label: "Adoption", sub: "active usage" },
  ontime: { label: "Overdue", sub: "invoices late" },
};
const pct = (v: number) => `${Math.round(v * 100)}%`;
const eur = (n: unknown) => "€" + Number(n ?? 0).toLocaleString("en-US");
const toQS = (s: Seg) => Object.entries(s).filter(([, v]) => v && v !== "Any").map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");

export function CompanyDashboardView() {
  const [seg, setSeg] = useState<Seg>(SAMPLES[0].s);
  const [active, setActive] = useState(0);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [loading, setLoading] = useState(false);

  const build = useCallback((s: Seg) => {
    setLoading(true);
    apiFetch<Sheet>(`/api/company-360?${toQS(s)}`).then(setSheet).catch(() => {}).finally(() => setLoading(false));
  }, []);
  useEffect(() => { build(SAMPLES[0].s); }, [build]);

  const set = (k: keyof Seg, v: string) => { const ns = { ...seg, [k]: v }; setSeg(ns); setActive(-1); };
  const pick = (i: number) => { setActive(i); setSeg(SAMPLES[i].s); build(SAMPLES[i].s); };

  const c = sheet?.customer;
  const prof = (c?.profile ?? {}) as Record<string, string | number>;

  return (
    <div className="cd">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />
      <div className="wrap">
        <div className="kick">Northwind Cloud · 360 Dashboard</div>
        <div className="chips">{SAMPLES.map((s, i) => <button key={i} className={`chip ${active === i ? "on" : ""}`} onClick={() => pick(i)}>{s.label}</button>)}</div>
        <div className="cfg">
          {(Object.keys(OPTS) as (keyof typeof OPTS)[]).map((k) => (
            <label key={k}><span>{k}</span>
              <select value={seg[k]} onChange={(e) => set(k, e.target.value)}>{OPTS[k].map((o) => <option key={o}>{o}</option>)}</select>
            </label>
          ))}
          <button className="run" disabled={loading} onClick={() => build(seg)}>{loading ? "Reading the company's data…" : "▶ Refresh 360"}</button>
        </div>

        {sheet && (
          <>
            <div className="sec">KPIs &amp; the lever that moves each <span className="op">_predict · _recommend</span></div>
            <div className="kgrid">
              {sheet.kpis.map((k) => {
                const m = META[k.key] ?? { label: k.headline.metric, sub: "" };
                const lower = k.headline.lower_is_better;
                const good = lower ? k.headline.now <= 0.33 : k.headline.now >= 0.5;
                return (
                  <div className="kc" key={k.key}>
                    <div className="kh"><b>{m.label}</b><span>{m.sub}</span></div>
                    <div className="kvrow">
                      <div className="kv" style={{ color: good ? "var(--g)" : "var(--r)" }}>{pct(k.headline.now)}</div>
                      <WhyTip title={`Why ${m.label} is ${pct(k.headline.now)}`} subtitle="live _predict · $why"
                        body={<KpiWhyBody w={k.kpi_why} now={k.headline.now} />}
                        footer="The base rate scaled by each segment attribute's lift · Aito _predict $why" />
                    </div>
                    <div className="kbar"><i style={{ width: pct(k.headline.now), background: good ? "var(--g)" : "var(--r)" }} /></div>

                    <div className="flist">
                      <div className="ft">Root causes <span className="op2">_relate</span></div>
                      {k.causes.length
                        ? k.causes.map((c, i) => <CauseRow key={i} c={c} bad={k.bad_label} good={k.good_label} />)
                        : <div className="fnone">no strong driver beyond the segment</div>}
                    </div>

                    <div className="flist">
                      <div className="ft">Recommended levers <span className="op2">_recommend</span></div>
                      {k.levers.items.map((l, i) => <LeverRow key={i} l={l} lever={k.levers.lever} current={k.current} good={k.good_label} top={i === 0} />)}
                    </div>

                    <div className="proj">↳ pull the top lever → <b style={{ color: "var(--t)" }}>{pct(k.headline.then)}</b> · {k.lift_pp}pp better</div>
                  </div>
                );
              })}
            </div>

            {c && (
              <>
                <div className="sec">Spotlight: an at-risk customer, 360 <span className="op">_query · linked</span></div>
                <div className="spot">
                  <div className="sp-head">
                    <div className="sp-name">{String(prof.name)} <span className="sp-id">{String(prof.customer_id)}</span></div>
                    <div className="sp-tags">
                      <span className="tag">{String(prof.industry)}</span>
                      <span className="tag">{String(prof.size)}</span>
                      <span className="tag">{String(prof.plan)}</span>
                      <span className={`tag h-${String(prof.health).toLowerCase()}`}>{String(prof.health)}</span>
                      <span className="tag mrr">{eur(prof.mrr_eur)}/mo</span>
                      {prof.churned === "yes" && <span className="tag churn">churned</span>}
                    </div>
                  </div>
                  <div className="sp-domains">
                    {Object.entries(c.domains).map(([d, v]) => (
                      <div className="dom" key={d}><div className="dn">{v.count}</div><div className="dl">{d}</div></div>
                    ))}
                  </div>
                  <div className="sp-foot">One customer, every domain — joined live by the Aito link. The same numbers the Company AI agent reasons over.</div>
                </div>
              </>
            )}
          </>
        )}
        <div className="foot">Every figure is a live Aito query over Northwind&apos;s linked data — KPIs &amp; levers (`_predict` + `_recommend`), the customer join (`_query`). This is the data view; the <b>Company AI agent</b> drives the same ops in a chat.</div>
      </div>
    </div>
  );
}

export default CompanyDashboardView;

const CSS = `
.cd{--card:#fff;--line:#e6e2d8;--ink:#16140f;--ink2:#56524a;--faint:#928d80;--t:#16c2b9;--g:#1f6f4a;--r:#c2410c;--gold-ink:#6f561c;--gold-soft:#f6efd9;
  font-family:'Figtree',ui-sans-serif,system-ui,sans-serif;background:#f4f2ec;color:var(--ink);min-height:100%;height:100%;overflow-y:auto;font-size:14px}
.cd .wrap{max-width:1060px;margin:0 auto;padding:18px 24px 60px}
.cd .op{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:var(--faint);background:#eee9dd;padding:2px 7px;border-radius:5px;margin-left:auto}
.cd .kick{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;margin:8px 0 12px}
.cd .chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.cd .chip{font-family:'JetBrains Mono',monospace;font-size:11.5px;padding:6px 11px;border-radius:7px;border:1px solid var(--line);background:#fff;color:var(--ink2);cursor:pointer}
.cd .chip.on{background:var(--gold-soft);border-color:#e3c878;color:var(--gold-ink)}
.cd .cfg{display:grid;grid-template-columns:repeat(3,1fr) auto;gap:10px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
@media(max-width:720px){.cd .cfg{grid-template-columns:1fr 1fr}.cd .cfg .run{grid-column:1/-1;white-space:normal}}
.cd .cfg label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--faint);text-transform:capitalize}
.cd .cfg select{font-size:12.5px;padding:7px 8px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink)}
.cd .run{font-weight:800;font-size:13px;background:var(--t);color:#04221f;border:none;border-radius:8px;padding:9px 16px;cursor:pointer;white-space:nowrap}
.cd .run:disabled{opacity:.6;cursor:wait}
.cd .sec{display:flex;align-items:center;gap:8px;font-weight:800;font-size:14.5px;margin:22px 0 11px}
.cd .kgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:13px}
@media(max-width:820px){.cd .kgrid{grid-template-columns:1fr 1fr}}
@media(max-width:520px){.cd .kgrid{grid-template-columns:1fr}}
.cd .kc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 15px}
.cd .kh{display:flex;align-items:baseline;justify-content:space-between;gap:6px}
.cd .kh b{font-size:14px;font-weight:700}.cd .kh span{font-size:10.5px;color:var(--faint)}
.cd .kvrow{display:flex;align-items:center;margin:4px 0 6px}
.cd .kv{font-size:34px;font-weight:900;letter-spacing:-.03em;line-height:1.1}
.cd .kbar{height:7px;background:#eee9dd;border-radius:4px;overflow:hidden;margin-bottom:10px}.cd .kbar i{display:block;height:100%;border-radius:4px}
.cd .flist{border-top:1px dashed var(--line);padding-top:8px;margin-top:9px}
.cd .ft{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.cd .op2{font-family:'JetBrains Mono',monospace;font-size:8.5px;color:var(--t);background:#e9f6f5;padding:1px 5px;border-radius:4px;text-transform:none;letter-spacing:0}
.cd .fr{display:flex;align-items:center;gap:7px;padding:2px 0}
.cd .fr .fl{flex:1;min-width:0;font-size:11.5px;color:var(--ink2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cd .fr .fx{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;padding:1px 6px;border-radius:5px}
.cd .fr .fx.risk{color:var(--r);background:#fbe4d8}
.cd .fr .fx.prot{color:var(--g);background:#e3f4ea}
.cd .fr .fx.best{color:#04221f;background:#d6f3f0}
.cd .fr .fx.good{color:var(--t);background:#e9f6f5}
.cd .fnone{font-size:11px;color:var(--faint);font-style:italic;padding:2px 0}
.cd .proj{border-top:1px dashed var(--line);margin-top:9px;padding-top:8px;font-size:11.5px;color:var(--ink2)}
.cd .spot{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 17px;border-left:3px solid var(--r)}
.cd .sp-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}
.cd .sp-name{font-size:16px;font-weight:800}.cd .sp-id{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--faint);font-weight:400;margin-left:6px}
.cd .sp-tags{display:flex;gap:6px;flex-wrap:wrap}
.cd .tag{font-family:'JetBrains Mono',monospace;font-size:10.5px;padding:3px 8px;border-radius:6px;background:#f1eee8;color:var(--ink2)}
.cd .tag.h-red{background:#fbe4d8;color:var(--r)}.cd .tag.h-yellow{background:#fbf1d8;color:var(--gold-ink)}.cd .tag.h-green{background:#e3f4ea;color:var(--g)}
.cd .tag.mrr{background:#e9f6f5;color:#04221f}.cd .tag.churn{background:#fbe4d8;color:var(--r);font-weight:700}
.cd .sp-domains{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-top:14px}
@media(max-width:620px){.cd .sp-domains{grid-template-columns:repeat(3,1fr)}}
.cd .dom{background:#faf9f6;border:1px solid var(--line);border-radius:9px;padding:10px;text-align:center}
.cd .dom .dn{font-size:22px;font-weight:900;letter-spacing:-.02em}.cd .dom .dl{font-size:11px;color:var(--faint);text-transform:capitalize;margin-top:2px}
.cd .sp-foot{font-size:11.5px;color:var(--faint);margin-top:12px;line-height:1.5}
.cd .foot{margin-top:22px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--faint);line-height:1.7}
.cd .foot b{color:var(--ink2)}
`;
