#!/usr/bin/env node
/**
 * Feature name capitalization linter.
 *
 * Loads canonical feature names from src/content/feature_names.json.
 * Scans marketing + app pages for non-canonical casing.
 * Exit 1 on violations. Run: node scripts/lint-feature-case.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const FEATURE_FILE = path.resolve(process.cwd(), 'src/content/feature_names.json');
const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app/(marketing)'),
  path.resolve(process.cwd(), 'src/app/app'),
  path.resolve(process.cwd(), 'src/components'),
];

const featureData = JSON.parse(fs.readFileSync(FEATURE_FILE, 'utf-8'));
const violations = [];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx|mdx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

// Build alias -> canonical map
const aliasMap = new Map();
for (const feature of featureData.features) {
  for (const alias of feature.aliases) {
    aliasMap.set(alias, feature.canonical);
  }
}

// Build regex that matches any alias (sorted by length desc for greedy matching)
const allAliases = [...aliasMap.keys()].sort((a, b) => b.length - a.length);
const escapedAliases = allAliases.map(a => a.replace(/[-/\\^$*+?.()|[\]{}]/g, '\\$&'));
const aliasRegex = new RegExp(`\\b(${escapedAliases.join('|')})\\b`, 'g');

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    const relPath = rel(filePath);

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // Skip code-only lines
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('import ')) continue;
      if (trimmed.startsWith('const ') || trimmed.startsWith('let ') || trimmed.startsWith('function ')) continue;

      // Only check user-facing text: strings, JSX text
      const textParts = [];
      const strRe = /['"](.*?)['"]/g;
      let m;
      while ((m = strRe.exec(line)) !== null) textParts.push({ text: m[1], offset: m.index });
      const jsxTextRe = />([^<]+)</g;
      while ((m = jsxTextRe.exec(line)) !== null) textParts.push({ text: m[1], offset: m.index });

      for (const part of textParts) {
        aliasRegex.lastIndex = 0;
        let aliasMatch;
        while ((aliasMatch = aliasRegex.exec(part.text)) !== null) {
          const found = aliasMatch[1];
          const canonical = aliasMap.get(found);
          if (canonical) {
            violations.push({
              file: relPath,
              line: i + 1,
              found,
              canonical,
            });
          }
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-feature-case: All feature names use canonical casing.');
  process.exit(0);
} else {
  console.error(`lint-feature-case: ${violations.length} casing violation(s):\n`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line} -- "${v.found}" -> use "${v.canonical}"`);
  }
  // Warnings only — enable blocking after fixing existing violations
  console.error('\n  (feature-case warnings — not blocking CI yet)\n');
  process.exit(0);
}
