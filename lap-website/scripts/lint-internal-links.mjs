#!/usr/bin/env node
/**
 * Internal link map linter.
 *
 * Crawls marketing pages and reports:
 *  - Dead links (href targets with no matching page)
 *  - Orphan pages (no inbound links from other marketing pages)
 *  - Overlinked pages (>15 outbound links)
 *
 * Exit 1 on dead links or orphans. Run: node scripts/lint-internal-links.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');
const AUTH_DIR = path.resolve(process.cwd(), 'src/app/(auth)');
const APP_DIR = path.resolve(process.cwd(), 'src/app/app');
const FREE_REPORT_DIR = path.resolve(process.cwd(), 'src/app/(free-report)');

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/page\.(tsx|ts|jsx|js)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function routeFromPath(baseDir, filePath) {
  const r = path.relative(baseDir, filePath).replace(/\\/g, '/');
  const route = r.replace(/\/page\.(tsx|ts|jsx|js)$/, '').replace(/^page\.(tsx|ts|jsx|js)$/, '');
  return route ? `/${route}` : '/';
}

// Discover all valid routes
const validRoutes = new Set();

for (const f of walk(MARKETING_DIR)) validRoutes.add(routeFromPath(MARKETING_DIR, f));
if (fs.existsSync(AUTH_DIR)) {
  for (const f of walk(AUTH_DIR)) validRoutes.add(routeFromPath(AUTH_DIR, f));
}
if (fs.existsSync(APP_DIR)) {
  for (const f of walk(APP_DIR)) {
    validRoutes.add('/app' + routeFromPath(APP_DIR, f).replace(/^\/$/, ''));
  }
}
if (fs.existsSync(FREE_REPORT_DIR)) {
  for (const f of walk(FREE_REPORT_DIR)) {
    const r = routeFromPath(FREE_REPORT_DIR, f);
    validRoutes.add(r === '/' ? '/free-report' : `/free-report${r}`);
  }
}

// Known special routes
for (const r of ['/', '/register', '/login', '/free-report/analyze', '/auth/callback']) {
  validRoutes.add(r);
}

function extractLinks(source) {
  const links = [];
  const hrefRe = /href=["']([^"']+)["']/g;
  let m;
  while ((m = hrefRe.exec(source)) !== null) {
    const href = m[1];
    if (href.startsWith('/') && !href.startsWith('//')) {
      links.push(href.split('?')[0].split('#')[0]);
    }
  }
  return links;
}

function isValidRoute(href) {
  if (validRoutes.has(href)) return true;
  for (const route of validRoutes) {
    if (route.includes('[')) {
      const pattern = route.replace(/\[[\w]+\]/g, '[^/]+');
      if (new RegExp(`^${pattern}$`).test(href)) return true;
    }
  }
  return false;
}

const marketingPages = walk(MARKETING_DIR);
const outbound = new Map();
const inbound = new Map();
const deadLinks = [];

for (const f of marketingPages) {
  const route = routeFromPath(MARKETING_DIR, f);
  if (!inbound.has(route)) inbound.set(route, new Set());
}

for (const filePath of marketingPages) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const route = routeFromPath(MARKETING_DIR, filePath);
  const links = extractLinks(source);
  outbound.set(route, links);

  for (const href of links) {
    if (inbound.has(href)) inbound.get(href).add(route);
    if (!isValidRoute(href)) {
      deadLinks.push({
        source: route,
        href,
        file: path.relative(process.cwd(), filePath).replace(/\\/g, '/'),
      });
    }
  }
}

// Pages that are intentionally not linked from marketing pages
// (accessed via app nav, form redirects, direct URLs, or dynamic routing)
const ALLOWED_ORPHANS = new Set([
  '/billing', '/book', '/customers', '/dpa', '/insights/[slug]',
  '/security', '/status', '/thank-you/[form]', '/waitlist',
]);

const orphans = [];
for (const [route, sources] of inbound.entries()) {
  if (route === '/') continue;
  if (ALLOWED_ORPHANS.has(route)) continue;
  if (sources.size === 0) orphans.push(route);
}

const OVERLINK_THRESHOLD = 15;
const overlinked = [];
for (const [route, links] of outbound.entries()) {
  if (links.length > OVERLINK_THRESHOLD) {
    overlinked.push({ route, count: links.length });
  }
}

// ── Report ──
let hasErrors = false;

console.log('=== Internal Link Map Report ===\n');
console.log(`Pages scanned: ${marketingPages.length}`);
console.log(`Valid routes discovered: ${validRoutes.size}\n`);

if (deadLinks.length > 0) {
  hasErrors = true;
  console.error(`DEAD LINKS (${deadLinks.length}):`);
  for (const d of deadLinks) console.error(`  ${d.source} -> ${d.href}  (${d.file})`);
  console.error('');
}

if (orphans.length > 0) {
  hasErrors = true;
  console.error(`ORPHAN PAGES (${orphans.length}):`);
  for (const o of orphans) console.error(`  ${o}`);
  console.error('');
}

if (overlinked.length > 0) {
  console.log(`OVERLINKED (${overlinked.length}):`);
  for (const o of overlinked) console.log(`  ${o.route}: ${o.count} links`);
  console.log('');
}

if (!hasErrors && overlinked.length === 0) console.log('All checks passed.');

process.exit(hasErrors ? 1 : 0);
