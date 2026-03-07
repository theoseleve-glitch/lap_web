#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);

const SEO_EXEMPT = new Set(['/', '/sitemap']);
const violations = [];
const keywords = new Map();
const descriptions = new Map();

/**
 * Extract route entries using a balanced-brace parser so that nested
 * structures like sectionAnchors (arrays of objects) are handled correctly.
 */
function extractEntries(source) {
  const entries = [];
  const keyRe = /'([^']+)':\s*\{/g;
  let keyMatch;
  while ((keyMatch = keyRe.exec(source)) !== null) {
    const routePath = keyMatch[1];
    const bodyStart = keyMatch.index + keyMatch[0].length;
    let depth = 1;
    let i = bodyStart;
    while (i < source.length && depth > 0) {
      if (source[i] === '{') depth++;
      else if (source[i] === '}') depth--;
      if (depth > 0) i++;
    }
    entries.push({ routePath, body: source.slice(bodyStart, i) });
  }
  return entries;
}

for (const { routePath, body } of extractEntries(routeMapSource)) {

  if (SEO_EXEMPT.has(routePath)) continue;

  const kwMatch = body.match(/primaryKeyword:\s*'([^']*)'/);
  if (!kwMatch) {
    violations.push({ path: routePath, rule: 'missing-keyword', detail: 'No primaryKeyword' });
  } else {
    const kw = kwMatch[1].toLowerCase();
    if (keywords.has(kw)) {
      violations.push({
        path: routePath,
        rule: 'duplicate-keyword',
        detail: `Shares keyword "${kw}" with ${keywords.get(kw)}`,
      });
    } else {
      keywords.set(kw, routePath);
    }
  }

  const descMatch = body.match(/metaDescription:\s*'([^']*)'/);
  if (!descMatch) {
    violations.push({ path: routePath, rule: 'missing-description', detail: 'No metaDescription' });
  } else {
    const desc = descMatch[1];
    if (desc.length < 80) {
      violations.push({
        path: routePath,
        rule: 'short-description',
        detail: `metaDescription is ${desc.length} chars (min 80)`,
      });
    }
    if (desc.length > 160) {
      violations.push({
        path: routePath,
        rule: 'long-description',
        detail: `metaDescription is ${desc.length} chars (max 160)`,
      });
    }
    if (descriptions.has(desc)) {
      violations.push({
        path: routePath,
        rule: 'duplicate-description',
        detail: `Shares description with ${descriptions.get(desc)}`,
      });
    } else {
      descriptions.set(desc, routePath);
    }
  }
}

if (violations.length === 0) {
  console.log('lint-seo-fields: All SEO fields valid. All clear.');
  process.exit(0);
}

console.error(`lint-seo-fields: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.path} -- ${v.rule} -- ${v.detail}`);
}
process.exit(1);
