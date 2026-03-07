#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app'),
  path.resolve(process.cwd(), 'src/components'),
];
const EXEMPT_PATHS = ['src/components/ui/Section.tsx', 'src/components/ui/PageIntro.tsx'];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|jsx)$/.test(entry.name)) results.push(full);
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

const HEADING_WITH_CLASS_RE = /<h[23]\s[^>]*className="([^"]*)"/;
const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isExempt(filePath)) continue;
    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.includes('// token-ok')) continue;
      const headingMatch = HEADING_WITH_CLASS_RE.exec(line);
      if (!headingMatch) continue;
      const classStr = headingMatch[1];
      const re = /\b[mp][tbylrx]?-(\[.+?\])/g;
      let spacingMatch;
      while ((spacingMatch = re.exec(classStr)) !== null) {
        const value = spacingMatch[1];
        if (!value.includes('var(--space')) {
          violations.push({
            file: rel(filePath),
            line: i + 1,
            rule: 'spacing:non-token-heading',
            context: `${spacingMatch[0]} -- use Section component or --space-* token`,
          });
        }
      }
    }
  }
}

if (violations.length === 0) {
  console.log('lint-spacing-tokens: No violations. All clear.');
  process.exit(0);
}

const BUDGET = 20;
console.warn(`lint-spacing-tokens: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.warn(`  ${v.file}:${v.line} -- ${v.rule} -- ${v.context}`);
}

if (violations.length > BUDGET) {
  console.error(`\n  FAIL: ${violations.length} exceeds budget of ${BUDGET}`);
  process.exit(1);
} else {
  console.warn(`\n  OK: within budget (${BUDGET - violations.length} remaining)`);
  process.exit(0);
}
