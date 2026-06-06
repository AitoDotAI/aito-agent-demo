"use client";

/* The Northlight "Opportunity Assistant" as an embeddable view inside the
   AppShell. Self-contained state; renders inside .rc-main (the shell supplies
   the left nav + right Aito panel, so this drops its old standalone top bar). */

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Driver = { field: string; value: string; lift: number };
type Ref = { brief: string; effort_days: number; deal_size_band: string; region: string };
type Ranked = { v: string; p: number };
type Sheet = {
  profile: Record<string, string>;
  win: { p: number; drivers: Driver[] };
  effort_days: number;
  references: Ref[];
  outreach: { channels: Ranked[]; angles: Ranked[]; recommended: { channel: string; angle: string; personalization: string }; meeting_p: number; auto_send: boolean };
  business_case: { value_eur: number; day_rate: number; cost_eur: number; margin_eur: number; margin_pct: number };
};

const OPTS = {
  industry: ["SaaS", "Retail", "Banking", "Manufacturing", "Healthcare", "Public", "Telecom", "Logistics"],
  service_line: ["Advisory", "Analytics & ML", "Integration", "Data Platform", "Cloud Migration", "Custom Dev"],
  deal_size_band: ["S", "M", "L", "XL"],
  lead_source: ["Referral", "Partner", "Inbound", "Event", "Outbound"],
  relationship: ["New logo", "Existing client"],
  competitive: ["Sole-source", "Competitive"],
  target_role: ["CTO", "Head of Data", "COO", "CEO", "Procurement"],
  complexity: ["Low", "Medium", "High"],
  team_seniority: ["junior-heavy", "balanced", "senior-heavy"],
};
type Profile = Record<keyof typeof OPTS, string>;

const SAMPLES: { label: string; p: Profile }[] = [
  { label: "SaaS · Data Platform · warm", p: { industry: "SaaS", service_line: "Data Platform", deal_size_band: "L", lead_source: "Referral", relationship: "Existing client", competitive: "Sole-source", target_role: "Head of Data", complexity: "Medium", team_seniority: "balanced" } },
  { label: "Manufacturing · Cloud · big", p: { industry: "Manufacturing", service_line: "Cloud Migration", deal_size_band: "XL", lead_source: "Partner", relationship: "New logo", competitive: "Competitive", target_role: "CTO", complexity: "High", team_seniority: "balanced" } },
  { label: "Retail · Analytics · inbound", p: { industry: "Retail", service_line: "Analytics & ML", deal_size_band: "M", lead_source: "Inbound", relationship: "New logo", competitive: "Competitive", target_role: "Head of Data", complexity: "Medium", team_seniority: "balanced" } },
  { label: "Public · Custom Dev · cold", p: { industry: "Public", service_line: "Custom Dev", deal_size_band: "M", lead_source: "Outbound", relationship: "New logo", competitive: "Competitive", target_role: "Procurement", complexity: "High", team_seniority: "junior-heavy" } },
];

const eur = (n: number) => "€" + (n >= 1000 ? `${Math.round(n / 1000)}k` : `${n}`);
const winLabel = (p: number) => (p >= 0.7 ? ["Strong", "var(--g)"] : p >= 0.45 ? ["Moderate", "var(--gold-ink)"] : ["Long shot", "var(--r)"]);

export type SalesMeta = { loading: boolean; meeting_p: number | null; win_p: number | null };

export function SalesView({ onMeta }: { onMeta?: (m: SalesMeta) => void }) {
  const [profile, setProfile] = useState<Profile>(SAMPLES[0].p);
  const [active, setActive] = useState(0);
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [loading, setLoading] = useState(false);

  const build = useCallback((p: Profile) => {
    setLoading(true);
    onMeta?.({ loading: true, meeting_p: null, win_p: null });
    const qs = new URLSearchParams(p).toString();
    apiFetch<Sheet>(`/api/opportunity?${qs}`)
      .then((s) => { setSheet(s); onMeta?.({ loading: false, meeting_p: s.outreach.meeting_p, win_p: s.win.p }); })
      .catch(() => onMeta?.({ loading: false, meeting_p: null, win_p: null }))
      .finally(() => setLoading(false));
  }, [onMeta]);
  useEffect(() => { build(SAMPLES[0].p); }, [build]);

  const set = (k: keyof Profile, v: string) => { const np = { ...profile, [k]: v }; setProfile(np); setActive(-1); };
  const pick = (i: number) => { setActive(i); setProfile(SAMPLES[i].p); build(SAMPLES[i].p); };

  const w = sheet?.win;
  const wl = w ? winLabel(w.p) : ["", ""];

  return (
    <div className="sa">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />
      <div className="wrap">
        <div className="kick">New opportunity</div>
        <div className="chips">{SAMPLES.map((s, i) => <button key={i} className={`chip ${active === i ? "on" : ""}`} onClick={() => pick(i)}>{s.label}</button>)}</div>
        <div className="cfg">
          {(Object.keys(OPTS) as (keyof typeof OPTS)[]).map((k) => (
            <label key={k}><span>{k.replace(/_/g, " ")}</span>
              <select value={profile[k]} onChange={(e) => set(k, e.target.value)}>{OPTS[k].map((o) => <option key={o}>{o}</option>)}</select>
            </label>
          ))}
          <button className="run" disabled={loading} onClick={() => build(profile)}>{loading ? "Reading the firm's history…" : "▶ Build deal sheet"}</button>
        </div>

        {sheet && (
          <div className="grid">
            {/* win */}
            <div className="card">
              <div className="ct">Win likelihood <span className="op">_predict</span></div>
              <div className="winrow">
                <div className="winpct" style={{ color: wl[1] }}>{Math.round(w!.p * 100)}<span>%</span></div>
                <div className="winmeta"><div className="winlbl" style={{ color: wl[1] }}>{wl[0]}</div><div className="winbar"><i style={{ width: `${Math.round(w!.p * 100)}%`, background: wl[1] }} /></div></div>
              </div>
              <div className="sub">why — top drivers from {sheet.profile.industry} history</div>
              {w!.drivers.map((d, i) => (
                <div className="drv" key={i}><span className="df">{d.field.replace(/_/g, " ")} = <b>{d.value}</b></span><span className={`dl ${d.lift >= 1 ? "up" : "dn"}`}>×{d.lift.toFixed(2)}</span></div>
              ))}
            </div>

            {/* effort + business case */}
            <div className="card hero">
              <div className="ct">Effort &amp; business case <span className="op">_estimate</span></div>
              <div className="big">{sheet.effort_days}<span> person-days</span></div>
              <div className="sub" style={{ marginBottom: 12 }}>estimated from similar {sheet.profile.service_line} work</div>
              <div className="bc">
                <div><span>deal value</span><b>{eur(sheet.business_case.value_eur)}</b></div>
                <div><span>delivery cost</span><b>{eur(sheet.business_case.cost_eur)}</b><i>{sheet.effort_days}d × {eur(sheet.business_case.day_rate)}</i></div>
                <div className="m"><span>gross margin</span><b style={{ color: sheet.business_case.margin_pct >= 35 ? "var(--g)" : "var(--gold-ink)" }}>{eur(sheet.business_case.margin_eur)} · {sheet.business_case.margin_pct}%</b></div>
              </div>
            </div>

            {/* references */}
            <div className="card">
              <div className="ct">Reference projects <span className="op">_query · won</span></div>
              <div className="sub">similar wins to cite in outreach</div>
              {sheet.references.length === 0 && <div className="empty">no prior wins in this exact segment yet</div>}
              {sheet.references.map((r, i) => (
                <div className="ref" key={i}><div className="rb">{r.brief}</div><div className="rm">{r.deal_size_band} · {r.effort_days}d · {r.region}</div></div>
              ))}
            </div>

            {/* outreach */}
            <div className="card">
              <div className="ct">Best way in <span className="op">_recommend</span></div>
              <div className="rec">
                <b>{sheet.outreach.recommended.channel}</b> · <b>{sheet.outreach.recommended.angle}</b> · {sheet.outreach.recommended.personalization} personalization
              </div>
              <div className="meet">
                predicted meeting rate <b>{Math.round(sheet.outreach.meeting_p * 100)}%</b>
                <span className={`gate ${sheet.outreach.auto_send ? "go" : "rev"}`}>{sheet.outreach.auto_send ? "⚡ clears auto-send gate" : "→ human review"}</span>
              </div>
              <div className="ranks">
                <div className="rk"><div className="rkl">channels</div>{sheet.outreach.channels.map((c, i) => <div className="rkrow" key={i}><span>{c.v}</span><div className="rkbar"><i style={{ width: `${Math.min(100, c.p * 220)}%` }} /></div></div>)}</div>
                <div className="rk"><div className="rkl">angles</div>{sheet.outreach.angles.slice(0, 4).map((a, i) => <div className="rkrow" key={i}><span>{a.v}</span><div className="rkbar"><i style={{ width: `${Math.min(100, a.p * 320)}%` }} /></div></div>)}</div>
              </div>
            </div>
          </div>
        )}
        <div className="foot">Every figure is a live Aito query over Northlight&apos;s own history — win &amp; drivers (`_predict`+`$why`), effort (`_estimate`), references (`_query`), outreach (`_recommend`). The LLM would draft the email; Aito supplies the facts it can&apos;t invent.</div>
      </div>
    </div>
  );
}

export default SalesView;

const CSS = `
.sa{--paper:#f4f2ec;--card:#fff;--line:#e6e2d8;--ink:#16140f;--ink2:#56524a;--faint:#928d80;--t:#16c2b9;--g:#1f6f4a;--r:#c2410c;--gold-ink:#6f561c;--gold-soft:#f6efd9;--gold-line:#e3c878;--ind:#0c0f41;
  font-family:'Figtree',ui-sans-serif,system-ui,sans-serif;background:var(--paper);color:var(--ink);min-height:100%;font-size:14px}
.sa .wrap{max-width:1060px;margin:0 auto;padding:6px 24px 60px}
.sa a{text-decoration:none}
.sa .op{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:var(--faint);background:#eee9dd;padding:2px 7px;border-radius:5px;margin-left:auto}
.sa .kick{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;margin:18px 0 10px}
.sa .chips{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
.sa .chip{font-family:'JetBrains Mono',monospace;font-size:11.5px;padding:6px 11px;border-radius:7px;border:1px solid var(--line);background:#fff;color:var(--ink2);cursor:pointer}
.sa .chip.on{background:var(--gold-soft);border-color:var(--gold-line);color:var(--gold-ink)}
.sa .cfg{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;align-items:end;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:15px 16px}
@media(max-width:980px){.sa .cfg{grid-template-columns:repeat(3,1fr)}}
@media(max-width:680px){.sa .cfg{grid-template-columns:repeat(2,1fr)}}
.sa .cfg label{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--faint);text-transform:capitalize}
.sa .cfg select{font-size:12.5px;padding:7px 8px;border:1px solid var(--line);border-radius:7px;background:#fff;color:var(--ink)}
.sa .run{grid-column:1/-1;justify-self:start;font-weight:800;font-size:13.5px;background:var(--t);color:#04221f;border:none;border-radius:8px;padding:10px 20px;cursor:pointer;margin-top:4px}
.sa .run:disabled{opacity:.6;cursor:wait}
.sa .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:18px}
@media(max-width:860px){.sa .grid{grid-template-columns:1fr}}
.sa .card{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:16px 17px}
.sa .card.hero{border-top:3px solid var(--t)}
.sa .ct{display:flex;align-items:center;gap:8px;font-weight:800;font-size:15px;margin-bottom:12px}
.sa .sub{font-size:11.5px;color:var(--faint);margin-bottom:9px}
.sa .winrow{display:flex;align-items:center;gap:16px;margin-bottom:14px}
.sa .winpct{font-size:46px;font-weight:900;letter-spacing:-.03em;line-height:1}.sa .winpct span{font-size:22px}
.sa .winmeta{flex:1}.sa .winlbl{font-weight:700;font-size:14px;margin-bottom:6px}
.sa .winbar{height:8px;background:#eee9dd;border-radius:4px;overflow:hidden}.sa .winbar i{display:block;height:100%;border-radius:4px}
.sa .drv{display:flex;align-items:center;gap:10px;padding:6px 0;border-top:1px solid #f2efe8;font-size:12.5px}
.sa .drv .df{color:var(--ink2)}.sa .drv .df b{color:var(--ink)}
.sa .drv .dl{margin-left:auto;font-family:'JetBrains Mono',monospace;font-weight:700;font-size:12px}
.sa .drv .dl.up{color:var(--g)}.sa .drv .dl.dn{color:var(--r)}
.sa .big{font-size:40px;font-weight:900;letter-spacing:-.03em;color:var(--t);line-height:1}.sa .big span{font-size:18px;color:var(--ink2);font-weight:700}
.sa .bc{border-top:1px solid #f2efe8}
.sa .bc>div{display:flex;align-items:baseline;gap:8px;padding:9px 0;border-bottom:1px solid #f2efe8;font-size:13px}
.sa .bc>div span{color:var(--faint);min-width:110px}.sa .bc>div b{font-weight:800;font-size:15px}
.sa .bc>div i{color:var(--faint);font-size:11px;font-style:normal;font-family:'JetBrains Mono',monospace}
.sa .bc .m{border-bottom:none}.sa .bc .m b{font-size:16px}
.sa .ref{padding:9px 0;border-top:1px solid #f2efe8}
.sa .ref .rb{font-size:12.5px;color:var(--ink)}.sa .ref .rm{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--faint);margin-top:2px}
.sa .empty{font-size:12px;color:var(--faint);font-style:italic;padding:8px 0}
.sa .rec{font-size:14.5px;color:var(--ink);background:var(--gold-soft);border:1px solid var(--gold-line);border-radius:9px;padding:10px 12px;margin-bottom:10px}
.sa .rec b{color:var(--gold-ink)}
.sa .meet{font-size:12.5px;color:var(--ink2);display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px}.sa .meet b{color:var(--ink)}
.sa .gate{font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;padding:3px 8px;border-radius:6px}
.sa .gate.go{background:#e7f4ec;color:var(--g)}.sa .gate.rev{background:#fff3e7;color:#9a5512}
.sa .ranks{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.sa .rkl{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:6px}
.sa .rkrow{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--ink2);margin-bottom:5px}
.sa .rkrow span{min-width:78px}.sa .rkbar{flex:1;height:6px;background:#eee9dd;border-radius:3px;overflow:hidden}.sa .rkbar i{display:block;height:100%;background:var(--t);border-radius:3px}
.sa .foot{margin-top:22px;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--faint);line-height:1.7}
`;
