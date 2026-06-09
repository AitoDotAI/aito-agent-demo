"use client";

/* The agent's toolbox — and the on/off switch that proves the thesis.

   Lists every tool the sales agent can call. Four are Aito ops over the firm's
   history; one is a plain (gated) action. Flip the Aito tools off and the SAME
   chat agent has to reason without the firm's data — grounded numbers vs a
   flagged guess. The toggle state lives in AppShell and is shared with the chat
   view, so changes here take effect on the next message. */

export type ToolMeta = { name: string; op: string; aito: boolean; summary: string; params: string[] };

export function ToolboxView({ tools, toolOn, onToggle, onAllAito, agentLabel, lead, examples }: {
  tools: ToolMeta[];
  toolOn: Record<string, boolean>;
  onToggle: (name: string) => void;
  onAllAito: (on: boolean) => void;
  agentLabel: string;
  lead: React.ReactNode;
  examples: Record<string, string>;
}) {
  const aitoTools = tools.filter((t) => t.aito);
  const aitoAllOn = aitoTools.length > 0 && aitoTools.every((t) => toolOn[t.name] ?? true);

  return (
    <div className="tb">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />
      <div className="wrap">
        <div className="kick">The agent&apos;s toolbox</div>
        <h2>Aito ops, registered as tools</h2>
        <p className="lead">{lead}</p>

        <div className={`master ${aitoAllOn ? "on" : "off"}`}>
          <div>
            <div className="mt">Aito tools <span className="badge">{aitoAllOn ? "ON" : "OFF"}</span></div>
            <div className="ms">{aitoAllOn ? "The agent reads real data for grounded, calibrated answers." : "The agent is on its own — grounded numbers replaced by flagged guesses."}</div>
          </div>
          <button className="switch" onClick={() => onAllAito(!aitoAllOn)} role="switch" aria-checked={aitoAllOn}>
            <span className="knob" />
          </button>
        </div>

        <div className="grid">
          {tools.map((t) => {
            const on = toolOn[t.name] ?? true;
            return (
              <div className={`tool ${t.aito ? "aito" : "act"} ${on ? "" : "dim"}`} key={t.name}>
                <div className="th">
                  <span className={`op ${t.aito ? "" : "a"}`}>{t.op}</span>
                  <b>{t.name}</b>
                  <button className={`chk ${on ? "on" : ""}`} onClick={() => onToggle(t.name)} aria-label={`toggle ${t.name}`}>{on ? "✓" : ""}</button>
                </div>
                <div className="sum">{t.summary}</div>
                <div className="ex">{examples[t.name] ?? ""}</div>
                <div className="pr">{t.params.map((p) => <span key={p}>{p}</span>)}</div>
                {!t.aito && <div className="note">🔒 gated — drafts only, never auto-sends</div>}
              </div>
            );
          })}
          {tools.length === 0 && <div className="empty">loading toolbox…</div>}
        </div>

        <div className="foot">Toggling a tool changes which functions are handed to the model on your next message in <b>{agentLabel}</b>. Everything else about the agent stays identical — same prompt, same model — so the difference you see is exactly what Aito adds.</div>
      </div>
    </div>
  );
}

export default ToolboxView;

const CSS = `
.tb{--card:#fff;--line:#e7e4db;--ink:#1c1c1c;--ink2:#5e5b53;--faint:#9b978c;--turq:#16c2b9;--turq-ink:#04221f;--turq-soft:#e3f6f4;--gold-soft:#f6efd9;--gold-ink:#6f561c;--purple:#7c6cff;--purple-soft:#efecff;--purple-ink:#3b2f9e;
  height:100%;overflow-y:auto;background:#faf9f6;font-family:'Figtree',ui-sans-serif,system-ui,sans-serif;color:var(--ink)}
.tb .wrap{max-width:920px;margin:0 auto;padding:26px 24px 60px}
.tb .kick{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:8px}
.tb h2{font-size:26px;font-weight:800;letter-spacing:-.02em;margin:0 0 10px}
.tb .lead{font-size:15px;color:var(--ink2);line-height:1.55;margin:0 0 22px;max-width:74ch}
.tb .lead b,.tb .foot b{color:var(--ink)}
.tb code{font-family:'JetBrains Mono',monospace;font-size:.84em;background:#ece9e0;padding:1px 5px;border-radius:4px}
.tb .master{display:flex;align-items:center;gap:16px;border-radius:14px;padding:16px 18px;margin-bottom:20px;border:1px solid}
.tb .master.on{background:var(--turq-soft);border-color:#bfeae6}
.tb .master.off{background:#f3f1ec;border-color:var(--line)}
.tb .master>div:first-child{flex:1}
.tb .mt{font-size:16px;font-weight:800;display:flex;align-items:center;gap:9px}
.tb .mt .badge{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;padding:2px 8px;border-radius:5px;background:#fff;border:1px solid var(--line)}
.tb .master.on .badge{color:var(--turq-ink)}
.tb .ms{font-size:13px;color:var(--ink2);margin-top:4px;line-height:1.45}
.tb .switch{position:relative;width:58px;height:32px;border-radius:16px;border:none;cursor:pointer;background:#cfcabf;transition:.18s;flex:0 0 auto}
.tb .master.on .switch{background:var(--turq)}
.tb .switch .knob{position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;transition:.18s;box-shadow:0 1px 3px rgba(0,0,0,.25)}
.tb .master.on .switch .knob{left:29px}
.tb .grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:760px){.tb .grid{grid-template-columns:1fr}}
.tb .tool{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:15px 16px;transition:.15s}
.tb .tool.aito{border-left:3px solid var(--turq)}
.tb .tool.act{border-left:3px solid var(--purple)}
.tb .tool.dim{opacity:.5}
.tb .th{display:flex;align-items:center;gap:9px}
.tb .th b{font-size:14.5px;font-weight:700}
.tb .th .op{font-family:'JetBrains Mono',monospace;font-size:10.5px;font-weight:700;padding:2px 7px;border-radius:5px;background:var(--turq-soft);color:var(--turq-ink)}
.tb .th .op.a{background:var(--purple-soft);color:var(--purple-ink)}
.tb .chk{margin-left:auto;width:24px;height:24px;border-radius:7px;border:1.5px solid var(--line);background:#fff;cursor:pointer;font-size:13px;color:var(--turq-ink);font-weight:800;display:flex;align-items:center;justify-content:center}
.tb .chk.on{background:var(--turq);border-color:var(--turq);color:#fff}
.tb .sum{font-size:13px;color:var(--ink2);line-height:1.45;margin-top:9px}
.tb .ex{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--faint);margin-top:8px;background:#faf9f6;border:1px solid var(--line);border-radius:7px;padding:6px 8px;line-height:1.5;word-break:break-word}
.tb .pr{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}
.tb .pr span{font-family:'JetBrains Mono',monospace;font-size:9.5px;color:var(--ink2);background:#f1eee8;padding:2px 6px;border-radius:5px}
.tb .note{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--gold-ink);margin-top:9px}
.tb .empty{color:var(--faint);font-size:13px;padding:20px}
.tb .foot{margin-top:22px;font-size:12.5px;color:var(--ink2);line-height:1.6;border-top:1px solid var(--line);padding-top:16px}
`;
