"use client";

/* Sales agent = AgentChat wired to /api/sales-agent/chat with sales-specific
   samples and result summaries. */

import { AgentChat, num, pct, type TraceItem } from "@/components/AgentChat";
import type { ToolMeta } from "@/components/ToolboxView";

const SAMPLES = [
  "Warm referral into an Enterprise SaaS company that wants a data platform build, sole-source. Should we pursue it, and how big is the job?",
  "Cold outbound to a Public-sector custom-dev project, competitive. Is it worth it, and how should I approach the head of procurement?",
  "Existing Banking client wants an integration project. What's the win likelihood and effort — and draft an intro email to their CTO.",
];

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
    default: return JSON.stringify(r).slice(0, 80);
  }
}

export function SalesAgentView({ tools, toolOn }: { tools: ToolMeta[]; toolOn: Record<string, boolean> }) {
  return (
    <AgentChat
      endpoint="/api/sales-agent/chat"
      tools={tools} toolOn={toolOn} samples={SAMPLES}
      title="Northlight · Opportunity Assistant"
      blurb={<>A live gpt-5-mini agent. Ask it about a deal — it reasons, and calls Aito ops (<code>_predict</code>, <code>_estimate</code>, <code>_query</code>, <code>_recommend</code>) for the numbers it can&apos;t invent.</>}
      summarize={summarize}
      actionLabel="Approve & send"
    />
  );
}

export default SalesAgentView;
