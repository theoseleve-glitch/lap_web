#!/usr/bin/env node
/**
 * Placeholder copy elimination linter.
 *
 * Fails if any production route contains placeholder tokens:
 *   lorem, ipsum, coming soon, TODO, TBD, placeholder, FIXME, [insert
 *
 * Allowlist: pages marked as dev-only are skipped.
 * Exit 1 on violations. Run: node scripts/lint-placeholders.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app/(marketing)'),
  path.resolve(process.cwd(), 'src/app/(auth)'),
  path.resolve(process.cwd(), 'src/app/(free-report)'),
  path.resolve(process.cwd(), 'src/app/app'),
  path.resolve(process.cwd(), 'src/components'),
];

// Pages/files excluded from placeholder checks
const ALLOWLIST = new Set([
  'src/app/app/development',
  'src/app/app/analytics',               // In-progress feature
  'src/components/shared/ComingSoon.tsx',  // Legitimate "coming soon" component
  'src/components/app/focus-mode',        // In-progress feature
]);

const PLACEHOLDER_PATTERNS = [
  { pattern: /\blorem\b/i, name: 'lorem' },
  { pattern: /\bipsum\b/i, name: 'ipsum' },
  { pattern: /\bcoming\s+soon\b/i, name: 'coming soon' },
  { pattern: /\bTODO\b/, name: 'TODO' },
  { pattern: /\bTBD\b/, name: 'TBD' },
  { pattern: /\bFIXME\b/, name: 'FIXME' },
  { pattern: /\[insert\b/i, name: '[insert' },
  // "placeholder" omitted — too many false positives from HTML placeholder= attributes
];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx|js|mdx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function isAllowlisted(filePath) {
  const r = rel(filePath);
  for (const prefix of ALLOWLIST) {
    if (r.startsWith(prefix)) return true;
  }
  return false;
}

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isAllowlisted(filePath)) continue;

    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // Skip comments, imports, and JSX comments
      if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;
      if (trimmed.startsWith('import ')) continue;
      if (/^\{\/\*.*\*\/\}$/.test(trimmed)) continue;  // JSX comment line

      // Skip type/interface definitions and className attributes
      if (/placeholder\s*[\?:]/.test(trimmed) && /interface|type |prop/i.test(source.substring(Math.max(0, source.lastIndexOf('\n', source.indexOf(trimmed) - 1)), source.indexOf(trimmed)))) continue;

      for (const rule of PLACEHOLDER_PATTERNS) {
        if (rule.pattern.test(line)) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            token: rule.name,
            context: trimmed.substring(0, 80),
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-placeholders: No placeholder text found. All clear.');
  process.exit(0);
} else {
  console.error(`lint-placeholders: ${violations.length} placeholder(s) found:\n`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line} — "${v.token}" — ${v.context}`);
  }
  process.exit(1);
}
