/**
 * v5.0 D1 visual diff helper.
 *
 * Takes two screenshots:
 *   1. The React dev server (Vite) rendering our new shell with placeholder tabs
 *   2. The P6 prototype HTML file (file:// URL)
 *
 * Saves PNGs to /tmp/ura-dashboard-v5/ for visual comparison.
 *
 * Run: node playwright-shot.mjs [--mobile]
 */
import { chromium } from '@playwright/test';
import { mkdirSync, existsSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const OUT_DIR = '/tmp/ura-dashboard-v5';
if (!existsSync(OUT_DIR)) mkdirSync(OUT_DIR, { recursive: true });

// Vite is configured with base="/universal_room_automation_panel/" so the
// dev server only serves the app under that path. The root issues a 302.
const DEV_URL = 'http://localhost:5173/universal_room_automation_panel/';
const P6_URL = `file://${path.resolve(__dirname, '../docs/dashboard-prototypes/v4/p6-light-styled.html')}`;

const isMobile = process.argv.includes('--mobile');
const viewport = isMobile
  ? { width: 480, height: 900 }
  : { width: 1400, height: 900 };
const suffix = isMobile ? 'mobile' : 'desktop';

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport, deviceScaleFactor: 2 });

// React dev server — capture each tab
const tabs = ['home', 'house', 'zones', 'rooms', 'energy', 'hvac',
               'presence', 'security', 'safety', 'diagnostics'];
const onlyTab = process.argv.find(a => a.startsWith('--tab='))?.slice(6);
const tabsToShoot = onlyTab ? [onlyTab] : tabs;
for (const tab of tabsToShoot) {
  const reactPage = await ctx.newPage();
  try {
    await reactPage.goto(DEV_URL, { waitUntil: 'networkidle', timeout: 15000 });
    if (tab !== 'home') {
      // Click rail item to switch tabs
      const selector = `[aria-current="page"], button:has(span:text("${tab.charAt(0).toUpperCase() + tab.slice(1)}"))`;
      await reactPage.click(`.rail button:has-text("${tab.charAt(0).toUpperCase() + tab.slice(1)}")`).catch(() => {});
      await reactPage.waitForTimeout(300);
    } else {
      await reactPage.waitForTimeout(500);
    }
    const reactPath = path.join(OUT_DIR, `react-${tab}-${suffix}.png`);
    await reactPage.screenshot({ path: reactPath, fullPage: true });
    console.log(`React ${tab}: ${reactPath}`);
  } catch (e) {
    console.error(`React ${tab} shot failed:`, e.message);
  } finally {
    await reactPage.close();
  }
}

// P6 reference — also capture each tab
for (const tab of tabsToShoot) {
  const p6Page = await ctx.newPage();
  try {
    await p6Page.goto(P6_URL, { waitUntil: 'networkidle', timeout: 10000 });
    await p6Page.addStyleTag({ content: '.viewport-toggle { display: none !important; }' });
    if (tab !== 'home') {
      await p6Page.click(`.rail button[data-tab-target="${tab}"]`).catch(() => {});
      await p6Page.waitForTimeout(200);
    }
    const p6Path = path.join(OUT_DIR, `p6-${tab}-${suffix}.png`);
    await p6Page.screenshot({ path: p6Path, fullPage: true });
    console.log(`P6 ${tab}: ${p6Path}`);
  } catch (e) {
    console.error(`P6 ${tab} shot failed:`, e.message);
  } finally {
    await p6Page.close();
  }
}

await browser.close();
console.log(`Done. Compare ${OUT_DIR}/react-${suffix}.png vs ${OUT_DIR}/p6-${suffix}.png`);
