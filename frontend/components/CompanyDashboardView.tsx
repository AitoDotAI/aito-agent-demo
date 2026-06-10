"use client";

/* 360 Dashboard — Aito called DIRECTLY (no agent), the company analog of the
   Opportunity Assistant. Pick a customer segment and see every KPI with the lever
   that moves it + the projected lift, plus a spotlight at-risk customer joined
   across every domain. Same ops as the Company agent, just without the LLM. */

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Driver = { field: string; value: string; lift: number };
type Kpi = {
  key: string; kpi: string; headline: { metric: string; now: number; then: number; lower_is_better: boolean };
  lift_pp: number; drivers: Driver[];
  recommended_play: { lever: string; change_to: string };
};
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
                    <div className="kv" style={{ color: good ? "var(--g)" : "var(--r)" }}>{pct(k.headline.now)}</div>
                    <div className="kbar"><i style={{ width: pct(k.headline.now), background: good ? "var(--g)" : "var(--r)" }} /></div>
                    <div className="lev">
                      <div className="ll">↳ {k.recommended_play.lever} → <b>{k.recommended_play.change_to}</b></div>
                      <div className="lp">{pct(k.headline.now)} → <b style={{ color: "var(--t)" }}>{pct(k.headline.then)}</b> · {k.lift_pp}pp better</div>
                    </div>
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
@media(max-width:720px){.cd .cfg{grid-template-columns:1fr 1fr}}
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
.cd .kv{font-size:34px;font-weight:900;letter-spacing:-.03em;line-height:1.1;margin:4px 0 6px}
.cd .kbar{height:7px;background:#eee9dd;border-radius:4px;overflow:hidden;margin-bottom:11px}.cd .kbar i{display:block;height:100%;border-radius:4px}
.cd .lev{border-top:1px dashed var(--line);padding-top:9px}
.cd .ll{font-size:12px;color:var(--ink2)}.cd .ll b{color:var(--ink)}
.cd .lp{font-size:12px;color:var(--faint);margin-top:3px}
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
