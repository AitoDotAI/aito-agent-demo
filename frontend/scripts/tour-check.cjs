#!/usr/bin/env node
// Drive the first-visit tour (components/shell/Tour.tsx) in Chrome against a served static export: screenshot each step at
// phone, sideways-phone and desktop sizes, and check what the card covers, how each way out ends it, the stored flags and the events.
// No backend is needed: the /api calls fail and the shell still renders; /api/support/status is stubbed where a check needs it.
//
//   ./do tour-check                      builds nothing: serves frontend/out/ (run ./do build first) and runs this
//   node frontend/scripts/tour-check.cjs <base-url> <out-dir>
//
// CHROME_PATH picks the browser; without it playwright-core uses its own downloaded Chromium, if there is one. Exits 1 on any failed check.
const { chromium } = require("playwright-core");
const fs = require("fs");
const [BASE, OUT] = [process.argv[2] || "http://127.0.0.1:4197", process.argv[3] || require("path").resolve(__dirname, "output/tour")];
fs.mkdirSync(OUT, { recursive: true });
const results = [];
const check = (name, ok, extra = "") => { results.push(`${ok ? "PASS" : "FAIL"} ${name}${extra ? " :: " + extra : ""}`); };

const overlap = (a, b) => a && b && a.width > 0 && b.width > 0 &&
  a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
const rect = (page, sel) => page.evaluate((s) => {
  const el = document.querySelector(s); if (!el) return null;
  const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
  if (cs.display === "none" || cs.visibility === "hidden") return null;
  return { x: r.x, y: r.y, width: r.width, height: r.height };
}, sel);
const onScreen = (r, vw) => r && r.x >= -1 && r.x + r.width <= vw + 1;

async function ctx(browser, viewport, touch, init = {}) {
  const c = await browser.newContext({ viewport, isMobile: touch, hasTouch: touch, deviceScaleFactor: 2 });
  await c.addInitScript((seed) => {
    window.__ev = [];
    window.gtag = (...a) => window.__ev.push(a);
    for (const [k, v] of Object.entries(seed)) localStorage.setItem(k, v);
  }, init);
  return c;
}
const events = (page) => page.evaluate(() => window.__ev.filter((a) => a[0] === "event").map((a) => [a[1], a[2]]));
const card = (page) => page.waitForSelector(".tour-card", { timeout: 5000 });

async function walk(browser, name, viewport, touch, path) {
  const c = await ctx(browser, viewport, touch);
  const page = await c.newPage();
  await page.goto(BASE + path);
  await card(page);
  await page.waitForTimeout(400);
  const vw = viewport.width;
  for (let i = 1; i <= 3; i++) {
    await page.waitForTimeout(450);   // the drawer's slide
    await page.screenshot({ path: `${OUT}/${name}-step${i}.png` });
    const t = await rect(page, ".tour-card");
    const side = await rect(page, ".rc-side");
    const fab = await rect(page, ".rc-panel-fab");
    const toggle = await rect(page, ".rc-panel-toggle");
    const title = await page.textContent(".tour-title");
    check(`${name} step ${i} card on screen`, onScreen(t, vw) && t.y + t.height <= viewport.height + 1, JSON.stringify(t));
    if (onScreen(side, vw)) check(`${name} step ${i} card clear of the menu`, !overlap(t, side), title);
    if (fab) check(`${name} step ${i} card clear of the Aito button`, !overlap(t, fab));
    if (toggle) check(`${name} step ${i} card clear of the panel tab`, !overlap(t, toggle));
    if (i === 2 && vw <= 760) check(`${name} step 2 opened the drawer`, await page.evaluate(() => document.querySelector(".rc-app").classList.contains("nav-open")));
    if (i === 2) check(`${name} step 2 says ${touch ? "Tap" : "Click"}`, (await page.textContent(".tour-text")).includes(touch ? "Tap" : "Click"));
    if (i === 1 && path !== "/") check(`${name} deep link names the view`, /You are on/.test(title), title);
    if (i < 3) await page.click(".tour-next"); else await page.click(".tour-next");
  }
  check(`${name} tour gone after Done`, (await page.$(".tour-card")) === null);
  if (vw <= 760) check(`${name} drawer closed after the tour`, !(await page.evaluate(() => document.querySelector(".rc-app").classList.contains("nav-open"))));
  const ev = await events(page);
  check(`${name} events`, ev.some((e) => e[0] === "tour_started" && e[1].auto === true) && ev.some((e) => e[0] === "tour_completed")
    && ev.filter((e) => e[0].startsWith("tour_")).every((e) => e[1].device && e[1].surface === "agent-demo"), JSON.stringify(ev.filter((e) => e[0].startsWith("tour_")).map((e) => [e[0], e[1].device, e[1].reason ?? ""])));
  await page.reload();
  await page.waitForTimeout(1800);
  check(`${name} not shown again on reload`, (await page.$(".tour-card")) === null);
  await c.close();
}

async function behaviours(browser) {
  const phone = { width: 375, height: 812 };
  // a tap on a view in the drawer ends the tour as chose_a_view
  let c = await ctx(browser, phone, true); let page = await c.newPage();
  await page.goto(BASE + "/sales/"); await card(page); await page.click(".tour-next"); await page.waitForTimeout(500);
  await page.click('.rc-side .rc-item[data-view="company"]'); await page.waitForTimeout(300);
  let ev = await events(page);
  check("tap on a view ends the tour (chose_a_view)", (await page.$(".tour-card")) === null &&
    ev.some((e) => e[0] === "tour_skipped" && e[1].reason === "chose_a_view" && e[1].at_step === 2) && !ev.some((e) => e[0] === "tour_step" && e[1].step === 3),
    JSON.stringify(ev.filter((e) => e[0].startsWith("tour_")).map((e) => [e[0], e[1].reason ?? e[1].step ?? ""])));
  await c.close();
  // the backdrop closing the drawer moves on to step 3
  c = await ctx(browser, phone, true); page = await c.newPage();
  await page.goto(BASE + "/sales/"); await card(page); await page.click(".tour-next"); await page.waitForTimeout(500);
  await page.mouse.click(360, 400); await page.waitForTimeout(400);
  check("backdrop closes the drawer and moves to step 3", (await page.textContent(".tour-count"))?.startsWith("3 of 3"));
  // Escape ends it
  await page.keyboard.press("Escape"); await page.waitForTimeout(200);
  ev = await events(page);
  check("Escape ends the tour", (await page.$(".tour-card")) === null && ev.some((e) => e[0] === "tour_skipped" && e[1].reason === "escape"));
  // Take the tour starts it again
  await page.click(".rc-burger"); await page.waitForTimeout(400);
  await page.click(".tour-link"); await page.waitForTimeout(400);
  check("Take the tour starts it again", (await page.$(".tour-card")) !== null);
  ev = await events(page);
  check("Take the tour is not auto", ev.some((e) => e[0] === "tour_started" && e[1].auto === false));
  await c.close();
  // ?demo= leaves the first visit alone
  c = await ctx(browser, phone, true); page = await c.newPage();
  await page.goto(BASE + "/sales/?demo=1"); await page.waitForTimeout(1800);
  check("?demo= does not start the tour", (await page.$(".tour-card")) === null);
  check("?demo= does not use up the first visit", (await page.evaluate(() => localStorage.getItem("agent.tourSeen"))) === null);
  await c.close();
  // going to another view (the overview's button) ends it
  c = await ctx(browser, { width: 1440, height: 900 }, false); page = await c.newPage();
  await page.goto(BASE + "/"); await card(page);
  await page.click(".hbtns .btn.p"); await page.waitForTimeout(300);
  ev = await events(page);
  check("another view ends the tour (left_the_view)", (await page.$(".tour-card")) === null && ev.some((e) => e[0] === "tour_skipped" && e[1].reason === "left_the_view"));
  await c.close();
  // desktop with the Aito panel collapsed: step 3 shows it without saving, and it is collapsed again after
  c = await ctx(browser, { width: 1440, height: 900 }, false, { rcPanelCollapsed: "1" }); page = await c.newPage();
  await page.goto(BASE + "/company/"); await card(page);
  const collapsed = () => page.evaluate(() => document.querySelector(".rc-app").classList.contains("panel-collapsed"));
  check("desktop: panel starts collapsed (visitor's preference)", await collapsed());
  await page.click(".tour-next"); await page.waitForTimeout(300); await page.click(".tour-next"); await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT}/desktop-collapsed-step3.png` });
  check("desktop: step 3 shows the panel", !(await collapsed()));
  check("desktop: step 3 did not write the preference", (await page.evaluate(() => localStorage.getItem("rcPanelCollapsed"))) === "1");
  await page.click(".tour-next"); await page.waitForTimeout(300);
  check("desktop: panel collapsed again after the tour", await collapsed());
  check("desktop: preference still collapsed", (await page.evaluate(() => localStorage.getItem("rcPanelCollapsed"))) === "1");
  await c.close();
  // a visitor who hides the panel during step 3 keeps it hidden, and it stays saved as they chose
  c = await ctx(browser, { width: 1440, height: 900 }, false, { rcPanelCollapsed: "1" }); page = await c.newPage();
  await page.goto(BASE + "/company/"); await card(page);
  await page.click(".tour-next"); await page.waitForTimeout(300); await page.click(".tour-next"); await page.waitForTimeout(400);
  await page.click(".rc-panel-toggle"); await page.waitForTimeout(200);   // visitor hides it
  await page.click(".tour-next"); await page.waitForTimeout(300);
  check("desktop: visitor's own hide is kept", await collapsed());
  await c.close();
  // a visitor who hides and then re-shows the panel during step 3 keeps it shown, as they saved it ("0")
  c = await ctx(browser, { width: 1440, height: 900 }, false, { rcPanelCollapsed: "1" }); page = await c.newPage();
  await page.goto(BASE + "/company/"); await card(page);
  await page.click(".tour-next"); await page.waitForTimeout(300); await page.click(".tour-next"); await page.waitForTimeout(400);
  await page.click(".rc-panel-toggle"); await page.waitForTimeout(200); await page.click(".rc-panel-toggle"); await page.waitForTimeout(200);
  await page.click(".tour-next"); await page.waitForTimeout(300);
  check("desktop: visitor's hide-then-show is kept", !(await collapsed()) && (await page.evaluate(() => localStorage.getItem("rcPanelCollapsed"))) === "0");
  await c.close();
  // the support view joins the menu when its data answers, after the tour has started: the count follows the menu
  c = await ctx(browser, phone, true); page = await c.newPage();
  await c.route("**/api/support/status", async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.fulfill({ json: { loaded: true } }); });
  await page.goto(BASE + "/sales/"); await card(page);
  const before = await page.textContent(".tour-text");
  await page.waitForTimeout(2500);
  const after = await page.textContent(".tour-text");
  const items = await page.evaluate(() => document.querySelectorAll(".rc-side .rc-item").length);
  check("view count follows the menu when the support view arrives late", /one of 11 views/.test(before) && after.includes(`one of ${items} views`) && items === 12, `${before} -> ${after} (menu ${items})`);
  await c.close();
  // no storage at all: no auto start, and the page still works
  c = await browser.newContext({ viewport: phone, isMobile: true, hasTouch: true });
  await c.addInitScript(() => { Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } }); });
  page = await c.newPage(); const errs = []; page.on("pageerror", (e) => errs.push(String(e)));
  await page.goto(BASE + "/sales/"); await page.waitForTimeout(1800);
  check("blocked storage: no auto start, no page error", (await page.$(".tour-card")) === null && errs.length === 0, errs.join(" | "));
  await c.close();
}

(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH, headless: true });
  await walk(browser, "phone-375", { width: 375, height: 812 }, true, "/sales/");
  await walk(browser, "landscape-844x390", { width: 844, height: 390 }, true, "/sales/");
  await walk(browser, "phone-landscape-667x375", { width: 667, height: 375 }, true, "/company/");
  await walk(browser, "desktop-1440", { width: 1440, height: 900 }, false, "/");
  await behaviours(browser);
  await browser.close();
  console.log(results.join("\n"));
  const failed = results.filter((r) => r.startsWith("FAIL")).length;
  console.log(`${failed} failed of ${results.length}; screenshots in ${OUT}`);
  process.exit(failed ? 1 : 0);
})();
