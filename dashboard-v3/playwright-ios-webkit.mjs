/**
 * Reproduce the user's iOS Safari issue by using WebKit (not Chromium).
 * Tries to tap each MobileTabs button and reports which ones actually switch.
 */
import { webkit, devices } from "@playwright/test";
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "fs";
import path from "path";

const OUT = "/tmp/ura-dashboard-v5-ios";
if (!existsSync(OUT)) mkdirSync(OUT, { recursive: true });

const HA_URL = "http://192.168.13.13:8123";
const TOKEN = JSON.parse(
  readFileSync("/Users/okosisi/Code/universal-room-automation/.mcp.json", "utf-8"),
).mcpServers["home-assistant"].env.HOMEASSISTANT_TOKEN;

const TABS = [
  "home", "house", "zones", "rooms", "energy",
  "hvac", "presence", "security", "safety", "diagnostics",
];

const browser = await webkit.launch();
const ctx = await browser.newContext({ ...devices["iPhone 13"] });

await ctx.addInitScript(({ token, haUrl }) => {
  localStorage.setItem("hassTokens", JSON.stringify({
    hassUrl: haUrl, clientId: null, refresh_token: "",
    access_token: token, expires_in: 31536000,
    expires: Date.now() + 31536000_000, token_type: "Bearer",
  }));
  localStorage.setItem("selectedLanguage", '"en"');
}, { token: TOKEN, haUrl: HA_URL });

const page = await ctx.newPage();
const consoleErrors = [];
const failed404 = [];
ctx.on("console", (m) => {
  if (m.type() === "error") consoleErrors.push(m.text());
});
ctx.on("response", (resp) => {
  if (resp.status() >= 400 && resp.url().includes("/universal_room_automation_panel_v3/")) {
    failed404.push({ url: resp.url(), status: resp.status() });
  }
});

await page.goto(HA_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
await page.waitForTimeout(3000);
await page.goto(`${HA_URL}/ura-dashboard-v3`, { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(8000);

let appFrame = null;
for (let i = 0; i < 30; i++) {
  appFrame = page.frames().find((f) => f.url().includes("/universal_room_automation_panel_v3/"));
  if (appFrame) break;
  await page.waitForTimeout(1000);
}
if (!appFrame) {
  console.error("No app frame found");
  process.exit(2);
}

// Wait for Home button to render
await appFrame.waitForFunction(
  () => Array.from(document.querySelectorAll("button"))
    .some((b) => /^Home$/i.test((b.textContent ?? "").trim())),
  { timeout: 15000 },
);
await appFrame.waitForTimeout(2000);

// Probe initial state
const initial = await appFrame.evaluate(() => ({
  body_classes: document.body.className,
  active_tab: document.body.dataset.activeTab,
  mobile_tabs_buttons: Array.from(document.querySelectorAll(".mobile-tabs button"))
    .map((b) => ({
      text: b.textContent?.trim(),
      classes: b.className,
      pointerEvents: window.getComputedStyle(b).pointerEvents,
      display: window.getComputedStyle(b).display,
    })),
  whole_house_power_value: document.querySelector('[class*="kW"]')?.parentElement?.textContent?.slice(0, 100) ?? null,
}));
console.log("=== INITIAL ===");
console.log(JSON.stringify(initial, null, 2));

const results = [];
for (const tab of TABS) {
  const tabLabel = tab.charAt(0).toUpperCase() + tab.slice(1);

  // Try tapping via REAL touchpoint (not synthetic click) — closer to what
  // iOS Safari does. Use page.tap if button is visible; else .mobile-tabs button.
  const result = await appFrame.evaluate(({ tabId, label }) => {
    const btns = Array.from(document.querySelectorAll(".mobile-tabs button"));
    let btn = btns.find((b) =>
      (b.textContent?.trim() ?? "").toLowerCase().startsWith(label.toLowerCase())
    );
    // Some labels are truncated ("Diag" not "Diagnostics") — fallback to id-ish match
    if (!btn && label === "Diagnostics") {
      btn = btns.find((b) => /^Diag$/i.test((b.textContent?.trim() ?? "")));
    }
    if (!btn) {
      // Fallback to rail-link (just in case mobile state didn't apply)
      btn = Array.from(document.querySelectorAll(".rail-link")).find((b) =>
        (b.textContent?.trim() ?? "").toLowerCase().startsWith(label.toLowerCase())
      );
    }
    if (!btn) return { found: false };

    const beforeActive = document.body.dataset.activeTab;
    // Simulate iOS Safari tap sequence: touchstart, touchend, click
    const rect = btn.getBoundingClientRect();
    const touchInit = {
      bubbles: true, cancelable: true,
      changedTouches: [new Touch({
        identifier: 0, target: btn,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
      })],
    };
    try {
      btn.dispatchEvent(new TouchEvent("touchstart", touchInit));
      btn.dispatchEvent(new TouchEvent("touchend", touchInit));
    } catch (e) {
      // older WebKit may not support TouchEvent constructor; fall back to click
    }
    btn.click();

    return new Promise((resolve) => {
      setTimeout(() => {
        const afterActive = document.body.dataset.activeTab;
        const sec = document.querySelector(`section[data-tab="${tabId}"]`);
        resolve({
          found: true,
          beforeActive,
          afterActive,
          switched: afterActive === tabId,
          sectionLen: sec?.textContent?.length ?? 0,
        });
      }, 1500);
    });
  }, { tabId: tab, label: tabLabel });

  await page.waitForTimeout(500);
  const shot = path.join(OUT, `tab-${tab}.png`);
  await page.screenshot({ path: shot, fullPage: false }).catch(() => {});
  results.push({ tab, ...result, shot });
  console.log(
    `  ${tab.padEnd(12)} found=${result.found} switched=${result.switched ?? "?"} ` +
    `active_before=${result.beforeActive ?? "?"} → after=${result.afterActive ?? "?"} ` +
    `chars=${result.sectionLen ?? 0}`
  );
}

writeFileSync(path.join(OUT, "summary.json"), JSON.stringify({
  initial, results, consoleErrors, failed404,
}, null, 2));

console.log("\n=== SUMMARY ===");
const switched = results.filter((r) => r.switched).length;
console.log(`Tabs that actually switched (active_tab updated): ${switched}/10`);
console.log(`Console errors: ${consoleErrors.length}`);
console.log(`404s in panel assets: ${failed404.length}`);
if (failed404.length) console.log(JSON.stringify(failed404, null, 2));

await browser.close();
