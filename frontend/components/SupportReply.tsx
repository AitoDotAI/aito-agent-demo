"use client";

/* The support agent's LLM half (src/support_reply.py): the reply to the customer,
   written from Aito's decisions and checked by code guards before anything is sent,
   and the recorded Aito vs LLM comparison on the held-out queue. */

import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api";

type Guard = { name: string; ok: boolean; detail: string | null };
type Call = { model: string; input_tokens: number; output_tokens: number; ms: number; usd: number | null };
type Draft = {
  paused?: boolean; path: "routine" | "unfamiliar" | null; model: string | null; reply: string; send: "auto" | "review"; reasons: string[];
  fits: boolean | null; reading: string | null; resolution: string | null; note: string | null;
  guards: Guard[]; calls: Call[]; tokens: number; llm_ms: number; usd: number | null;
};

const STRONG = "gpt-6-luna";
const STRONG_LIMIT_S = 125; // the server gives up at 120 s; this is the page's own backstop
const lab = (v: string | null) => (v == null ? "none" : v.replace(/_/g, " "));
const secs = (ms: number) => `${(ms / 1000).toFixed(1)} s`;

export function ReplyPanel({ ticketId, text, gate }: { ticketId: string; text: string | null; gate: string }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState<null | "fast" | "strong">(null);
  const [err, setErr] = useState<string | null>(null);
  const [waited, setWaited] = useState(0);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []); // leaving the ticket cancels its request
  useEffect(() => {
    if (busy !== "strong") return;
    const t0 = Date.now();
    const id = window.setInterval(() => setWaited(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [busy]);

  const run = (stronger: boolean) => {
    const ctl = new AbortController();
    abort.current = ctl;
    const limit = stronger ? window.setTimeout(() => ctl.abort("timeout"), STRONG_LIMIT_S * 1000) : null;
    setBusy(stronger ? "strong" : "fast"); setErr(null); setWaited(0);
    apiFetch<Draft>("/api/support/reply", {
      method: "POST", headers: { "Content-Type": "application/json" }, signal: ctl.signal,
      body: JSON.stringify({ ticket_id: ticketId, text, stronger }),
    })
      .then(setDraft)
      .catch((e) => {
        if (ctl.signal.aborted) {
          setErr(ctl.signal.reason === "timeout"
            ? `${STRONG} did not answer within ${STRONG_LIMIT_S} s. The earlier read stands.`
            : "Cancelled. The earlier read stands.");
        } else setErr(String(e?.message ?? e));
      })
      .finally(() => { if (limit) window.clearTimeout(limit); setBusy(null); });
  };

  return (
    <div className="sr">
      <div className="sr-h">
        <b>The reply</b>
        <span>
          {gate === "auto"
            ? "Aito is sure, so gpt-5-mini writes the reply from its decisions, and checks they fit the ticket."
            : "Aito is not sure, so the LLM reads the ticket with Aito's shortlists and similar past tickets, and a person checks the draft."}
        </span>
      </div>
      {!draft && (
        <button className="sr-go" disabled={busy !== null} onClick={() => run(false)}>
          {busy === "fast" ? "writing…" : "Draft the reply"}
        </button>
      )}
      {err && <div className="ev-note warn">{err}</div>}
      {draft && (
        <>
          <div className="sr-verdict">
            <span className={`sr-send ${draft.send}`}>{draft.send === "auto" ? "✓ sent automatically" : "→ to a person for review"}</span>
            {draft.path && <span className="sr-path">{draft.path === "routine" ? "routine" : "unfamiliar ticket"} · {draft.model}</span>}
          </div>
          {draft.reasons.length > 0 && <ul className="sr-why">{draft.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
          {draft.path === "unfamiliar" && (
            <div className="sr-read">
              {draft.reading && <div><i>What the customer wants</i>{draft.reading}</div>}
              <div><i>Resolution it picks</i>{draft.resolution ? lab(draft.resolution) : "none of the desk's: not a case history covers"}</div>
              {draft.note && <div><i>For the colleague</i>{draft.note}</div>}
            </div>
          )}
          {draft.reply && <div className="sr-reply">{draft.reply}</div>}
          {!draft.paused && <div className="sr-guards">
            {draft.guards.map((g) => (
              <span key={g.name} className={g.ok ? "ok" : "no"} title={g.detail ?? ""}>{g.ok ? "✓" : "✗"} {g.name}</span>
            ))}
            <span className="sr-cost">
              {draft.calls.length} LLM call{draft.calls.length > 1 ? "s" : ""} · {draft.tokens.toLocaleString()} tokens · {secs(draft.llm_ms)}
              {draft.usd != null ? ` · $${(draft.usd * 1000).toFixed(2)} per 1,000 like it` : " · no list price for this model"}
            </span>
          </div>}
          {draft.path === "unfamiliar" && draft.model !== STRONG && (busy === "strong" ? (
            <div className="sr-wait">
              <span className="rc-typing"><span>{STRONG} is still thinking · {waited} s (it gives up at 120 s)</span></span>
              <button className="sr-go ghost" onClick={() => abort.current?.abort("cancel")}>Cancel</button>
            </div>
          ) : (
            <button className="sr-go ghost" disabled={busy !== null} onClick={() => run(true)}>
              Ask {STRONG} for a closer read (slow: often a minute or more)
            </button>
          ))}
        </>
      )}
      <div className="sr-foot">
        The guards are code, not prompt: a draft that promises money the decisions don&apos;t include, states a figure no
        fact contains, cites another article, or links anywhere but that article and the support portal goes to a person, and so does anything that moves money.
        {" "}<b>Known limit, being fixed:</b> a question the desk doesn&apos;t handle, worded like one it does
        (&ldquo;Where can I buy a Northwind hoodie?&rdquo;), can still be read as routine and answered. Aito is adding a
        measure of how much of a ticket&apos;s wording it has seen, which this path will route on.
      </div>
    </div>
  );
}

type Share = { share: number; ci95: [number, number] };
type Bench = {
  caveat: string; tickets: number;
  accuracy: Record<string, { all_five_right: Share }>;
  llm: Record<string, { tokens_per_ticket: number; usd_per_1000_tickets: number; calls_per_ticket: number }>;
  latency_ms: Record<string, { p50: number; p95: number }>;
  paired_vs_aito_only: Record<string, { mcnemar_p: number }>;
};

const ARMS: [string, string][] = [
  ["aito_only", "Aito only"],
  ["aito_shortlist_why_llm", "Aito shortlists + why, LLM decides"],
  ["rag_llm", "LLM + RAG (similar past tickets)"],
  ["aito_plus_llm", "Aito, LLM on its unsure steps"],
  ["llm_only", "LLM, no history"],
];

export function BenchPanel() {
  const [b, setB] = useState<Bench | null>(null);
  useEffect(() => { apiFetch<Bench>("/api/support/benchmark").then(setB).catch(() => setB(null)); }, []);
  if (!b) return null;
  const n = ARMS.length - 1;
  return (
    <div className="sb">
      <div className="sb-h"><b>Aito vs the LLM on the same {b.tickets} held-out tickets</b><span>recorded run · synthetic fixture · gpt-5-mini</span></div>
      <div className="sb-scroll">
        <table>
          <thead><tr><th /><th>all five decisions right</th><th>LLM tokens / ticket</th><th>LLM spend / 1,000 tickets</th><th>median · slowest 5%</th></tr></thead>
          <tbody>
            {ARMS.map(([k, name]) => {
              const a = b.accuracy[k]?.all_five_right, l = b.llm[k], t = b.latency_ms[k], pr = b.paired_vs_aito_only[k];
              if (!a || !l || !t) return null;
              return (
                <tr key={k} className={k === "aito_only" ? "me" : ""}>
                  <td>{name}</td>
                  <td><b>{Math.round(a.share * 100)}%</b> <i>{Math.round(a.ci95[0] * 100)}–{Math.round(a.ci95[1] * 100)}{pr ? ` · p ${pr.mcnemar_p < 0.001 ? "<0.001" : pr.mcnemar_p.toFixed(3)}` : ""}</i></td>
                  <td>{l.tokens_per_ticket === 0 ? "0" : l.tokens_per_ticket}</td>
                  <td>{l.usd_per_1000_tickets === 0 ? "none" : `$${l.usd_per_1000_tickets.toFixed(2)}`}</td>
                  <td>{secs(t.p50)} · {secs(t.p95)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="sr-foot">
        Product, category, priority, resolution and first step, each checked against what happened; 95% intervals, and a
        paired McNemar p against Aito only ({n} comparisons, so below {(0.05 / n).toFixed(4)} is conclusive, above it
        suggestive). Accuracy is on a synthetic desk with planted patterns, so it shows the method, not a forecast for
        your data. Speed and LLM spend carry over; Aito has its own compute cost, which is not LLM spend. Latency is end to
        end from our server.
      </div>
    </div>
  );
}

/** rendered once by the page, for both panels */
export const SUPPORT_REPLY_CSS = `
.sr,.sb{background:var(--rc-card);border:1px solid var(--rc-line);border-radius:12px;padding:14px 16px;margin-top:14px}
.sr{border-left:3px solid var(--turq)}
.sr-h,.sb-h{display:flex;flex-direction:column;gap:3px;font-size:12.5px;color:var(--rc-ink2)}
.sr-h b,.sb-h b{font-size:14px;color:var(--rc-ink)}
.sb-h span{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--rc-faint)}
.sr-go{margin-top:10px;font-family:inherit;font-weight:700;font-size:12.5px;background:var(--purple);color:#fff;border:none;border-radius:8px;padding:8px 14px;cursor:pointer}
.sr-go.ghost{background:transparent;color:var(--purple);border:1px solid var(--purple)}
.sr-go:disabled{opacity:.6;cursor:wait}
.sr-wait{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin-top:10px;font-size:12px;color:var(--rc-ink2)}
.sr-wait .sr-go{margin-top:0}
.sr-verdict{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;margin-top:10px}
.sr-send{font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;padding:4px 9px;border-radius:6px}
.sr-send.auto{background:#e7f4ec;color:#1f6f4a}.sr-send.review{background:#fbf1d8;color:#6f561c}
.sr-path{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--rc-faint)}
.sr-why{margin:8px 0 0;padding-left:18px;font-size:12px;color:var(--rc-ink2)}
.sr-read{display:flex;flex-direction:column;gap:5px;margin-top:10px;font-size:12.5px;color:var(--rc-ink)}
.sr-read i{font-style:normal;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint);text-transform:uppercase;letter-spacing:.05em;margin-right:8px}
.sr-reply{white-space:pre-wrap;background:#faf8f3;border:1px solid var(--rc-line);border-radius:10px;padding:12px 14px;margin-top:10px;font-size:13px;line-height:1.5;color:var(--rc-ink)}
.sr-guards{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;margin-top:9px;font-size:11.5px}
.sr-guards .ok{color:#1f6f4a}.sr-guards .no{color:#c2410c;font-weight:700}
.sr-cost{margin-left:auto;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint)}
.sr-foot{font-size:11px;color:var(--rc-faint);margin-top:10px;line-height:1.45}
.sb-scroll{overflow-x:auto;margin-top:10px}
.sb table{border-collapse:collapse;width:100%;font-size:12.5px;min-width:560px}
.sb th{text-align:left;font-weight:400;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint);padding:5px 8px;border-bottom:1px solid var(--rc-line)}
.sb td{padding:7px 8px;border-bottom:1px solid #f1efe8;color:var(--rc-ink)}
.sb td i{font-style:normal;font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--rc-faint)}
.sb tr.me td{background:#f4f1ff}
`;
