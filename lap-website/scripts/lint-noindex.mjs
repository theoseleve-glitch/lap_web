#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const violations = [];

// Check 1: /app layout has noindex
const appLayoutPath = path.resolve(process.cwd(), 'src/app/app/layout.tsx');
if (fs.existsSync(appLayoutPath)) {
  const source = fs.readFileSync(appLayoutPath, 'utf-8');
  if (!source.includes('index: false')) {
    violations.push({
      file: 'src/app/app/layout.tsx',
      rule: 'missing-app-noindex',
      detail: 'App layout must have robots: { index: false }',
    });
  }
}

// Check 2: No marketing pages have inline noindex
const marketingDir = path.resolve(process.cwd(), 'src/app/(marketing)');
function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

for (const filePath of walk(marketingDir)) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const relative = path.relative(process.cwd(), filePath).replace(/\\/g, '/');
  if (source.includes('index: false') && !source.includes('generateSeoMetadata')) {
    violations.push({
      file: relative,
      rule: 'marketing-noindex',
      detail: 'Marketing page has inline noindex',
    });
  }
}

if (violations.length === 0) {
  console.log('lint-noindex: App noindex present, no accidental marketing noindex. All clear.');
  process.exit(0);
}

console.error(`lint-noindex: ${violations.length} violation(s):\n`);
for (const v of violations) {
  console.error(`  ${v.file} -- ${v.rule} -- ${v.detail}`);
}
process.exit(1);
