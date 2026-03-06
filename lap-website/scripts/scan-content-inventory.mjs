#!/usr/bin/env node
/**
 * Content inventory scanner.
 * Scans marketing routes and extracts headings + copy block IDs.
 * Outputs CSV to stdout.
 *
 * Usage: node scripts/scan-content-inventory.mjs > docs/content-inventory.csv
 */

import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';

const ROOT = path.resolve(process.cwd(), 'src/app/(marketing)');
const COLUMNS = [
  'url', 'page_name', 'section_id', 'component_name', 'copy_block_id',
  'owner', 'last_updated', 'persona_target', 'jtbd', 'primary_cta_label',
  'primary_cta_url', 'secondary_ctas', 'proof_links', 'claims_used',
  'glossary_terms_used', 'uniqueness_hash', 'notes',
];

function escapeCSV(val) {
  const s = String(val ?? '');
  if (s.includes(',') || s.includes('"') || s.includes('\n')) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

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

function extractHeadings(source) {
  const headings = [];
  const hTagRe = /<h([1-6])[^>]*>([^<]+)<\/h\1>/g;
  let m;
  while ((m = hTagRe.exec(source)) !== null) {
    headings.push({ level: `h${m[1]}`, text: m[2].trim() });
  }
  // Match PageShell title prop
  const titleRe = /title=(?:\{[^}]*['"]([^'"]+)['"][^}]*\}|"([^"]+)")/g;
  while ((m = titleRe.exec(source)) !== null) {
    headings.push({ level: 'h1', text: (m[1] || m[2]).trim() });
  }
  return headings;
}

function extractCTAs(source) {
  const ctas = [];
  const ctaRe = /href=["']([^"']+)["'][^>]*>\s*(?:\{[^}]*\}|([^<]+))/g;
  let m;
  while ((m = ctaRe.exec(source)) !== null) {
    if (m[2]) ctas.push({ label: m[2].trim(), href: m[1] });
  }
  return ctas;
}

function pageNameFromPath(filePath) {
  const rel = path.relative(ROOT, filePath).replace(/\\/g, '/');
  const route = rel.replace(/\/page\.(tsx|ts|jsx|js)$/, '').replace(/^page\.(tsx|ts|jsx|js)$/, '');
  return route || 'home';
}

function routeFromPath(filePath) {
  const name = pageNameFromPath(filePath);
  return name === 'home' ? '/' : `/${name}`;
}

// Header
console.log(COLUMNS.map(escapeCSV).join(','));

const pages = walk(ROOT);

for (const pagePath of pages) {
  const source = fs.readFileSync(pagePath, 'utf-8');
  const pageName = pageNameFromPath(pagePath);
  const url = routeFromPath(pagePath);
  const headings = extractHeadings(source);
  const ctas = extractCTAs(source);
  const primaryCta = ctas[0] || { label: '', href: '' };
  const secondaryCtas = ctas.slice(1).map(c => c.label).join('; ');
  const hash = createHash('sha256').update(source).digest('hex').slice(0, 12);

  if (headings.length === 0) {
    const row = [
      url, pageName, '', '', '',
      '', '', '', '', primaryCta.label,
      primaryCta.href, secondaryCtas, '', '',
      '', hash, '',
    ];
    console.log(row.map(escapeCSV).join(','));
  } else {
    for (const heading of headings) {
      const row = [
        url, pageName, heading.level, '', heading.text,
        '', '', '', '', primaryCta.label,
        primaryCta.href, secondaryCtas, '', '',
        '', hash, '',
      ];
      console.log(row.map(escapeCSV).join(','));
    }
  }
}
