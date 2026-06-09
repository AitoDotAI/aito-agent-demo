"use client";

/* Company AI agent = AgentChat wired to /api/company-agent/chat. A 360° copilot
   over one linked customers master (sales/support/product/finance/CX). It doesn't
   just report KPIs — it finds the lever that moves each one and drafts the play.
   A SQL+LLM BI bot counts rows; this predicts, explains, optimises, and learns. */

import { AgentChat, pct, type TraceItem } from "@/components/AgentChat";
import type { ToolMeta } from "@/components/ToolboxView";

const eur = (v: unknown) => "€" + Number(v).toLocaleString("en-US");

const SAMPLES = [
  "Give me the 360 KPI snapshot for our SMB Free-plan customers, then the single biggest lever to cut their churn and the projected impact.",
  "Which lever most improves conversion for Enterprise deals, and what's the lift? Draft the play.",
  "Pull a 360 on an at-risk customer — deals, tickets, usage, invoices — and recommend what to do.",
];

function summarize(t: TraceItem): string {
  const r = t.result || {};
  if (r.error) return `⚠ ${r.error}`;
  switch (t.name) {
    case "kpi_snapshot": {
      const k = (r.kpis ?? {}) as Record<string, { p: number }>;
      const m = (key: string) => (k[key] ? pct(k[key].p) : "—");
      return `conv ${m("conversion")} · churn ${m("churn")} · NPS det ${m("nps")} · CSAT ${m("csat")} · adopt ${m("adoption")}`;
    }
    case "optimize_kpi": {
      const p = (r.recommended_play ?? {}) as { lever?: string; change_to?: string };
      const h = r.headline as { metric?: string; now?: number; then?: number } | undefined;
      const now = h ? h.now : r.current, then = h ? h.then : r.projected;
      return `${r.kpi}: ${pct(now)} → ${pct(then)} (${r.lift_pp}pp) via ${p.lever}=${p.change_to}`;
    }
    case "customer_360": {
      const d = (r.domains ?? {}) as Record<string, { count: number }>;
      const prof = (r.profile ?? {}) as { name?: string };
      return `${prof.name ?? "customer"} · ${Object.entries(d).map(([k, v]) => `${v.count} ${k}`).join(" · ")}`;
    }
    case "find_examples": return `${r.count ?? 0} ${r.domain ?? "rows"}`;
    case "estimate_mrr": return `${eur(r.mrr_eur_estimate)}/mo expected`;
    default: return JSON.stringify(r).slice(0, 80);
  }
}

export function CompanyAgentView({ tools, toolOn }: { tools: ToolMeta[]; toolOn: Record<string, boolean> }) {
  return (
    <AgentChat
      endpoint="/api/company-agent/chat"
      tools={tools} toolOn={toolOn} samples={SAMPLES}
      title="Northwind Cloud · Company AI"
      blurb={<>A 360° copilot over one <b>linked</b> customer view — sales, support, product, finance, CX. It calls Aito to give the <b>360 KPIs</b>, find the <b>lever that moves each one</b> (<code>_predict</code> + <code>_recommend</code> + projected lift), and draft the play. See → optimise → act → learn, no retrain.</>}
      summarize={summarize}
      actionLabel="Approve play"
    />
  );
}

export default CompanyAgentView;
