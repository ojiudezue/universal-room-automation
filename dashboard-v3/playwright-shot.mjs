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

// React dev server
const reactPage = await ctx.newPage();
try {
  await reactPage.goto(DEV_URL, { waitUntil: 'networkidle', timeout: 15000 });
  await reactPage.waitForTimeout(500); // settle
  const reactPath = path.join(OUT_DIR, `react-${suffix}.png`);
  await reactPage.screenshot({ path: reactPath, fullPage: false });
  console.log(`React shot: ${reactPath}`);
} catch (e) {
  console.error('React shot failed:', e.message);
}

// P6 reference
const p6Page = await ctx.newPage();
try {
  await p6Page.goto(P6_URL, { waitUntil: 'networkidle', timeout: 10000 });
  // Hide the prototype-only viewport toggle for fair comparison
  await p6Page.addStyleTag({ content: '.viewport-toggle { display: none !important; }' });
  await p6Page.waitForTimeout(300);
  const p6Path = path.join(OUT_DIR, `p6-${suffix}.png`);
  await p6Page.screenshot({ path: p6Path, fullPage: false });
  console.log(`P6 shot: ${p6Path}`);
} catch (e) {
  console.error('P6 shot failed:', e.message);
}

await browser.close();
console.log(`Done. Compare ${OUT_DIR}/react-${suffix}.png vs ${OUT_DIR}/p6-${suffix}.png`);
