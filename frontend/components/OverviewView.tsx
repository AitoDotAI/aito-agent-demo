"use client";

/* The landing / overview page, embedded as a view inside the AppShell.
   Identical content to the old standalone front page, minus its own top
   nav (the shell's left nav replaces it). Primary CTAs switch shell tabs
   via onNavigate instead of routing. */

const CSS = `
.fp{
  --paper:#f6f5f1;--card:#fff;--line:#e7e4db;--ink:#161616;--ink2:#56524a;--faint:#928d82;
  --gold:#e0b34d;--gold-soft:#f6efd9;--gold-ink:#6f561c;
  --turq:#16c2b9;--turq-ink:#04221f;--turq-soft:#e3f6f4;
  --purple:#7c6cff;--purple-soft:#efecff;--purple-ink:#3b2f9e;
  --indigo:#0c0f41;--indigo-2:#11154f;--indigo-deep:#070920;--imuted:#9aa2dd;
  background:var(--paper);color:var(--ink);font-family:'Figtree',ui-sans-serif,system-ui,sans-serif;font-size:15px;line-height:1.5;min-height:100%;
}
.fp .wrap{max-width:1080px;margin:0 auto;padding:0 26px}
.fp a{color:inherit;text-decoration:none}
.fp code{font-family:'JetBrains Mono',monospace;font-size:.86em;background:#ece9e0;padding:1px 6px;border-radius:5px;color:#3a352a}
.fp .hero{background:linear-gradient(160deg,var(--indigo-2),var(--indigo-deep));color:#eef0ff;padding:54px 0 64px;position:relative;overflow:hidden}
.fp .hero::after{content:"";position:absolute;right:-120px;top:-80px;width:420px;height:420px;border-radius:50%;background:radial-gradient(circle,rgba(22,194,185,.18),transparent 65%)}
.fp .eyebrow{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:.18em;text-transform:uppercase;color:var(--turq);font-weight:700;margin-bottom:18px}
.fp .hero h1{font-size:39px;line-height:1.12;letter-spacing:-.025em;font-weight:900;margin:0 0 22px;max-width:760px}
.fp .hero h1 .hl{color:var(--turq)}
.fp .hero h1 .dim{color:#7e87c6;font-weight:800}
.fp .faculties{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:980px){.fp .faculties{grid-template-columns:1fr}}
.fp .fac{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;position:relative}
.fp .fac.hot{border:2px solid var(--turq);box-shadow:0 8px 30px rgba(22,194,185,.13)}
.fp .fac .fl{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--faint);font-weight:700}
.fp .fac .ft{font-size:25px;font-weight:900;letter-spacing:-.02em;margin:4px 0 9px}
.fp .fac.hot .ft{color:var(--turq)}
.fp .fac .fd{font-size:13.5px;color:var(--ink2);line-height:1.55}
.fp .fac .fd b{color:var(--ink)}
.fp .fac .plus{position:absolute;top:50%;right:-19px;transform:translateY(-50%);font-size:22px;color:var(--faint);font-weight:300;z-index:2}
@media(max-width:980px){.fp .fac .plus{display:none}}
.fp .lede{font-size:17px;line-height:1.55;color:#cdd2f4;max-width:62ch;margin:0 0 16px}
.fp .lede b{color:#fff;font-weight:600}
.fp .oneliner{font-size:15.5px;color:#eef0ff;max-width:62ch;margin:0 0 28px;padding-left:14px;border-left:3px solid var(--gold)}
.fp .oneliner b{color:var(--gold)}
.fp .hbtns{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:26px}
.fp .btn{padding:13px 22px;border-radius:10px;font-weight:800;font-size:15px;cursor:pointer;border:none;display:inline-block}
.fp .btn.p{background:var(--turq);color:var(--turq-ink)}
.fp .btn.s{background:rgba(255,255,255,.08);color:#fff;border:1px solid rgba(255,255,255,.18)}
.fp .reassure{display:flex;gap:8px;flex-wrap:wrap;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--imuted)}
.fp .reassure span{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);padding:5px 10px;border-radius:7px}
.fp .reassure b{color:#dfe4ff;font-weight:500}
.fp section{padding:52px 0}
.fp .kicker{font-family:'JetBrains Mono',monospace;font-size:11.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--faint);font-weight:700;margin-bottom:10px}
.fp h2{font-size:28px;letter-spacing:-.02em;font-weight:800;margin:0 0 12px}
.fp .lead{font-size:16px;color:var(--ink2);max-width:74ch;margin:0 0 30px;line-height:1.55}
.fp .pains{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
@media(max-width:980px){.fp .pains{grid-template-columns:1fr 1fr}}
@media(max-width:600px){.fp .pains{grid-template-columns:1fr}}
.fp .pain{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 17px}
.fp .pain .ph{font-weight:700;font-size:15px;margin-bottom:5px;display:flex;gap:8px;align-items:center}
.fp .pain .ph .x{color:var(--purple);font-size:13px}
.fp .pain .pd{font-size:13.5px;color:var(--ink2);line-height:1.45}
.fp .pain .fix{margin-top:9px;font-size:12.5px;color:var(--turq-ink);background:var(--turq-soft);border-radius:7px;padding:6px 9px;line-height:1.4}
.fp .trio{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
@media(max-width:980px){.fp .trio{grid-template-columns:1fr}}
.fp .lane{background:var(--card);border:1px solid var(--line);border-radius:15px;overflow:hidden;display:flex;flex-direction:column}
.fp .lane .lh{padding:18px 20px 14px;border-bottom:1px solid var(--line)}
.fp .lane .lt{font-size:19px;font-weight:800;letter-spacing:-.01em;display:flex;align-items:center;gap:9px}
.fp .lane .lt .dot{width:10px;height:10px;border-radius:50%}
.fp .lane .ls{font-size:13px;color:var(--ink2);margin-top:5px;line-height:1.4}
.fp .lane.analyze{border-top:4px solid var(--turq)}.fp .lane.analyze .dot{background:var(--turq)}
.fp .lane.assist{border-top:4px solid var(--gold)}.fp .lane.assist .dot{background:var(--gold)}
.fp .lane.automate{border-top:4px solid var(--purple)}.fp .lane.automate .dot{background:var(--purple)}
.fp .uc{padding:15px 20px;border-bottom:1px solid #f2f0e9}.fp .uc:last-child{border-bottom:none}
.fp .uc .ut{font-weight:700;font-size:15px;display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.fp .uc .op{font-family:'JetBrains Mono',monospace;font-size:11px;padding:2px 7px;border-radius:5px;font-weight:700}
.fp .analyze .op{background:var(--turq-soft);color:var(--turq-ink)}
.fp .assist .op{background:var(--gold-soft);color:var(--gold-ink)}
.fp .automate .op{background:var(--purple-soft);color:var(--purple-ink)}
.fp .uc .ud{font-size:13px;color:var(--ink2);line-height:1.5;margin-top:5px}
.fp .uc .ud em{color:var(--ink);font-style:normal;font-weight:600}
.fp .proof{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:980px){.fp .proof{grid-template-columns:1fr}}
.fp .pc{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:18px 19px;display:flex;flex-direction:column;gap:10px}
.fp .pc .pn{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--faint)}
.fp .pc .ptt{font-weight:800;font-size:16.5px;letter-spacing:-.01em;line-height:1.25}
.fp .pc .vs,.fp .pc .ai{font-size:13px;line-height:1.5;padding:9px 11px;border-radius:8px}
.fp .pc .vs{background:#faf3ef;border:1px solid #f0ddd2;color:var(--ink2)}
.fp .pc .ai{background:var(--turq-soft);border:1px solid #c6ece8;color:var(--turq-ink)}
.fp .pc .tag{display:block;font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:3px;font-weight:700}
.fp .pc .vs .tag{color:#b06a45}.fp .pc .ai .tag{color:var(--turq-ink)}
.fp .pc b{color:var(--ink)}.fp .pc .ai b{color:var(--turq-ink)}
.fp .pc .bm{margin-top:auto;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--faint)}
.fp .band{background:var(--indigo);color:#eef0ff;border-radius:18px;padding:34px}
.fp .band h2{color:#fff}.fp .band .lead{color:#c7cdf2}
.fp .pillars{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-top:8px}
@media(max-width:980px){.fp .pillars{grid-template-columns:1fr 1fr}}
.fp .pillar .pt{font-weight:700;font-size:15px;color:#fff;margin-bottom:5px}
.fp .pillar .pp{font-size:13px;color:var(--imuted);line-height:1.5}
.fp .pillar .pt .em{color:var(--turq)}
.fp .demos{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
@media(max-width:980px){.fp .demos{grid-template-columns:1fr}}
.fp .demo{display:block;background:var(--card);border:1px solid var(--line);border-radius:13px;padding:18px 19px;transition:.15s;cursor:pointer;text-align:left;width:100%;font:inherit}
.fp .demo:hover{border-color:var(--turq);transform:translateY(-2px)}
.fp .demo .dt{font-weight:800;font-size:16px;margin-bottom:6px}
.fp .demo .dd{font-size:13.5px;color:var(--ink2);line-height:1.5}
.fp .demo .go{margin-top:12px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--turq-ink);font-weight:700}
.fp footer{padding:34px 0 50px;text-align:center;color:var(--faint);font-size:13px;border-top:1px solid var(--line)}
`;

export type OverviewNav = (view: "resolve" | "augment" | "handoff" | "sales" | "agent" | "toolbox") => void;

export function OverviewView({ onNavigate }: { onNavigate: OverviewNav }) {
  return (
    <div className="fp">
      <style dangerouslySetInnerHTML={{ __html: CSS }} />

      <div className="hero"><div className="wrap">
        <div className="eyebrow">The faculty your agent is missing</div>
        <h1><span className="dim">LLMs gave your agent reasoning. RAG gave it memory.</span> <span className="hl">Aito gives it intuition.</span></h1>
        <p className="lede">A neural network turns experience into instant answers — but that intuition is <b>frozen at training time</b>, and it&apos;s about the whole internet, not your business. LLMs are brilliant <b>amnesiacs</b>: they don&apos;t know your customers, and training one on your data isn&apos;t feasible. Aito does the same thing — pattern into answer — <b>live, over your own data, with no training.</b></p>
        <p className="oneliner">Ask it about your customers, orders, tickets, codes — and it just <b>knows</b>, with a calibrated sense of how sure it is. The <b>known and the unknown</b>, through one door.</p>
        <div className="hbtns"><button className="btn p" onClick={() => onNavigate("agent")}>Meet the agent</button><a className="btn s" href="#faculties">How it fits</a></div>
        <div className="reassure"><span>same act as the <b>neural net</b></span><span>but <b>live</b> · no training · no MLOps</span><span>over <b>your</b> data, not the world&apos;s</span><span>calibrated <b>$p</b> + <b>$why</b></span></div>
      </div></div>

      <section id="faculties"><div className="wrap">
        <div className="kicker">What it is</div>
        <h2>Reasoning · Memory · Intuition</h2>
        <p className="lead">An agent needs all three. You already have two. Aito is the third — the <b>same kind of pattern-machine as the model</b>, specialized to your data: it turns what you&apos;ve seen into an instant, calibrated answer, with no training and nothing to forget.</p>
        <div className="faculties">
          <div className="fac"><div className="fl">The LLM</div><div className="ft">Reasoning</div><div className="fd">General, deliberate thinking. A frozen intuition about the whole internet — powerful, but it can&apos;t feasibly be trained on <b>your</b> data, and it forgets the moment the context window scrolls.</div><span className="plus">+</span></div>
          <div className="fac"><div className="fl">RAG / vector store</div><div className="ft">Memory</div><div className="fd">Recall of what was stored — facts copied <b>into</b> the prompt for the model to re-read and re-reason every time. Bolted on beside the intuition, never part of it.</div><span className="plus">+</span></div>
          <div className="fac hot"><div className="fl">Aito</div><div className="ft">Intuition</div><div className="fd">The same act as the neural net — turn what you&apos;ve seen into an instant answer — but <b>live</b>, <b>memory-native</b>, and over <b>your</b> data. No training, nothing to forget. It answers <b>from</b> the data directly, and tells you how sure it is.</div></div>
        </div>
      </div></section>

      <section id="headaches"><div className="wrap">
        <div className="kicker">The agent&apos;s bad days</div>
        <h2>Six places a capable agent quietly falls down</h2>
        <p className="lead">None of these mean you picked the wrong model or built the wrong platform. They&apos;re the predictable failure modes of asking one LLM to reason <em>and</em> remember <em>and</em> do arithmetic over a large, structured, ever-changing dataset. Each has a one-query fix.</p>
        <div className="pains">
          {[
            ["Tool / option sprawl", "Hundreds of tools or SKUs in context → selection degrades, prompts bloat.", "_predict shortlists the handful that actually apply."],
            ["An LLM call on every step", "Multi-step workflows take seconds and burn tokens, per ticket, at scale.", "_predict caches the routine — ~10× faster, ~10× fewer tokens."],
            ["Vector search misfires", "Embeddings dilute identifiers — the nearest neighbour is the wrong customer.", "_match / _similarity conditions on structure, aimed at what matters."],
            ["Bad with numbers", "Aggregation, drivers, estimates — the model guesses, often confidently wrong.", "_relate / _estimate compute it from your data."],
            ["No sense of “how sure”", "Overconfident output gives no signal for when to act vs ask a human.", "$p is a calibrated gate — auto when sure, escalate when not."],
            ["Memory without relevance", "Dump everything and blow the context, or miss the one case that matters now.", "_match surfaces the memory that fits the current context."],
          ].map(([h, d, f], i) => (
            <div className="pain" key={i}><div className="ph"><span className="x">✕</span>{h}</div><div className="pd">{d}</div><div className="fix" dangerouslySetInnerHTML={{ __html: (f as string).replace(/(_\w+|\$\w+)/g, "<b>$1</b>") }} /></div>
          ))}
        </div>
      </div></section>

      <section id="trio" style={{ background: "linear-gradient(180deg,#fff,var(--paper))" }}><div className="wrap">
        <div className="kicker">The tour</div>
        <h2>Analyze · Assist · Automate</h2>
        <p className="lead">The same predictive index, three ways to plug into an agent stack — give it the facts it&apos;s missing (<b>analyze</b>), narrow and ground its choices (<b>assist</b>), or let it act when it&apos;s sure (<b>automate</b>). Every example is a real Aito op, drawn from the ecommerce, ERP and accounting demos.</p>
        <div className="trio">
          {[
            ["analyze", "Analyze", "Give the agent the numbers and structure it can’t compute.", [
              ["Find the drivers", "_relate", "<em>Why</em> are these customers churning, invoices late, projects at risk? Statistical relationships an LLM can’t aggregate."],
              ["Estimate the number", "_estimate", "Price, demand, effort, lead time — a grounded estimate instead of a confident guess."],
              ["Explain the flag", "_predict + $why", "Anomaly detection <em>with the evidence</em> behind it — the agent cites, doesn’t hallucinate."],
            ]],
            ["assist", "Assist", "Augment the model in the loop — narrow, ground, recommend.", [
              ["Shortlist the haystack", "_predict", "300 tools · 1,800 SKUs · 255 GL codes → the few that apply. <em>~16× smaller prompts</em>, same answer."],
              ["Aim the memory", "_match / _similarity", "Surface the past case that fits <em>this</em> context — targeted recall, not a fuzzy global hit."],
              ["Next best action", "_recommend", "The upsell, product, or resolution that maximizes your KPI — learned from history."],
            ]],
            ["automate", "Automate", "Let it act outright when the prediction is confident.", [
              ["Fill the fields", "_predict", "GL code, approver, cost center, assignee, category — the data entry, automatic and confidence-scored."],
              ["Match the answer", "_match", "Answer the routine ticket, FAQ, or payment <em>outright</em> — no LLM call at all."],
              ["Gate &amp; route", "_predict + $p", "Auto-handle the confident, escalate the rest. Governance and audit built in."],
            ]],
          ].map(([cls, title, sub, ucs]) => (
            <div className={`lane ${cls}`} key={cls as string}>
              <div className="lh"><div className="lt"><span className="dot" />{title}</div><div className="ls">{sub}</div></div>
              {(ucs as string[][]).map(([t, op, d], i) => (
                <div className="uc" key={i}><div className="ut" dangerouslySetInnerHTML={{ __html: `${t} <span class="op">${op}</span>` }} /><div className="ud" dangerouslySetInnerHTML={{ __html: d }} /></div>
              ))}
            </div>
          ))}
        </div>
      </div></section>

      <section id="proof"><div className="wrap">
        <div className="kicker">Benchmarked, not asserted</div>
        <h2>Measured against the standard solution</h2>
        <p className="lead">Three failure modes every agent team runs into — each one we ran as a real benchmark (live Aito + live gpt-5-mini on seeded, realistic data), against the tool a good engineer would otherwise reach for.</p>
        <div className="proof">
          <div className="pc">
            <div className="pn">01 · shortlisting</div>
            <div className="ptt">Shortlisting is a non-trivial problem</div>
            <div className="vs"><span className="tag">Standard · embedding-retrieval shortlist</span>As the catalog grows, the right tool slides out of top-k — handled-correct fell <b>58 → 40 / 75</b> from 12 to 340 tools.</div>
            <div className="ai"><span className="tag">Aito · calibrated shortlist</span>Holds as the catalog grows, and hands the LLM <b>~16× fewer tokens</b> for the same pick (3,842 → 237, live).</div>
            <div className="bm">→ telco-tool-routing-bench · live &ldquo;short-list&rdquo; view</div>
          </div>
          <div className="pc">
            <div className="pn">02 · latency</div>
            <div className="ptt">Agentic workflows get painfully slow</div>
            <div className="vs"><span className="tag">Standard · LLM agent</span>A 6-step resolution chains calls sequentially ≈ <b>22 s</b>; one call ≈ 3.6 s. Per ticket, at volume.</div>
            <div className="ai"><span className="tag">Aito · predict-first</span>Predicts in parallel, <b>~0.15 s</b> — resolved before the agent clears step one; <b>~9–10×</b> on a single call, measured live.</div>
            <div className="bm">→ resolution-scorecard · live console</div>
          </div>
          <div className="pc">
            <div className="pn">03 · context memory</div>
            <div className="ptt">Finding the right context-memory is hard</div>
            <div className="vs"><span className="tag">Standard · vector search</span>Picks the <b>wrong customer&apos;s</b> memory <b>86%</b> of the time — symptom text matches across customers; still ~47% wrong even at scale.</div>
            <div className="ai"><span className="tag">Aito · conditions on structure</span>Recovers the customer the text can&apos;t identify (flat <b>~65%</b> from little data) where embeddings dilute the signal.</div>
            <div className="bm">→ ticket-assignment-bench (v3)</div>
          </div>
        </div>
      </div></section>

      <section id="platform"><div className="wrap"><div className="band">
        <div className="kicker" style={{ color: "var(--turq)" }}>Why it fits, instead of competing</div>
        <h2>It&apos;s a primitive your agents call — not another platform to adopt.</h2>
        <p className="lead">Aito has no agents, no orchestrator, no UI to defend. It&apos;s a query you call like a tool or MCP endpoint. Your platform stays the brain; Aito is the instant, calibrated memory underneath it.</p>
        <div className="pillars">
          {[
            ["One query", "_predict · _match · _relate · _estimate · _recommend. Call it from any agent, any language."],
            ["Zero MLOps", "No model files, no retrain, no drift. A row added today is in the next prediction."],
            ["Calibrated & explainable", "Every answer has a $p and a $why that traces straight to your data. Auditable by design."],
            ["Multi-tenant by a where-clause", "One instance, isolated per customer — 255 tenants, zero per-tenant models."],
          ].map(([t, p], i) => {
            const parts = (t as string).split(" ");
            return <div className="pillar" key={i}><div className="pt">{parts.slice(0, -1).join(" ")} <span className="em">{parts.slice(-1)}</span></div><div className="pp">{p}</div></div>;
          })}
        </div>
      </div></div></section>

      <section id="live" style={{ background: "linear-gradient(180deg,#fff,var(--paper))" }}><div className="wrap">
        <div className="kicker">See it live</div>
        <h2>Real predictions, real latency, real cost</h2>
        <p className="lead">Not mocks — these run a live Aito index and a live gpt-5-mini, side by side, on synthetic-but-realistic data. Open any of them from the left.</p>
        <div className="demos">
          <button className="demo" onClick={() => onNavigate("agent")}><div className="dt">Sales agent</div><div className="dd">A live gpt-5-mini agent that calls Aito ops as <b>tools</b> — win-odds, effort, references, and the outreach that books the most meetings (with the lift). Better, faster, cheaper — and higher-yield.</div><div className="go">open →</div></button>
          <button className="demo" onClick={() => onNavigate("resolve")}><div className="dt">Resolution console</div><div className="dd">A ticket resolved instantly by _predict (with $why) beside the same gpt-5-mini call — the response-rate gap, live.</div><div className="go">open →</div></button>
          <a className="demo" href="https://ecommerce.aito.ai"><div className="dt">Industry demos</div><div className="dd">Ecommerce, ERP and accounting — recommend, relate, estimate, GL-coding, anomaly detection, from one index.</div><div className="go">ecommerce · erp · accounting →</div></a>
        </div>
      </div></section>

      <footer><div className="wrap">Aito — the predictive database. Predictions come straight from the index: no model file, no retrain step, every answer verifiable.</div></footer>
    </div>
  );
}

export default OverviewView;
