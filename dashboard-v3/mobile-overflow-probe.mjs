/**
 * Find the widest element overflowing the mobile viewport.
 */
import { chromium, devices } from "@playwright/test";
import { readFileSync } from "fs";

const HA_URL = "http://192.168.13.13:8123";
const TOKEN = JSON.parse(
  readFileSync("/Users/okosisi/Code/universal-room-automation/.mcp.json", "utf-8"),
).mcpServers["home-assistant"].env.HOMEASSISTANT_TOKEN;

const browser = await chromium.launch();
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

// Wait for tabs button hydration
await appFrame.waitForFunction(
  () => Array.from(document.querySelectorAll("button")).some((b) => /^Home$/i.test((b.textContent ?? "").trim())),
  { timeout: 15000 },
);
await appFrame.waitForTimeout(2000);

const result = await appFrame.evaluate(() => {
  const viewport = window.innerWidth;
  const overflowing = [];
  const all = document.querySelectorAll("*");
  for (const el of all) {
    const r = el.getBoundingClientRect();
    // Element extends beyond the viewport right edge
    if (r.right > viewport + 2 && r.width > 0) {
      const path = [];
      let cur = el;
      while (cur && cur !== document.body && path.length < 5) {
        const cls = (cur.className || "").toString().slice(0, 40);
        path.unshift(`${cur.tagName.toLowerCase()}${cls ? `.${cls.replace(/\s+/g, ".")}` : ""}`);
        cur = cur.parentElement;
      }
      overflowing.push({
        path: path.join(" > "),
        left: Math.round(r.left),
        right: Math.round(r.right),
        width: Math.round(r.width),
        text: (el.textContent ?? "").slice(0, 40).replace(/\s+/g, " "),
      });
    }
  }
  // Sort by rightmost edge desc, take top 15
  overflowing.sort((a, b) => b.right - a.right);
  return {
    viewport,
    overflow_count: overflowing.length,
    body_class: document.body.className,
    activeTab: document.body.dataset.activeTab,
    worst: overflowing.slice(0, 15),
  };
});

console.log(JSON.stringify(result, null, 2));
await browser.close();
