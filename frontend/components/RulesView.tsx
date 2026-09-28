"use client";

/* Decision rules: what the agent's logged decisions follow (use case #15).
   Read-only. Candidate rules are mined live with _relate over a decision log;
   a reviewer approves or rejects them here, but nothing is saved: promotion
   (aito-accounting-demo ADR 0025's POST /api/rules/promote) needs a writable
   engine, so no rule is in force and each log's model path decides (PATH). */

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Cond = { field: string; op: string; value: string };
type Rule = {
  rule: { conditions: Cond[]; target: { field: string; value: string } };
  support: { match: number; total: number };
  precision: number; coverage: number; strength: "strong" | "candidate";
};
type Mined = {
  log: string; label: string; target: string; decisions: number; decision_values: number;
  rules: Rule[]; strong: number; logs: Record<string, string>;
  thresholds: { min_precision: number; strong_precision: number; strong_match: number };
};
type Active = { rules: Rule[]; writable: boolean; note: string };
type Verdict = "approve" | "reject";

// What decides each log's decisions while no rule is in force (see app.py /api/resolve,
// /api/handoff and /api/route).
const PATH: Record<string, React.ReactNode> = {
  resolutions: <><code>_predict</code> reads the intent; its <code>$p</code> gate decides auto, assist or handoff</>,
  tool_calls: <><code>_predict</code> shortlists the tools; the LLM picks one</>,
};

const pct = (x: number) => `${Math.round(x * 100)}%`;
const cond = (c: Cond) =>
  c.op === "has" ? <>{c.field} has <b>&ldquo;{c.value}&rdquo;</b></>
  : c.op === "is" ? <>{c.field} is <b>{String(c.value)}</b></>
  : <>{c.field} {c.op} <b>{String(c.value)}</b></>;
const key = (r: Rule) => JSON.stringify(r.rule);

export function RulesView() {
  const [log, setLog] = useState("resolutions");
  const [data, setData] = useState<Mined | null>(null);
  const [active, setActive] = useState<Active | null | "error">(null);
  const [err, setErr] = useState<string | null>(null);
  const [review, setReview] = useState<Record<string, Verdict>>({});

  useEffect(() => {
    let live = true;  // a slow answer for the previous tab must not land under this one
    setData(null); setErr(null); setActive(null);
    apiFetch<Mined>(`/api/governance/rules?log=${log}`)
      .then((d) => { if (live) setData(d); })
      .catch((e) => { if (live) setErr(String(e?.message ?? e)); });
    apiFetch<Active>(`/api/rules/active?log=${log}`)
      .then((a) => { if (live) setActive(a); })
      .catch(() => { if (live) setActive("error"); });
    return () => { live = false; };
  }, [log]);

  // clicking the current verdict again clears it
  const mark = (r: Rule, v: Verdict) => setReview((s) => {
    const next = { ...s };
    if (next[key(r)] === v) delete next[key(r)]; else next[key(r)] = v;
    return next;
  });
  const reviewed = data ? data.rules.filter((r) => review[key(r)]).length : 0;
  const inForce = active === "error" ? "n/a" : active ? active.rules.length : "—";

  return (
    <div className="rc-body gv">
      <div className="rc-h">The rules your agent&apos;s decisions follow</div>
      <div className="rc-sub">
        Instead of reviewing thousands of decisions one by one, review the few rules they follow. <code>_relate</code> mines
        them from the decision log: for each rule, how many decisions its condition fires on, how often the decision then
        matched, and how much of that decision it explains. A rule can hold on the log and still be an accident of how
        the log was written. Telling those apart is the review.
      </div>

      <div className="gv-tabs" role="tablist" aria-label="Decision log">
        {Object.entries({ resolutions: "ticket resolutions", tool_calls: "tool routing" }).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={k === log} className={k === log ? "on" : ""} onClick={() => setLog(k)}>{label}</button>
        ))}
      </div>

      <div className="rc-kpis">
        <div className="rc-kpi"><div className="kl">Decisions logged</div><div className="kv">{data ? data.decisions.toLocaleString() : "—"}</div><div className="ks">{data ? `${data.decision_values} distinct ${data.target} values` : "reading the log…"}</div></div>
        <div className="rc-kpi"><div className="kl">Candidate rules</div><div className="kv">{data ? data.rules.length : "—"}</div><div className="ks">{data ? `right ≥ ${pct(data.thresholds.min_precision)} of the time they fire` : "_relate per decision"}</div></div>
        <div className="rc-kpi"><div className="kl">Strong enough to promote</div><div className="kv t">{data ? data.strong : "—"}</div><div className="ks">{data ? `≥ ${pct(data.thresholds.strong_precision)} right, on ≥ ${data.thresholds.strong_match} decisions` : ""}</div></div>
        <div className="rc-kpi"><div className="kl">Rules in force</div><div className="kv p">{inForce}</div><div className="ks">no decision is made by a rule yet</div></div>
      </div>

      {err && <div className="gv-note warn">Could not mine the log: {err}</div>}
      {!data && !err && <div className="rc-typing" style={{ padding: "20px 0" }}><span>mining the decision log…</span></div>}

      {data && (
        <>
          {log === "resolutions" && (
            <div className="gv-note">
              This ticket log is synthetic and generated from templates, so many single words decide the intent perfectly,
              including ones no reviewer would accept (&ldquo;for&rdquo; → refund). A real log gives fewer, noisier rules.
            </div>
          )}
          {log === "tool_calls" && data.strong === 0 && (
            <div className="gv-note">
              No rule here is strong enough to promote: {data.decisions.toLocaleString()} logged calls, and the words
              overlap between tools. These decisions need a model, not a rule: {PATH.tool_calls}.
            </div>
          )}
          <div className="gv-table">
            <div className="gv-row gv-head">
              <span>Rule <i>(text: word stems)</i></span><span>Fires on</span><span>Right</span><span>Explains</span><span>Review</span>
            </div>
            {data.rules.map((r) => {
              const v = review[key(r)];
              return (
                <div className={`gv-row ${v ?? ""}`} key={key(r)}>
                  <span className="gv-rule">
                    {r.rule.conditions.map((c, i) => <span key={i}>{i > 0 && " and "}{cond(c)}</span>)}
                    <span className="gv-arrow">→</span>{r.rule.target.field} <b>{r.rule.target.value}</b>
                    {r.strength === "strong" && <span className="gv-strong">strong</span>}
                  </span>
                  <span className="gv-num"><em className="gv-ml">fires on </em>{r.support.total.toLocaleString()}</span>
                  <span className="gv-num"><em className="gv-ml">right </em>{pct(r.precision)} <i>{r.support.match}/{r.support.total}</i></span>
                  <span className="gv-num"><em className="gv-ml">explains </em>{pct(r.coverage)} <i>of {r.rule.target.value}</i></span>
                  <span className="gv-act">
                    <button aria-pressed={v === "approve"} className={v === "approve" ? "on ok" : ""} onClick={() => mark(r, "approve")}>Approve</button>
                    <button aria-pressed={v === "reject"} className={v === "reject" ? "on no" : ""} onClick={() => mark(r, "reject")}>Reject</button>
                  </span>
                </div>
              );
            })}
          </div>
          <div className="rc-foot">
            {reviewed > 0 ? `${reviewed} reviewed so far. ` : ""}Your review is not saved (demo: read-only). Promoting an
            approved rule would put it in force ahead of the model. That needs a writable engine, so no rule is in force
            here: {PATH[log]}.
          </div>
        </>
      )}
      <style>{CSS}</style>
    </div>
  );
}

const CSS = `
.gv{--g:#1f6f4a}
.gv .gv-tabs{display:flex;gap:8px;margin:4px 0 16px}
.gv .gv-tabs button{font-family:inherit;font-weight:600;font-size:12.5px;padding:7px 13px;border-radius:8px;border:1px solid var(--rc-line);background:var(--rc-card);color:var(--rc-ink2);cursor:pointer}
.gv .gv-tabs button.on{background:var(--purple);border-color:var(--purple);color:#fff}
.gv .gv-note{font-size:12.5px;color:var(--rc-ink2);background:#fbf7ec;border:1px solid #efe3c2;border-radius:10px;padding:10px 13px;margin-bottom:12px;line-height:1.45}
.gv .gv-note.warn{background:#fff3e7;border-color:#f0d4b0;color:#9a5512}
.gv .gv-table{background:var(--rc-card);border:1px solid var(--rc-line);border-radius:13px;overflow:hidden}
.gv .gv-row{display:grid;grid-template-columns:minmax(0,2.6fr) .8fr 1.1fr 1.1fr 1.3fr;gap:10px;align-items:center;padding:10px 16px;border-bottom:1px solid #f1efe8;font-size:13px}
.gv .gv-row:last-child{border-bottom:none}
.gv .gv-head i{font-style:normal;text-transform:none;letter-spacing:0}
.gv .gv-head{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--rc-faint);background:#faf9f6}
.gv .gv-row.approve{background:#f1f9f4}.gv .gv-row.reject{background:#fdf3ef;color:var(--rc-faint)}
.gv .gv-rule{line-height:1.45}.gv .gv-arrow{margin:0 7px;color:var(--rc-faint)}
.gv .gv-strong{margin-left:8px;font-family:'JetBrains Mono',monospace;font-size:9.5px;padding:2px 6px;border-radius:5px;background:#e7f4ec;color:var(--g)}
.gv .gv-num{font-family:'JetBrains Mono',monospace;font-size:12px}.gv .gv-num i{font-style:normal;color:var(--rc-faint);font-size:10.5px;margin-left:4px}
.gv .gv-act{display:flex;gap:6px}
.gv .gv-ml{display:none;font-style:normal;color:var(--rc-faint);font-size:10.5px}
.gv .gv-act button{font-family:inherit;font-weight:600;font-size:11.5px;padding:5px 10px;border-radius:7px;border:1px solid var(--rc-line);background:#fff;color:var(--rc-ink2);cursor:pointer}
.gv .gv-act button.on.ok{background:var(--g);border-color:var(--g);color:#fff}
.gv .gv-act button.on.no{background:#c2542f;border-color:#c2542f;color:#fff}
@media(max-width:760px){
  .gv .gv-row{grid-template-columns:1fr 1fr 1fr;row-gap:6px}
  .gv .gv-ml{display:inline}
  .gv .gv-rule{grid-column:1 / -1}.gv .gv-act{grid-column:1 / -1}
  .gv .gv-head span:nth-child(n+2){display:none}.gv .gv-head{grid-template-columns:1fr}
}
`;
