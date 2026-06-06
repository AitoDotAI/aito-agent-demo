"use client";

/* The conversational sales agent — the demo's thesis made literal.

   A real gpt-5-mini chat loop (POST /api/sales-agent/chat). The model reasons
   and talks; when it needs a number it can't invent it CALLS AN AITO OP, and we
   render those tool calls inline so you can watch Aito work inside the agent.
   Which tools it may call is controlled by the Toolbox (shared state) — turn the
   Aito tools off and the same agent has to guess (and says so). */

import { useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/api";
import type { ToolMeta } from "@/components/ToolboxView";

type TraceItem = { name: string; op: string; aito: boolean; args: Record<string, unknown>; result: Record<string, unknown>; ms: number };
type Turn = { input_tokens: number; output_tokens: number; latency_ms: number; cost_usd: number; steps: number };
type Msg = { role: "user" | "assistant"; content: string; trace?: TraceItem[]; turn?: Turn };

const SAMPLES = [
  "Warm referral into an Enterprise SaaS company that wants a data platform build, sole-source. Should we pursue it, and how big is the job?",
  "Cold outbound to a Public-sector custom-dev project, competitive. Is it worth it, and how should I approach the head of procurement?",
  "Existing Banking client wants an integration project. What's the win likelihood and effort — and draft an intro email to their CTO.",
];

const num = (v: unknown) => (typeof v === "number" ? v : Number(v));
const pct = (v: unknown) => `${Math.round(num(v) * 100)}%`;

// one-line summary of a tool result, per tool
function summarize(t: TraceItem): string {
  const r = t.result || {};
  if (r.error) return `⚠ ${r.error}`;
  switch (t.name) {
    case "win_odds": return `win ${pct(r.win_probability)} · ${(r.drivers as unknown[] | undefined)?.length ?? 0} drivers`;
    case "estimate_effort": return `${r.effort_days} person-days`;
    case "find_references": return `${r.count ?? (r.references as unknown[] | undefined)?.length ?? 0} won references`;
    case "recommend_outreach": {
      const lift = r.outcome_lift != null ? ` · ${num(r.outcome_lift)}× vs ${pct(r.baseline_meeting_probability)} baseline` : "";
      return `${r.channel} · ${r.angle} · meeting ${pct(r.meeting_probability)}${lift}`;
    }
    case "propose_send_email": return r.sent === false ? "draft queued — not sent" : String(r.status ?? "");
    default: return JSON.stringify(r).slice(0, 80);
  }
}

function ToolCard({ t }: { t: TraceItem }) {
  if (t.name === "propose_send_email") {
    const r = t.result || {};
    return (
      <div className="tc act">
        <div className="tch"><span className="op">action</span><b>{t.name}</b><span className="ms">gated</span></div>
        <div className="mail">
          <div className="ml"><span>to</span>{String(r.to ?? "—")}</div>
          <div className="ml"><span>subject</span>{String((t.args as Record<string, unknown>).subject ?? r.subject ?? "")}</div>
          <pre className="body">{String((t.args as Record<string, unknown>).body ?? "")}</pre>
        </div>
        <SendGate />
      </div>
    );
  }
  const argStr = Object.entries(t.args || {}).map(([k, v]) => `${k}=${v}`).join(" · ");
  return (
    <div className={`tc ${t.aito ? "aito" : ""}`}>
      <div className="tch"><span className="op">{t.op}</span><b>{t.name}</b><span className="ms">{t.ms}ms</span></div>
      {argStr && <div className="args">{argStr}</div>}
      <div className="res">→ {summarize(t)}</div>
    </div>
  );
}

// the never-auto-fire gate: approving here does NOT send — it just records intent.
function SendGate() {
  const [approved, setApproved] = useState(false);
  return (
    <div className="gate">
      {approved ? (
        <span className="ok">✓ Approved by rep — would hand to your ESP to send (demo: nothing sent)</span>
      ) : (
        <>
          <span className="lock">🔒 Draft only — never sent automatically</span>
          <button onClick={() => setApproved(true)}>Approve &amp; send</button>
        </>
      )}
    </div>
  );
}

export function SalesAgentView({ tools, toolOn }: { tools: ToolMeta[]; toolOn: Record<string, boolean> }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const scroll = useRef<HTMLDivElement | null>(null);

  const enabledNames = tools.filter((t) => toolOn[t.name] ?? true).map((t) => t.name);
  const aitoOn = tools.some((t) => t.aito && (toolOn[t.name] ?? true));
  const aitoOff = tools.some((t) => t.aito) && !aitoOn;

  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: "smooth" }); }, [msgs, loading]);

  const send = (text: string) => {
    const t = text.trim();
    if (!t || loading) return;
    const next: Msg[] = [...msgs, { role: "user", content: t }];
    setMsgs(next); setInput(""); setLoading(true); setErr(null);
    const body = tools.length
      ? { messages: next.map((m) => ({ role: m.role, content: m.content })), enabled_tools: enabledNames }
      : { messages: next.map((m) => ({ role: m.role, content: m.content })), aito_enabled: true };
    apiFetch<{ reply: string; trace: TraceItem[]; steps: number; input_tokens: number; output_tokens: number; latency_ms: number; cost_usd: number }>(
      "/api/sales-agent/chat",
      { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
    )
      .then((r) => setMsgs((m) => [...m, { role: "assistant", content: r.reply, trace: r.trace, turn: r }]))
      .catch((e: ApiError) => setErr(e?.detail || "agent unavailable"))
      .finally(() => setLoading(false));
  };

  const totCost = msgs.reduce((s, m) => s + (m.turn?.cost_usd ?? 0), 0);
  const totTok = msgs.reduce((s, m) => s + (m.turn ? m.turn.input_tokens + m.turn.output_tokens : 0), 0);
  const aitoCalls = msgs.reduce((s, m) => s + (m.trace?.filter((t) => t.aito).length ?? 0), 0);

  return (
    <div className="ag">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="ag-strip">
        <div className={`tog ${aitoOn ? "on" : "off"}`}>{aitoOn ? "● Aito tools ON" : "○ Aito tools OFF"}</div>
        <span className="meta">{tools.length ? `${enabledNames.length}/${tools.length} tools` : "loading tools…"} · set in <b>Toolbox</b></span>
        <span className="spacer" />
        <span className="axes">better · faster · cheaper · <b>+higher-yield</b></span>
        <span className="meta">{aitoCalls} Aito calls · {totTok} tokens · ${totCost.toFixed(4)}</span>
      </div>

      <div className="ag-scroll" ref={scroll}>
        {msgs.length === 0 && (
          <div className="ag-empty">
            <h3>Northlight · Opportunity Assistant</h3>
            <p>A live gpt-5-mini agent. Ask it about a deal — it reasons, and calls Aito ops (<code>_predict</code>, <code>_estimate</code>, <code>_query</code>, <code>_recommend</code>) for the numbers it can&apos;t invent. {aitoOff && <b>Aito tools are off — it&apos;ll have to guess.</b>}</p>
            <div className="samples">{SAMPLES.map((s, i) => <button key={i} onClick={() => send(s)}>{s}</button>)}</div>
          </div>
        )}

        {msgs.map((m, i) => (
          <div key={i} className={`row ${m.role}`}>
            {m.role === "user" ? (
              <div className="bub u">{m.content}</div>
            ) : (
              <div className="asst">
                {m.trace && m.trace.length > 0 && (
                  <div className="trace">
                    <div className="tlbl">{m.trace.some((t) => t.aito) ? "called the toolbox" : "no Aito tools available — reasoning only"}</div>
                    {m.trace.map((t, j) => <ToolCard key={j} t={t} />)}
                  </div>
                )}
                <div className="bub a">{m.content}</div>
                {m.turn && <div className="tmeta">{m.turn.steps} tool calls · {m.turn.input_tokens + m.turn.output_tokens} tokens · ${m.turn.cost_usd.toFixed(4)} · {(m.turn.latency_ms / 1000).toFixed(1)}s</div>}
              </div>
            )}
          </div>
        ))}

        {loading && <div className="row assistant"><div className="asst"><div className="working"><i /><i /><i /><span>agent reasoning &amp; calling tools…</span></div></div></div>}
        {err && <div className="row assistant"><div className="bub a err">⚠ {err}</div></div>}
      </div>

      <div className="ag-compose">
        <textarea rows={1} value={input} placeholder="Ask about an opportunity…" disabled={loading}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
        <button disabled={loading || !input.trim()} onClick={() => send(input)}>{loading ? "…" : "Send"}</button>
      </div>
    </div>
  );
}

export default SalesAgentView;

const CSS = `
.ag{--card:#fff;--line:#e7e4db;--ink:#1c1c1c;--ink2:#5e5b53;--faint:#9b978c;--turq:#16c2b9;--turq-ink:#04221f;--turq-soft:#e3f6f4;--gold-soft:#f6efd9;--gold-ink:#6f561c;--purple:#7c6cff;--purple-soft:#efecff;--purple-ink:#3b2f9e;
  display:flex;flex-direction:column;height:100%;background:#faf9f6;font-family:'Figtree',ui-sans-serif,system-ui,sans-serif;color:var(--ink)}
.ag code{font-family:'JetBrains Mono',monospace;font-size:.84em;background:#ece9e0;padding:1px 5px;border-radius:4px}
.ag-strip{display:flex;align-items:center;gap:12px;padding:9px 22px;border-bottom:1px solid var(--line);background:#fff;font-size:12px;color:var(--ink2)}
.ag-strip .spacer{flex:1}
.ag-strip .meta b{color:var(--ink)}
.ag-strip .tog{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;padding:4px 9px;border-radius:6px}
.ag-strip .tog.on{background:var(--turq-soft);color:var(--turq-ink)}
.ag-strip .tog.off{background:#f1eee8;color:var(--faint)}
.ag-strip .axes{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--faint)}
.ag-strip .axes b{color:var(--turq-ink);font-weight:700}
.ag-scroll{flex:1;overflow-y:auto;padding:22px;display:flex;flex-direction:column;gap:16px}
.ag-empty{max-width:680px;margin:6vh auto 0;text-align:center}
.ag-empty h3{font-size:22px;font-weight:800;margin:0 0 8px}
.ag-empty p{font-size:14px;color:var(--ink2);line-height:1.55;margin:0 0 20px}
.ag-empty .samples{display:flex;flex-direction:column;gap:8px;max-width:560px;margin:0 auto}
.ag-empty .samples button{text-align:left;font-size:13px;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:10px;padding:11px 13px;cursor:pointer;line-height:1.4}
.ag-empty .samples button:hover{border-color:var(--turq);background:var(--turq-soft)}
.row{display:flex}
.row.user{justify-content:flex-end}
.bub{max-width:760px;border-radius:13px;padding:12px 15px;font-size:14px;line-height:1.55;white-space:pre-wrap}
.bub.u{background:var(--ink);color:#fff;border-bottom-right-radius:4px}
.bub.a{background:#fff;border:1px solid var(--line);border-bottom-left-radius:4px}
.bub.err{background:#fbe9df;border-color:#f0c8b2;color:#9a3a12}
.asst{display:flex;flex-direction:column;gap:9px;max-width:780px}
.tmeta{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--faint);padding-left:3px}
.trace{display:flex;flex-direction:column;gap:7px;border-left:2px solid var(--turq);padding-left:12px;margin-left:2px}
.tlbl{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:700}
.tc{background:#fff;border:1px solid var(--line);border-radius:10px;padding:9px 11px}
.tc.aito{border-color:#bfeae6;background:linear-gradient(180deg,#fff,#f4fcfb)}
.tc.act{border-color:#ddd5f5;background:linear-gradient(180deg,#fff,#f8f6ff)}
.tch{display:flex;align-items:center;gap:8px;font-size:13px}
.tch b{font-weight:700}
.tch .op{font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:5px;background:var(--turq-soft);color:var(--turq-ink)}
.tc.act .op{background:var(--purple-soft);color:var(--purple-ink)}
.tch .ms{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--faint)}
.args{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--ink2);margin-top:6px;line-height:1.5;word-break:break-word}
.res{font-size:12.5px;font-weight:600;color:var(--turq-ink);margin-top:6px}
.tc.act .mail{margin-top:8px;border-top:1px dashed var(--line);padding-top:8px}
.mail .ml{font-size:12px;color:var(--ink2);margin-bottom:3px}.mail .ml span{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--faint);margin-right:8px;text-transform:uppercase}
.mail .body{font-family:'Figtree',sans-serif;font-size:12.5px;color:var(--ink);white-space:pre-wrap;background:#faf9f6;border:1px solid var(--line);border-radius:8px;padding:9px 11px;margin:6px 0 0;max-height:200px;overflow:auto;line-height:1.5}
.gate{display:flex;align-items:center;gap:10px;margin-top:9px;flex-wrap:wrap}
.gate .lock{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--gold-ink);background:var(--gold-soft);padding:3px 8px;border-radius:6px;font-weight:700}
.gate .ok{font-size:11.5px;color:var(--turq-ink);background:var(--turq-soft);padding:4px 9px;border-radius:6px}
.gate button{font-size:12px;font-weight:700;background:var(--purple);color:#fff;border:none;border-radius:7px;padding:6px 13px;cursor:pointer}
.working{display:flex;align-items:center;gap:8px;background:#fff;border:1px solid var(--line);border-radius:13px;padding:12px 15px;font-size:13px;color:var(--ink2)}
.working i{width:7px;height:7px;border-radius:50%;background:var(--turq);animation:agb 1s infinite ease-in-out}
.working i:nth-child(2){animation-delay:.15s}.working i:nth-child(3){animation-delay:.3s}
@keyframes agb{0%,80%,100%{opacity:.25}40%{opacity:1}}
.ag-compose{display:flex;gap:10px;padding:14px 22px;border-top:1px solid var(--line);background:#fff}
.ag-compose textarea{flex:1;resize:none;font-family:inherit;font-size:14px;padding:11px 13px;border:1px solid var(--line);border-radius:10px;line-height:1.4;max-height:120px}
.ag-compose textarea:focus{outline:none;border-color:var(--turq)}
.ag-compose button{font-weight:800;font-size:14px;background:var(--turq);color:var(--turq-ink);border:none;border-radius:10px;padding:0 22px;cursor:pointer}
.ag-compose button:disabled{opacity:.5;cursor:not-allowed}
`;
