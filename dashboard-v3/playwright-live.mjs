/**
 * Post-deploy live validation of the v5.0 dashboard against HA.
 *
 * Authenticates by injecting the long-lived access token into HA's
 * `hassTokens` localStorage shape, then navigates the side panel
 * URL and cycles through all 10 tabs, capturing:
 *   - Page screenshot per tab
 *   - Console errors / warnings
 *   - Failed network requests
 *   - First-paint timings via Performance API
 *
 * Run: node playwright-live.mjs
 *
 * Writes results to /tmp/ura-dashboard-v5-live/.
 */
import { chromium } from "@playwright/test";
import { mkdirSync, existsSync, writeFileSync, readFileSync } from "fs";
import path from "path";

const OUT_DIR = "/tmp/ura-dashboard-v5-live";
if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

const HA_URL = "http://192.168.13.13:8123";
const PANEL_PATH = "/universal_room_automation_panel_v3";
const MCP_PATH = "/Users/okosisi/Code/universal-room-automation/.mcp.json";
const TOKEN = JSON.parse(readFileSync(MCP_PATH, "utf-8"))
  .mcpServers["home-assistant"].env.HOMEASSISTANT_TOKEN;

const TABS = [
  "home",
  "house",
  "zones",
  "rooms",
  "energy",
  "hvac",
  "presence",
  "security",
  "safety",
  "diagnostics",
];

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1400, height: 900 },
  deviceScaleFactor: 1,
});

// Capture console + network across all pages
const consoleLog = [];
const networkFail = [];

ctx.on("console", (msg) => {
  const t = msg.type();
  if (t === "error" || t === "warning") {
    consoleLog.push({ type: t, text: msg.text(), location: msg.location() });
  }
});
ctx.on("requestfailed", (req) => {
  networkFail.push({ url: req.url(), failure: req.failure()?.errorText });
});

// Auth: inject hassTokens into localStorage before any page nav.
// HA's frontend reads this on bootstrap; long-lived token works for the
// access_token field because HA accepts Bearer auth on /api/* and the
// frontend's WS handshake.
const NOW = Date.now();
const hassTokens = {
  hassUrl: HA_URL,
  clientId: null,
  refresh_token: "",
  access_token: TOKEN,
  expires_in: 31536000, // 1 year
  expires: NOW + 31536000_000,
  token_type: "Bearer",
};

await ctx.addInitScript(({ tokens, haUrl }) => {
  localStorage.setItem("hassTokens", JSON.stringify(tokens));
  // Set selected language to avoid downloading non-en locale on first paint
  localStorage.setItem("selectedLanguage", '"en"');
  // hakit's expected discovered URL (some versions of hakit cache this)
  window.__HA_URL__ = haUrl;
}, { tokens: hassTokens, haUrl: HA_URL });

console.log(`[${new Date().toISOString()}] Bootstrapping HA frontend...`);

const page = await ctx.newPage();
const results = [];

// Step 1: hit HA root to bootstrap the frontend with the injected token
try {
  await page.goto(HA_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(3000); // let HA-frontend init
  const url = page.url();
  console.log(`After bootstrap: ${url}`);
  if (url.includes("/auth/authorize") || url.includes("/onboarding")) {
    console.error(`AUTH FAILED — landed on ${url}. Long-lived token may not be accepted by the frontend bootstrap.`);
    await page.screenshot({ path: path.join(OUT_DIR, "auth-fail.png"), fullPage: true });
    console.log(`Screenshot saved to ${OUT_DIR}/auth-fail.png`);
    await browser.close();
    process.exit(2);
  }
} catch (e) {
  console.error("HA root nav failed:", e.message);
  await browser.close();
  process.exit(3);
}

// Step 2: navigate to the URA panel
console.log(`[${new Date().toISOString()}] Navigating to panel...`);
try {
  // The panel is registered as panel_custom; HA renders it at /<panel_url_path>
  // The exact side-panel URL depends on how URA registers it.
  // Try both common URLs:
  // panel_custom registers the side-panel route at `frontend_url_path`.
  // For URA Dashboard v3 this is "ura-dashboard-v3" (see __init__.py:2242).
  const PANEL_URLS = [
    `${HA_URL}/ura-dashboard-v3`,
  ];
  let panelLoaded = false;
  for (const url of PANEL_URLS) {
    try {
      await page.goto(url, { waitUntil: "networkidle", timeout: 20000 });
      const title = await page.title();
      // HA wraps panels in shadow DOM; body.textContent returns 0 chars but
      // the URA Dashboard title is set on the document. Title match is the
      // reliable signal.
      if (title.toLowerCase().includes("ura")) {
        console.log(`Panel loaded at: ${url} (title: "${title}")`);
        panelLoaded = true;
        break;
      } else {
        console.log(`Tried ${url} → title="${title}", no URA match`);
      }
    } catch (e) {
      console.log(`Tried ${url} → error: ${e.message}`);
    }
  }
  if (!panelLoaded) {
    console.error("Could not find the URA dashboard panel.");
    await page.screenshot({ path: path.join(OUT_DIR, "panel-not-found.png"), fullPage: true });
    await browser.close();
    process.exit(4);
  }
} catch (e) {
  console.error("Panel nav failed:", e.message);
  await browser.close();
  process.exit(5);
}

// Step 3: locate the dashboard iframe + wait for React to mount.
// panel_custom hosts our panel as an iframe at
// /universal_room_automation_panel_v3/index.html even when embed_iframe=False
// is passed to async_register_panel. We need that frame's context.
console.log(`[${new Date().toISOString()}] Locating dashboard iframe + waiting for mount...`);
let appFrame = null;
for (let attempt = 0; attempt < 30; attempt++) {
  appFrame = page
    .frames()
    .find((f) => f.url().includes("/universal_room_automation_panel_v3/"));
  if (appFrame) break;
  await page.waitForTimeout(1000);
}
if (!appFrame) {
  console.error("Could not find dashboard iframe after 30s.");
  await browser.close();
  process.exit(6);
}
console.log(`Dashboard iframe at: ${appFrame.url()}`);

// Wait for the Rail to render — Home button must be present in the frame.
try {
  await appFrame.waitForFunction(
    () => {
      const btns = document.querySelectorAll("button");
      for (const b of btns) {
        const txt = b.textContent?.trim() ?? "";
        if (/^Home$/i.test(txt)) return true;
      }
      return false;
    },
    { timeout: 15000 },
  );
  await appFrame.waitForTimeout(2000); // useEntity subscriptions settle
  console.log("App hydrated; Home tab button visible.");
} catch (e) {
  console.warn("Hydration wait timed out — proceeding anyway:", e.message);
}

// Step 4: capture first-paint perf metrics FROM THE DASHBOARD IFRAME.
const perfMetrics = await appFrame.evaluate(() => {
  const nav = performance.getEntriesByType("navigation")[0];
  const paints = performance.getEntriesByType("paint");
  const fcp = paints.find((p) => p.name === "first-contentful-paint")?.startTime;
  const resources = performance.getEntriesByType("resource");
  const totalBytes = resources.reduce((s, r) => s + (r.transferSize || 0), 0);
  return {
    domContentLoaded: nav?.domContentLoadedEventEnd,
    loadEvent: nav?.loadEventEnd,
    firstContentfulPaint: fcp,
    totalTransferKB: Math.round(totalBytes / 1024),
    resourceCount: resources.length,
  };
});

// Step 5: cycle through each tab via shadow-DOM-piercing click + read.
console.log(`[${new Date().toISOString()}] Cycling through ${TABS.length} tabs...`);

// Tab click + read — runs inside the dashboard iframe context. The Rail has
// multiple buttons with the same label (rail + mobile-tabs). We use the
// rail (.rail-link) variant since both fire the same onChange handler.
async function clickTabAndRead(frame, tabId, label) {
  return await frame.evaluate(
    ({ tabId, label }) => {
      // Prefer .rail-link button (Rail.tsx) — falls back to any matching label.
      const allBtns = Array.from(document.querySelectorAll("button"));
      let btn = allBtns.find(
        (b) =>
          b.classList.contains("rail-link") &&
          (b.textContent?.trim() ?? "")
            .replace(/\s+/g, " ")
            .toLowerCase()
            .startsWith(label.toLowerCase()),
      );
      if (!btn) {
        btn = allBtns.find(
          (b) =>
            (b.textContent?.trim() ?? "").toLowerCase() ===
            label.toLowerCase(),
        );
      }
      if (!btn) return { clicked: false, sectionLen: 0, reason: "no button" };
      btn.click();
      return new Promise((resolve) => {
        // Wait for React.lazy chunk to load + section[data-tab=X] to render.
        let elapsed = 0;
        const step = 200;
        function check() {
          const sec = document.querySelector(`section[data-tab="${tabId}"]`);
          if ((sec && (sec.textContent?.length ?? 0) > 20) || elapsed >= 5000) {
            resolve({
              clicked: true,
              sectionLen: sec?.textContent?.length ?? 0,
              snippet: sec?.textContent?.slice(0, 80) ?? null,
            });
          } else {
            elapsed += step;
            setTimeout(check, step);
          }
        }
        check();
      });
    },
    { tabId, label },
  );
}

for (const tab of TABS) {
  const tabLabel = tab.charAt(0).toUpperCase() + tab.slice(1);
  try {
    const result = await clickTabAndRead(appFrame, tab, tabLabel);
    await page.waitForTimeout(800); // let any tail re-renders settle

    const shotPath = path.join(OUT_DIR, `tab-${tab}.png`);
    await page.screenshot({ path: shotPath, fullPage: true });

    results.push({
      tab,
      status: result.clicked && result.sectionLen > 50 ? "ok" : "weak",
      rendered_chars: result.sectionLen,
      reason: result.reason,
      shot: shotPath,
    });
    console.log(
      `  ${tab}: clicked=${result.clicked}, ${result.sectionLen} chars rendered → ${shotPath}`,
    );
  } catch (e) {
    results.push({ tab, status: "fail", error: e.message });
    console.error(`  ${tab}: FAIL — ${e.message}`);
    await page
      .screenshot({ path: path.join(OUT_DIR, `tab-${tab}-FAIL.png`), fullPage: true })
      .catch(() => {});
  }
}

await browser.close();

// Step 6: write summary
const summary = {
  generated_at: new Date().toISOString(),
  ha_url: HA_URL,
  tabs_count: TABS.length,
  perf: perfMetrics,
  console_errors: consoleLog.filter((c) => c.type === "error"),
  console_warnings: consoleLog.filter((c) => c.type === "warning"),
  network_failures: networkFail,
  tabs: results,
};
writeFileSync(path.join(OUT_DIR, "summary.json"), JSON.stringify(summary, null, 2));

console.log("\n=== SUMMARY ===");
console.log(`Perf: FCP=${perfMetrics.firstContentfulPaint?.toFixed(0)}ms, DCL=${perfMetrics.domContentLoaded?.toFixed(0)}ms, total=${perfMetrics.totalTransferKB}KB, resources=${perfMetrics.resourceCount}`);
console.log(`Console errors: ${summary.console_errors.length}`);
console.log(`Console warnings: ${summary.console_warnings.length}`);
console.log(`Network failures: ${summary.network_failures.length}`);
console.log(`Tabs ok: ${results.filter((r) => r.status === "ok").length} / ${TABS.length}`);
const failed = results.filter((r) => r.status !== "ok");
if (failed.length) {
  console.log(`Tabs FAILED: ${failed.map((r) => r.tab).join(", ")}`);
}
console.log(`Full report: ${OUT_DIR}/summary.json`);
console.log(`Screenshots: ${OUT_DIR}/tab-*.png`);
