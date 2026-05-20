/**
 * Mobile viewport check — cycles all 10 tabs at iPhone-ish width.
 *
 * Captures per-tab screenshots, body.mobile class state, scroll-width
 * overflow, viewport-meta, and the MobileTabs strip presence.
 */
import { chromium, devices } from "@playwright/test";
import { mkdirSync, existsSync, writeFileSync, readFileSync } from "fs";
import path from "path";

const OUT_DIR = "/tmp/ura-dashboard-v5-mobile";
if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

const HA_URL = "http://192.168.13.13:8123";
const TOKEN = JSON.parse(
  readFileSync(
    "/Users/okosisi/Code/universal-room-automation/.mcp.json",
    "utf-8",
  ),
).mcpServers["home-assistant"].env.HOMEASSISTANT_TOKEN;

const TABS = [
  "home", "house", "zones", "rooms", "energy",
  "hvac", "presence", "security", "safety", "diagnostics",
];

const browser = await chromium.launch();
// iPhone 13 viewport-ish — typical phone size that body.mobile should fire on
const ctx = await browser.newContext({
  ...devices["iPhone 13"],
});

await ctx.addInitScript(({ token, haUrl }) => {
  localStorage.setItem("hassTokens", JSON.stringify({
    hassUrl: haUrl,
    clientId: null,
    refresh_token: "",
    access_token: token,
    expires_in: 31536000,
    expires: Date.now() + 31536000_000,
    token_type: "Bearer",
  }));
  localStorage.setItem("selectedLanguage", '"en"');
}, { token: TOKEN, haUrl: HA_URL });

const page = await ctx.newPage();
const consoleErrors = [];
ctx.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

await page.goto(HA_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForTimeout(3000);
await page.goto(`${HA_URL}/ura-dashboard-v3`, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(5000);

// Locate iframe
let appFrame = null;
for (let i = 0; i < 30; i++) {
  appFrame = page.frames().find((f) => f.url().includes("/universal_room_automation_panel_v3/"));
  if (appFrame) break;
  await page.waitForTimeout(1000);
}
if (!appFrame) {
  console.error("No app frame after 30s");
  process.exit(2);
}

// Wait for Rail/MobileTabs to render. At mobile viewport, MobileTabs is the
// visible strip; .rail-link buttons still exist but display:none.
try {
  await appFrame.waitForFunction(
    () => Array.from(document.querySelectorAll("button"))
      .some((b) => /^Home$/i.test((b.textContent ?? "").trim())),
    { timeout: 15000 },
  );
  await appFrame.waitForTimeout(2000);
} catch (e) {
  console.warn("Hydration wait timed out:", e.message);
}

// Probe mobile state
const mobileState = await appFrame.evaluate(() => {
  const body = document.body;
  const rail = document.querySelector(".rail");
  const mobileTabs = document.querySelector(".mobile-tabs");
  const railStyle = rail ? window.getComputedStyle(rail) : null;
  const mobileTabsStyle = mobileTabs ? window.getComputedStyle(mobileTabs) : null;
  return {
    body_classes: body.className,
    has_mobile_class: body.classList.contains("mobile"),
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    rail_present: !!rail,
    rail_display: railStyle?.display ?? null,
    mobile_tabs_present: !!mobileTabs,
    mobile_tabs_display: mobileTabsStyle?.display ?? null,
    scroll_width: document.documentElement.scrollWidth,
    viewport_meta: document.querySelector('meta[name="viewport"]')?.getAttribute("content") ?? "(missing)",
  };
});

console.log("=== MOBILE STATE ===");
console.log(JSON.stringify(mobileState, null, 2));

// Take Home screenshot
await page.screenshot({ path: path.join(OUT_DIR, "tab-home.png"), fullPage: true });
console.log(`Home screenshot: ${OUT_DIR}/tab-home.png`);

// Cycle through all tabs via MobileTabs first, fallback to any matching button
const results = [];
for (const tab of TABS) {
  const tabLabel = tab.charAt(0).toUpperCase() + tab.slice(1);
  try {
    const result = await appFrame.evaluate(({ tabId, label }) => {
      const all = Array.from(document.querySelectorAll("button"));
      // Prefer MobileTabs button
      let btn = all.find((b) =>
        b.classList.contains("mobile-tab") &&
        (b.textContent?.trim() ?? "").toLowerCase().startsWith(label.toLowerCase())
      );
      if (!btn) {
        btn = all.find((b) =>
          (b.textContent?.trim() ?? "").toLowerCase() === label.toLowerCase()
        );
      }
      if (!btn) return { clicked: false, reason: "no button" };
      // scrollIntoView in case the mobile-tabs strip is horizontally scrolled
      btn.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
      btn.click();
      return new Promise((resolve) => {
        let elapsed = 0;
        const step = 200;
        function check() {
          const sec = document.querySelector(`section[data-tab="${tabId}"]`);
          if ((sec && (sec.textContent?.length ?? 0) > 20) || elapsed >= 5000) {
            const scrollWidth = document.documentElement.scrollWidth;
            const innerWidth = window.innerWidth;
            resolve({
              clicked: true,
              sectionLen: sec?.textContent?.length ?? 0,
              scrollWidth,
              innerWidth,
              overflowsViewport: scrollWidth > innerWidth + 2,
            });
          } else {
            elapsed += step;
            setTimeout(check, step);
          }
        }
        check();
      });
    }, { tabId: tab, label: tabLabel });

    await page.waitForTimeout(500);
    const shotPath = path.join(OUT_DIR, `tab-${tab}.png`);
    await page.screenshot({ path: shotPath, fullPage: true });
    results.push({ tab, ...result, shot: shotPath });
    console.log(
      `  ${tab.padEnd(12)} clicked=${result.clicked} chars=${result.sectionLen ?? 0} ` +
      `scroll=${result.scrollWidth ?? "?"}/${result.innerWidth ?? "?"} ` +
      `overflow=${result.overflowsViewport ?? false}`
    );
  } catch (e) {
    results.push({ tab, error: e.message });
    console.error(`  ${tab}: ${e.message}`);
  }
}

writeFileSync(
  path.join(OUT_DIR, "summary.json"),
  JSON.stringify({ mobileState, tabs: results, consoleErrors }, null, 2),
);
await browser.close();

console.log("\n=== SUMMARY ===");
const overflowing = results.filter((r) => r.overflowsViewport);
console.log(`Tabs overflowing viewport: ${overflowing.length} (${overflowing.map((r) => r.tab).join(", ") || "none"})`);
console.log(`URA console errors: ${consoleErrors.length}`);
console.log(`Full report: ${OUT_DIR}/summary.json`);
