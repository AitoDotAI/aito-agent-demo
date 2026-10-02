#!/usr/bin/env node
/* Deep links, cold: every view (and its key state) must be reachable from a pasted URL in a
   fresh browser, the URL must follow navigation, and back/forward must work.

     BASE_URL=http://127.0.0.1:4105 CHROME_PATH=... node scripts/e2e-deeplinks.cjs

   Each case opens a NEW browser context (no history, no storage) on the URL and asserts what
   the page shows. Exit code = number of failed cases. */
const { chromium } = require("playwright-core");

const BASE = (process.env.BASE_URL || "http://127.0.0.1:4105").replace(/\/$/, "");
const TIMEOUT = 30000;

// the active nav item names the view; data-state attributes carry each view's key state
const activeView = (page) => page.locator(".rc-item.on").first().getAttribute("data-view", { timeout: TIMEOUT });
const stateOf = (page, sel) => page.locator(sel).first().getAttribute("data-state", { timeout: TIMEOUT });

const CASES = [
  { url: "/", view: "home" },
  { url: "/?view=resolve&sample=2", view: "resolve", state: ["[data-route='resolve']", "sample=2"] },
  { url: "/?view=augment&sample=3", view: "augment", state: ["[data-route='augment']", "sample=3"] },
  { url: "/?view=handoff", view: "handoff" },
  { url: "/?view=rules&log=tool_calls", view: "rules", state: ["[data-route='rules']", "log=tool_calls"] },
  { url: "/?view=support&ticket=SUP-11971", view: "support", state: ["[data-route='support']", "ticket=SUP-11971"] },
  { url: "/?view=sales&sample=2", view: "sales", state: ["[data-route='sales']", "sample=2"] },
  { url: "/?view=agent", view: "agent" },
  { url: "/?view=toolbox", view: "toolbox" },
  { url: "/?view=company", view: "company" },
  { url: "/?view=company-data&size=Enterprise&plan=Pro", view: "company-data",
    state: ["[data-route='company-data']", "industry=Any&size=Enterprise&plan=Pro"] },
  { url: "/?view=company-toolbox", view: "company-toolbox" },
  // links that already work must keep working
  { url: "/sales/", view: "sales" },
  { url: "/console/", view: "resolve" },
  { url: "/console/?view=handoff", view: "handoff" },
  { url: "/company/", view: "company" },
];

async function main() {
  const executablePath = process.env.CHROME_PATH || (process.platform === "linux" ? "/usr/bin/chromium" : undefined);
  const browser = await chromium.launch({ executablePath, headless: true });
  let failed = 0;
  const check = (ok, label, detail = "") => {
    if (!ok) failed++;
    console.log(`${ok ? "✓" : "✗"} ${label}${detail ? `  (${detail})` : ""}`);
  };

  for (const c of CASES) {
    const ctx = await browser.newContext();          // cold: a fresh browser profile per link
    const page = await ctx.newPage();
    try {
      await page.goto(BASE + c.url, { waitUntil: "domcontentloaded" });
      const v = await activeView(page);
      let ok = v === c.view, detail = `view ${v}`;
      if (ok && c.state) {
        const s = await stateOf(page, c.state[0]);
        ok = s === c.state[1];
        detail += `, state ${s}`;
      }
      check(ok, `cold ${c.url} → ${c.view}${c.state ? ` [${c.state[1]}]` : ""}`, detail);
    } catch (e) {
      check(false, `cold ${c.url}`, e.message.split("\n")[0]);
    }
    await ctx.close();
  }

  // navigation writes the URL; back/forward restore the view
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  try {
    await page.goto(BASE + "/", { waitUntil: "domcontentloaded" });
    await page.locator(".rc-item[data-view='handoff']").first().click();
    await page.waitForURL(/view=handoff/, { timeout: TIMEOUT });
    check(true, "navigating writes ?view=handoff");
    await page.locator(".rc-item[data-view='rules']").first().click();
    await page.waitForURL(/view=rules/, { timeout: TIMEOUT });
    await page.goBack();
    await page.waitForURL(/view=handoff/, { timeout: TIMEOUT });
    check((await activeView(page)) === "handoff", "back returns to handoff");
    await page.goForward();
    await page.waitForURL(/view=rules/, { timeout: TIMEOUT });
    check((await activeView(page)) === "rules", "forward returns to rules");
    // a state change inside a view lands in the URL, so the address is always shareable
    await page.locator("[data-route='rules'] [data-log='tool_calls']").first().click();
    await page.waitForURL(/log=tool_calls/, { timeout: TIMEOUT });
    check(true, "changing the rules log writes log=tool_calls");
  } catch (e) {
    check(false, "navigation and history", e.message.split("\n")[0]);
  }
  await ctx.close();
  await browser.close();
  console.log(failed ? `\n${failed} failed` : "\nall deep links work");
  process.exit(failed);
}

main().catch((e) => { console.error(e); process.exit(99); });
