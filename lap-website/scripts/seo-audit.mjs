#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

console.log('=== SEO Quarterly Audit ===\n');

const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);

// 1. Count entries with SEO fields
const ENTRY_RE = /'([^']+)':\s*\{/g;
const entries = [];
let match;
while ((match = ENTRY_RE.exec(routeMapSource)) !== null) {
  entries.push(match[1]);
}

const withKeyword = entries.filter((p) =>
  new RegExp(`'${p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'[\\s\\S]*?primaryKeyword[\\s\\S]*?\\}`).test(routeMapSource),
);

console.log(`1. Route entries: ${entries.length} total, ${withKeyword.length} with primaryKeyword`);

// 2. Sitemap coverage
const { collectMarketingSitemapRoutes } = await import(
  pathToFileURL(path.resolve(process.cwd(), 'src/lib/sitemap-routes.mjs')).href
);
const sitemapRoutes = collectMarketingSitemapRoutes();
const routeMapPaths = new Set(entries);
const notInRouteMap = sitemapRoutes.filter((r) => !routeMapPaths.has(r) && r !== '/');

console.log(`\n2. Sitemap: ${sitemapRoutes.length} routes`);
if (notInRouteMap.length > 0) {
  console.warn(`   WARN: Not in route-map: ${notInRouteMap.join(', ')}`);
} else {
  console.log('   OK: All covered');
}

// 3. Description uniqueness
const DESC_RE = /metaDescription:\s*'([^']*)'/g;
const descriptions = [];
let descMatch;
while ((descMatch = DESC_RE.exec(routeMapSource)) !== null) {
  descriptions.push(descMatch[1]);
}

let dupeCount = 0;
for (let i = 0; i < descriptions.length; i++) {
  for (let j = i + 1; j < descriptions.length; j++) {
    const words1 = new Set(descriptions[i].toLowerCase().split(/\s+/));
    const words2 = new Set(descriptions[j].toLowerCase().split(/\s+/));
    const overlap = [...words1].filter((w) => words2.has(w)).length;
    const similarity = overlap / Math.max(words1.size, words2.size);
    if (similarity > 0.7) dupeCount++;
  }
}

console.log(`\n3. Descriptions: ${descriptions.length} total, ${dupeCount} near-duplicates`);

console.log('\n=== Audit complete ===');
