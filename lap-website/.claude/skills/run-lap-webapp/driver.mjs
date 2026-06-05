// Driver for the LAP V2 webapp (lap_web/lap-website) — drives an authed
// /app/* page past the client-side AuthGuard and screenshots it, with the
// entire backend mocked at the network layer (nothing touches production).
//
// Prereq: a dev server must be running with a SAME-ORIGIN API base, e.g.
//   $env:NEXT_PUBLIC_API_URL="http://localhost:4123"; node_modules\.bin\next.cmd dev -p 4123
//
// Usage (run from lap-website/ so `import 'playwright'` resolves):
//   node .claude/skills/run-lap-webapp/driver.mjs                 # upload page + new-entry modal flow
//   node .claude/skills/run-lap-webapp/driver.mjs --path /app/dashboard --shot dashboard
//   BASE=http://localhost:4123 node .claude/skills/run-lap-webapp/driver.mjs
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const args = Object.fromEntries(process.argv.slice(2).flatMap((a, i, arr) =>
  a.startsWith('--') ? [[a.slice(2), arr[i + 1] && !arr[i + 1].startsWith('--') ? arr[i + 1] : true]] : []));
const BASE = process.env.BASE || 'http://localhost:4123';
const PATHNAME = args.path || '/app/sessions/upload';
const SHOT = args.shot || 'shot';
const OUT = process.env.OUT || '_shots';  // relative to cwd (run from lap-website/)
const FLOW = args.flow || (PATHNAME.includes('/sessions/upload') ? 'upload-modal' : 'none');
mkdirSync(OUT, { recursive: true });

const env = (data) => ({ status: 200, contentType: 'application/json',
  body: JSON.stringify({ ok: true, data, meta: { request_id: 'mock' } }) });
const USER = { id: 1, email: 'demo@lap.test', display_name: 'Demo Driver' };

// UserPlan shape (src/hooks/useUserPlan.ts) — plan.analyses.limit is NOT
// optional-chained, so an empty {} crashes the page. limit:null = unlimited.
const USAGE = {
  plan_tier: 'world-class', subscription_status: 'active',
  analyses: { used: 3, limit: null, resets: null },
  upload_volume_mb: { used: 0, limit: null, resets: null },
  features: { advanced_analysis: true, endurance: true },
};

async function setupMocks(page) {
  // Playwright tries the LAST-registered matching route first → catch-alls FIRST.
  await page.route(/\/api\/v1\//, (r) => r.fulfill(env({})));
  await page.route(/\/auth\//, (r) => r.fulfill(env({ user: USER })));
  // Specific shapes LAST (these win):
  await page.route(/\/api\/v1\/account\/usage(\?|$)/, (r) => r.fulfill(env(USAGE)));
  await page.route(/\/api\/v1\/account\/progress(\?|$)/, (r) => r.fulfill(env({ level: 1, xp: 0, current_streak: 0, longest_streak: 0, days_active: [] })));
  await page.route(/\/api\/v1\/billing\/subscription(\?|$)/, (r) => r.fulfill(env({ status: 'active', plan_tier: 'world-class' })));
  await page.route(/\/api\/v1\/me(\?|$)/, (r) => r.fulfill(env(USER)));
  await page.route(/\/api\/v1\/karts(\?|$)/, (r) => r.fulfill(env([{ id: 1, name: 'Team Kart #1' }, { id: 2, name: 'Rental 24' }])));
  await page.route(/\/api\/v1\/tracks(\?|$)/, (r) => r.fulfill(env([{ id: 1, name: 'South Garda Karting' }, { id: 2, name: 'Lonato' }])));
  await page.route(/\/api\/v1\/drivers(\?|$)/, (r) => r.fulfill(env([{ id: 1, name: 'Demo Driver' }])));
  // /auth/refresh MUST carry access_token + a non-empty display_name user,
  // or AuthGuard hangs / redirects to /app/onboarding.
  await page.route(/\/auth\/refresh(\?|$)/, (r) => r.fulfill(env({ access_token: 'fake', refresh_token: 'fake', user: USER })));
}

const browser = await chromium.launch({ headless: true });
// bypassCSP is MANDATORY for `next dev`: the app's CSP forbids 'unsafe-eval'
// which dev-mode HMR needs; without it the client bundle dies on a PAGEERROR
// and AuthGuard hangs on "Restoring session...". (Prod has no eval.)
const ctx = await browser.newContext({ viewport: { width: 1366, height: 950 }, bypassCSP: true });
const page = await ctx.newPage();
const errs = [];
page.on('pageerror', (e) => errs.push('PAGEERROR: ' + e.message.slice(0, 200)));
await setupMocks(page);

async function shot(name) { await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true }); console.log('  shot →', `${OUT}/${name}.png`); }

try {
  await page.goto(`${BASE}${PATHNAME}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(9000); // next-dev cold-compile + AuthGuard settle
  console.log('URL:', page.url());

  if (FLOW === 'upload-modal') {
    await page.waitForSelector('#track-name', { timeout: 30000 });
    const csv = 'Lap #,Time (s),Speed (m/s)\n' +
      Array.from({ length: 60 }, (_, t) => `1,${(t / 10).toFixed(1)},${(10 + (t % 20) * 0.1).toFixed(1)}`).join('\n') + '\n';
    await (await page.$('input[type="file"]')).setInputFiles({ name: 'session.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) });
    await page.selectOption('#track-name', '__new__');
    await page.waitForTimeout(400);
    await shot('01_upload_form_dropdowns');
    await page.getByRole('button', { name: /Upload & Analyz?e|Upload .* Files/i }).first().click();
    await page.waitForSelector('[role="dialog"]', { timeout: 10000 });
    await page.waitForTimeout(500);
    await shot('02_new_entry_modal');
    await page.fill('#new-track-name', 'Karting Genk');
    await page.fill('#new-track-record', '44.82');
    await page.fill('#new-track-wet', '49.10');
    await page.waitForTimeout(300);
    await shot('03_new_entry_modal_filled');
  } else {
    await page.waitForSelector('main, [id="main-content"]', { timeout: 30000 });
    await page.waitForTimeout(1500);
    await shot(SHOT);
  }
  console.log('OK', errs.length ? '(pageerrors: ' + errs.slice(0, 3).join(' | ') + ')' : '(no pageerrors)');
} catch (e) {
  await shot('99_failure');
  console.log('FAILED:', e.message, '| URL:', page.url(), '| pageerrors:', errs.slice(0, 3));
  process.exitCode = 1;
} finally {
  await browser.close();
}
