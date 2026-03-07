#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [path.resolve(process.cwd(), 'src/app')];
const EXEMPT_PATHS = [
  'src/components/site/SiteHeader.tsx',
  'src/components/site/MobileDrawer.tsx',
  'src/data/navigation.ts',
  'src/data/route-map.ts',
];

function walk(dir) {
  const results = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function rel(filePath) {
  return path.relative(process.cwd(), filePath).replace(/\\/g, '/');
}

function isExempt(filePath) {
  const r = rel(filePath);
  return EXEMPT_PATHS.some((e) => r.endsWith(e));
}

const NAV_PATTERNS = [
  { re: /topNavLinks\s*[:=]/, rule: 'nav-override:topNavLinks-redeclared' },
  { re: /aria-label=["']Primary["']/, rule: 'nav-override:inline-primary-nav' },
];

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isExempt(filePath)) continue;
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trimStart().startsWith('//')) continue;
      for (const pat of NAV_PATTERNS) {
        if (pat.re.test(line)) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            rule: pat.rule,
            context: line.trim().substring(0, 80),
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-nav-overrides: No violations. All clear.');
  process.exit(0);
}

console.error(`lint-nav-overrides: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}
process.exit(1);
