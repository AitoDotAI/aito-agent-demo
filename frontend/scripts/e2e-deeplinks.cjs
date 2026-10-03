#!/usr/bin/env node
/* Deep links, cold: every view (and its key state) must be reachable from a pasted URL in a
   fresh browser, the URL must follow navigation, and back/forward must work.

     BASE_URL=http://127.0.0.1:4105 CHROME_PATH=... node scripts/e2e-deeplinks.cjs

   Each case opens a NEW browser context (no history, no storage) on the URL and asserts what
   the page shows. Exit code = number of failed cases. */
const { chromium } = require("playwright-core");

const BASE = (process.env.BASE_URL || "http://127.0.0.1:4105").replace(/\/$/, "");
const TIMEOUT = 30000;

// the shell marks <main data-mounted> once it has read the URL; before that the prerendered
// HTML shows the default view, so every read and click waits for it
const mounted = (page) => page.locator("main.rc-main[data-mounted]").waitFor({ state: "attached", timeout: TIMEOUT });
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
      await mounted(page);
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
    await mounted(page);
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

  // every view, by CLICKING: the nav item and the view's own state controls must change the
  // address bar (a goto-only test passes even when clicks never write the URL)
  const c2 = await browser.newContext();
  const pg = await c2.newPage();
  const urlIs = async (label, pred) => {
    try { await pg.waitForURL((u) => pred(u.searchParams, u), { timeout: TIMEOUT }); check(true, label, pg.url().replace(BASE, "")); }
    catch { check(false, label, `address bar ${pg.url().replace(BASE, "")}`); }
  };
  const nav = async (v) => {
    await pg.locator(`.rc-item[data-view='${v}']`).first().click();
    await urlIs(`click nav ${v} → URL view=${v}`, (p, u) => (v === "home" ? u.pathname === "/" && !p.get("view") : p.get("view") === v));
  };
  const chip = async (route, sel, i) => {
    await pg.locator(`[data-route='${route}'] ${sel}`).nth(i).click();
    await urlIs(`click ${route} sample ${i} → URL sample=${i}`, (p) => p.get("sample") === String(i));
  };
  try {
    await pg.goto(BASE + "/?view=toolbox", { waitUntil: "domcontentloaded" });  // not a view clicked first or next
    await mounted(pg);
    await nav("home");
    await nav("resolve");   await chip("resolve", ".rc-chip", 1);
    await nav("augment");   await chip("augment", ".rc-chip", 2);
    await nav("handoff");
    await nav("rules");
    await pg.locator("[data-route='rules'] [data-log='tool_calls']").first().click();
    await urlIs("click rules log → URL log=tool_calls", (p) => p.get("log") === "tool_calls");
    await nav("support");
    const t = pg.locator("[data-route='support'] .ev-queue button").nth(1);
    const id = ((await t.locator(".ev-qm").textContent({ timeout: TIMEOUT })) || "").split(" · ")[0].trim();
    await t.click();
    await urlIs(`click support ticket → URL ticket=${id}`, (p) => !!id && p.get("ticket") === id);
    await nav("agent");
    await nav("sales");     await chip("sales", ".chip", 1);
    const ss = pg.locator("[data-route='sales'] select").first();
    const cur = await ss.inputValue();
    const pickS = (await ss.locator("option").allTextContents()).find((o) => o !== cur);
    await ss.selectOption(pickS);
    await urlIs(`edit sales industry → URL industry=${pickS}, no sample`, (p) => p.get("industry") === pickS && !p.get("sample"));
    await nav("toolbox");
    await nav("company");
    await nav("company-data");
    await pg.locator("[data-route='company-data'] .chip").nth(2).click();
    await urlIs("click 360 sample Banking · Mid-market → URL industry=Banking&size=Mid-market", (p) =>
      p.get("industry") === "Banking" && p.get("size") === "Mid-market" && !p.get("plan"));
    await pg.locator("[data-route='company-data'] select").nth(2).selectOption("Pro");
    await urlIs("edit 360 plan → URL plan=Pro", (p) => p.get("plan") === "Pro" && p.get("industry") === "Banking");
    await nav("company-toolbox");
  } catch (e) {
    check(false, "clicking through every view", e.message.split("\n")[0]);
  }
  await c2.close();
  await browser.close();
  console.log(failed ? `\n${failed} failed` : "\nall deep links work");
  process.exit(failed);
}

main().catch((e) => { console.error(e); process.exit(99); });
