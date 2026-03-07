#!/usr/bin/env node
/**
 * Icon import linter.
 *
 * Forbids importing external icon libraries (heroicons, tabler, fontawesome, react-icons).
 * This project uses inline SVG icons for consistency and bundle size.
 * lucide-react is allowed as the single approved icon library if adopted.
 *
 * Run: node scripts/lint-icon-imports.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app'),
  path.resolve(process.cwd(), 'src/components'),
  path.resolve(process.cwd(), 'src/lib'),
];

const FORBIDDEN_IMPORTS = [
  { pattern: /@heroicons\//, name: '@heroicons' },
  { pattern: /@tabler\/icons/, name: '@tabler/icons' },
  { pattern: /react-icons\//, name: 'react-icons' },
  { pattern: /@fortawesome\//, name: '@fortawesome' },
  { pattern: /phosphor-react/, name: 'phosphor-react' },
];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx|js)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (!line.includes('import')) continue;
      for (const rule of FORBIDDEN_IMPORTS) {
        if (rule.pattern.test(line)) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            lib: rule.name,
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-icon-imports: No forbidden icon imports found.');
  process.exit(0);
} else {
  console.error(`lint-icon-imports: ${violations.length} forbidden icon import(s):\n`);
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line} — forbidden import from "${v.lib}"`);
  }
  process.exit(1);
}
