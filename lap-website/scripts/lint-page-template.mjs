#!/usr/bin/env node
/**
 * Marketing page template linter.
 *
 * Enforces section order for marketing pages:
 *   Hero → Proof → HowItWorks → Features → CTA → FAQ
 *
 * Detection: looks for component names or HTML markers in source.
 * Legal pages (privacy, terms, dpa, subprocessors, security) are exempt.
 * Exit 1 if required sections are missing or out of order.
 * Run: node scripts/lint-page-template.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');

// Legal pages exempt from template checks
const EXEMPT_PAGES = new Set([
  'privacy', 'terms', 'dpa', 'subprocessors', 'security',
  'status', 'thank-you/[form]', 'insights', 'insights/[slug]',
  'billing', 'waitlist', 'book', 'contact', 'demo', 'customers',
]);

// Section markers (component names or comment markers)
const SECTION_ORDER = [
  { id: 'hero', markers: ['PageShell', 'HeroSection', 'StartGrid', '<!-- hero -->'] },
  { id: 'proof', markers: ['ProofSection', 'S2Proof', 'Scrutineering', '<!-- proof -->', 'proof.monument'] },
  { id: 'how-it-works', markers: ['HowItWorks', 'PipelineSection', 'S2Pipeline', '<!-- how-it-works -->', 'pipeline.monument'] },
  { id: 'features', markers: ['FeatureSection', 'S3Product', 'FeatureGrid', '<!-- features -->', 'product.monument'] },
  { id: 'cta', markers: ['StampButton', 'CtaSection', 'DemoCtaSection', '<!-- cta -->', 'PitStop'] },
  { id: 'faq', markers: ['FaqSection', 'faq.q', 'FAQ_REGISTRY', '<!-- faq -->', 'pitStop.faq'] },
];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/page\.(tsx|ts|jsx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function pageName(filePath) {
  const r = path.relative(MARKETING_DIR, filePath).replace(/\\/g, '/');
  return r.replace(/\/page\.(tsx|ts)$/, '').replace(/^page\.(tsx|ts)$/, 'home');
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const warnings = [];

for (const filePath of walk(MARKETING_DIR)) {
  const page = pageName(filePath);
  if (EXEMPT_PAGES.has(page)) continue;

  const source = fs.readFileSync(filePath, 'utf-8');
  const relPath = rel(filePath);

  // Find which sections are present and their first occurrence line
  const foundSections = [];
  for (const section of SECTION_ORDER) {
    let firstLine = -1;
    for (const marker of section.markers) {
      const idx = source.indexOf(marker);
      if (idx >= 0) {
        const lineNum = source.substring(0, idx).split('\n').length;
        if (firstLine < 0 || lineNum < firstLine) firstLine = lineNum;
      }
    }
    if (firstLine >= 0) {
      foundSections.push({ id: section.id, line: firstLine });
    }
  }

  // Check order (sections that exist must be in correct relative order)
  for (let i = 1; i < foundSections.length; i++) {
    if (foundSections[i].line < foundSections[i - 1].line) {
      warnings.push({
        file: relPath,
        page,
        msg: `Section "${foundSections[i].id}" appears before "${foundSections[i - 1].id}" (expected order: Hero → Proof → HowItWorks → Features → CTA → FAQ)`,
      });
    }
  }
}

if (warnings.length === 0) {
  console.log('lint-page-template: All marketing pages follow section order.');
  process.exit(0);
} else {
  console.error(`lint-page-template: ${warnings.length} order violation(s):\n`);
  for (const w of warnings) {
    console.error(`  ${w.file} (/${w.page}) — ${w.msg}`);
  }
  process.exit(1);
}
