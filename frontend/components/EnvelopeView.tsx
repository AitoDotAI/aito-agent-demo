"use client";

/* The support agent's predictive envelope (docs/design/support-agent.md, phase 1).
   One incoming ticket and the steps a support agent takes, each grounded by an
   Aito op, with its confidence, latency and the ticket's recorded truth.
   Read-only: the tickets are a held-out queue Aito has never seen, and the backend
   refuses any prediction that uses a field recorded later (src/support_envelope.py). */

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Alt = { value: string; p: number };
type Case = { ticket_id: string; text: string; resolution: string; nps_after: string };
type Step = {
  key: string; title: string; op: string; value: string | null; p: number | null; alternatives: Alt[];
  inputs: string[]; ms: number; truth: string | null; correct: boolean | null; note: string | null;
  gate?: "auto" | "assist" | "human"; cases?: Case[];
};
type Envelope = {
  ticket: { ticket_id: string; created_at: string; text: string; sender_domain: string; channel: string };
  steps: Step[]; gate: "auto" | "assist" | "human"; aito_calls: number; aito_ms: number;
};
type Incoming = { ticket_id: string; created_at: string; text: string; channel: string };

const pct = (p: number | null) => (p == null ? "" : `${Math.round(p * 100)}%`);
const label = (v: string | null) => (v == null ? "none" : v.replace(/_/g, " "));
const GATE = {
  auto: "served from history: no LLM call",
  assist: "the LLM decides, from Aito's shortlist",
  human: "a person decides, with Aito's tentative read",
};

export function EnvelopeView() {
  const [queue, setQueue] = useState<Incoming[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [env, setEnv] = useState<Envelope | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<{ tickets: Incoming[] }>("/api/support/incoming")
      .then((r) => { setQueue(r.tickets.slice(0, 12)); setSel(r.tickets[0]?.ticket_id ?? null); })
      .catch((e) => setErr(String(e?.message ?? e)));
  }, []);

  useEffect(() => {
    if (!sel) return;
    let live = true;
    setEnv(null); setErr(null);
    apiFetch<Envelope>(`/api/support/envelope?ticket_id=${sel}`)
      .then((r) => { if (live) setEnv(r); })
      .catch((e) => { if (live) setErr(String(e?.message ?? e)); });
    return () => { live = false; };
  }, [sel]);

  const scored = env ? env.steps.filter((s) => s.correct !== null) : [];
  const right = scored.filter((s) => s.correct).length;

  return (
    <div className="rc-body ev">
      <div className="rc-h">One ticket, inside Aito&apos;s predictive envelope</div>
      <div className="rc-sub">
        The agent (an LLM) reads and writes. Around it, every step a support agent takes is grounded by one Aito call:
        who wrote, what it&apos;s about, how urgent, whether history already knows the answer, what to try first, and
        how to keep the customer. These tickets are held out: Aito has never seen them, and each step is checked
        against what really happened.
      </div>

      <div className="ev-grid">
        <div className="ev-queue">
          <div className="ev-ql">Incoming queue</div>
          {queue.map((t) => (
            <button key={t.ticket_id} className={t.ticket_id === sel ? "on" : ""} onClick={() => setSel(t.ticket_id)}>
              <span className="ev-qt">{t.text}</span>
              <span className="ev-qm">{t.ticket_id} · {t.channel} · {t.created_at.slice(5, 16).replace("T", " ")}</span>
            </button>
          ))}
        </div>

        <div className="ev-main">
          {err && <div className="ev-note warn">{err}</div>}
          {!env && !err && <div className="rc-typing" style={{ padding: "20px 0" }}><span>running the envelope…</span></div>}
          {env && (
            <>
              <div className="ev-ticket">
                <div className="ev-tt">{env.ticket.text}</div>
                <div className="ev-tm">{env.ticket.ticket_id} · from {env.ticket.sender_domain} · {env.ticket.channel}</div>
              </div>
              <div className="ev-sum">
                <span><b>{env.aito_calls}</b> Aito calls</span>
                <span><b>{env.aito_ms.toLocaleString()} ms</b> in total</span>
                <span className={`ev-gate ${env.gate}`}>{GATE[env.gate]}</span>
                <span><b>{right} of {scored.length}</b> steps match what happened</span>
              </div>
              <div className="ev-steps">
                {env.steps.map((s, i) => (
                  <div key={s.key} className={`ev-step ${s.key === "resolution" ? "key" : ""}`}>
                    <div className="ev-sh"><span className="ev-n">{i + 1}</span>{s.title}<span className="ev-op">{s.op}</span></div>
                    {s.cases ? (
                      <div className="ev-cases">
                        {s.cases.map((c) => (
                          <div key={c.ticket_id}><span>{c.text}</span><i>{label(c.resolution)} · {c.nps_after}</i></div>
                        ))}
                      </div>
                    ) : (
                      <>
                        <div className="ev-val"><b>{label(s.value)}</b> <span className="ev-p">{pct(s.p)}</span></div>
                        {s.p != null && <div className="ev-bar"><i style={{ width: pct(s.p) }} /></div>}
                        {s.alternatives.length > 0 && (
                          <div className="ev-alt">then {s.alternatives.map((a) => `${label(a.value)} ${pct(a.p)}`).join(" · ")}</div>
                        )}
                      </>
                    )}
                    <div className="ev-foot">
                      {s.correct === true && <span className="ok">✓ matches: {label(s.truth)}</span>}
                      {s.correct === false && <span className="no">✗ it was {label(s.truth)}</span>}
                      {s.gate && <span className={`ev-gate ${s.gate}`}>{GATE[s.gate]}</span>}
                      <span className="ev-ms">{s.ms} ms · from {s.inputs.join(", ")}</span>
                    </div>
                    {s.note && <div className="ev-note-s">{s.note}</div>}
                  </div>
                ))}
              </div>
              <div className="rc-foot">
                Synthetic data (the support fixture), labelled as such; its planted effects are measured in
                scripts/support_fixture. Each prediction may only use the inputs listed for its target, so nothing
                recorded after the ticket can leak into it. The LLM-only comparison is added from recorded runs.
              </div>
            </>
          )}
        </div>
      </div>
      <style>{CSS}</style>
    </div>
  );
}

const CSS = `
.ev{--g:#1f6f4a;--r:#c2410c}
.ev .ev-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:18px;align-items:start}
.ev .ev-queue{display:flex;flex-direction:column;gap:6px;position:sticky;top:12px}
.ev .ev-ql{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--rc-faint);margin-bottom:2px}
.ev .ev-queue button{text-align:left;font-family:inherit;background:var(--rc-card);border:1px solid var(--rc-line);border-radius:10px;padding:9px 11px;cursor:pointer;display:flex;flex-direction:column;gap:4px}
.ev .ev-queue button.on{border-color:var(--purple);box-shadow:0 0 0 2px rgba(155,105,255,.18)}
.ev .ev-qt{font-size:12.5px;color:var(--rc-ink);line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ev .ev-qm{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint)}
.ev .ev-ticket{background:var(--rc-card);border:1px solid var(--rc-line);border-left:3px solid var(--purple);border-radius:12px;padding:14px 16px}
.ev .ev-tt{font-size:15px;line-height:1.45;color:var(--rc-ink)}
.ev .ev-tm{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--rc-faint);margin-top:6px}
.ev .ev-sum{display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center;margin:12px 2px;font-size:12.5px;color:var(--rc-ink2)}
.ev .ev-gate{font-family:'JetBrains Mono',monospace;font-size:10.5px;padding:3px 8px;border-radius:6px}
.ev .ev-gate.auto{background:#e7f4ec;color:var(--g)}.ev .ev-gate.assist{background:#fbf1d8;color:#6f561c}.ev .ev-gate.human{background:#fbe4d8;color:var(--r)}
.ev .ev-steps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.ev .ev-step{background:var(--rc-card);border:1px solid var(--rc-line);border-radius:12px;padding:12px 14px}
.ev .ev-step.key{border-color:var(--purple);box-shadow:0 0 0 2px rgba(155,105,255,.12)}
.ev .ev-sh{display:flex;align-items:center;gap:8px;font-weight:700;font-size:13.5px}
.ev .ev-n{width:20px;height:20px;border-radius:50%;background:#f1eee8;color:var(--rc-ink2);font-size:11px;display:inline-flex;align-items:center;justify-content:center}
.ev .ev-op{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:400;color:var(--plight)}
.ev .ev-val{margin-top:8px;font-size:15px}.ev .ev-p{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--rc-ink2)}
.ev .ev-bar{height:5px;background:#f1eee8;border-radius:3px;margin-top:6px;overflow:hidden}.ev .ev-bar i{display:block;height:100%;background:var(--turq)}
.ev .ev-alt{font-size:11.5px;color:var(--rc-faint);margin-top:5px}
.ev .ev-cases{display:flex;flex-direction:column;gap:6px;margin-top:8px;font-size:12px;color:var(--rc-ink2)}
.ev .ev-cases i{font-style:normal;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--rc-faint);margin-left:6px}
.ev .ev-foot{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin-top:9px;font-size:11.5px}
.ev .ev-foot .ok{color:var(--g)}.ev .ev-foot .no{color:var(--r)}
.ev .ev-ms{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint);margin-left:auto}
.ev .ev-note-s{font-size:11px;color:var(--rc-faint);margin-top:6px;line-height:1.4}
.ev .ev-note{font-size:12.5px;background:#fbf7ec;border:1px solid #efe3c2;border-radius:10px;padding:10px 13px;margin-bottom:12px}
.ev .ev-note.warn{background:#fff3e7;border-color:#f0d4b0;color:#9a5512}
@media(max-width:900px){
  .ev .ev-grid{grid-template-columns:1fr}.ev .ev-queue{position:static;flex-direction:row;overflow-x:auto}
  .ev .ev-ql{display:none}
  .ev .ev-queue button{min-width:220px}.ev .ev-steps{grid-template-columns:1fr}
}
`;
