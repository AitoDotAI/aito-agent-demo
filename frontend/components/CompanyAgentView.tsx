"use client";

/* Company AI agent = AgentChat wired to /api/company-agent/chat. A SQL+LLM BI
   bot can count rows; this answers WHY accounts churn, what drags NPS, the
   expected MRR of a cohort, and what to fix — calibrated, with drivers. */

import { AgentChat, pct, type TraceItem } from "@/components/AgentChat";
import type { ToolMeta } from "@/components/ToolboxView";

const eur = (v: unknown) => "€" + Number(v).toLocaleString("en-US");

const SAMPLES = [
  "Our SMB Free-plan accounts with Red health and no onboarding — are they a churn risk, what's dragging their NPS, and what should we focus on?",
  "What's the expected MRR for an Enterprise account on the Pro plan with 100+ seats?",
  "Which feedback themes hurt us most in the Mid-market segment, and which accounts there are at risk?",
];

function summarize(t: TraceItem): string {
  const r = t.result || {};
  if (r.error) return `⚠ ${r.error}`;
  switch (t.name) {
    case "churn_risk": return `churn ${pct(r.churn_probability)} · ${(r.drivers as unknown[] | undefined)?.length ?? 0} drivers`;
    case "nps_drivers": return `detractor ${pct(r.detractor_probability)} · promoter ${pct(r.promoter_probability)}`;
    case "estimate_mrr": return `${eur(r.mrr_eur_estimate)}/mo expected`;
    case "find_accounts": return `${r.count ?? 0} example accounts`;
    case "recommend_focus": return ((r.themes_to_prioritise as { theme: string }[] | undefined) ?? []).map((x) => x.theme).join(" · ");
    default: return JSON.stringify(r).slice(0, 80);
  }
}

export function CompanyAgentView({ tools, toolOn }: { tools: ToolMeta[]; toolOn: Record<string, boolean> }) {
  return (
    <AgentChat
      endpoint="/api/company-agent/chat"
      tools={tools} toolOn={toolOn} samples={SAMPLES}
      title="Northwind Cloud · Company AI"
      blurb={<>Ask about the company&apos;s own numbers. A BI bot can count rows; this calls Aito ops (<code>_predict</code>, <code>_estimate</code>, <code>_recommend</code>) to tell you <b>which accounts churn and why</b>, what drags NPS, and what to fix — calibrated, with drivers.</>}
      summarize={summarize}
      actionLabel="Approve task"
    />
  );
}

export default CompanyAgentView;
