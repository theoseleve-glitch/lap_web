#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');

const routeMapSource = fs.readFileSync(
  path.resolve(process.cwd(), 'src/data/route-map.ts'),
  'utf-8',
);
const PATH_KEY_RE = /'([^']+)':\s*\{/g;
const registeredPaths = new Set();
let match;
while ((match = PATH_KEY_RE.exec(routeMapSource)) !== null) {
  registeredPaths.add(match[1]);
}

function findPages(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...findPages(full));
    else if (entry.name === 'page.tsx') results.push(full);
  }
  return results;
}

const violations = [];

for (const pageFile of findPages(MARKETING_DIR)) {
  const relative = path.relative(MARKETING_DIR, path.dirname(pageFile)).replace(/\\/g, '/');
  const routePath = relative ? `/${relative}` : '/';
  // Skip dynamic route segments (e.g., [slug], [form])
  if (routePath.includes('[')) continue;
  if (!registeredPaths.has(routePath) && routePath !== '/') {
    violations.push({
      file: path.relative(process.cwd(), pageFile).replace(/\\/g, '/'),
      path: routePath,
    });
  }
}

if (violations.length === 0) {
  console.log('lint-route-map: All marketing pages have route-map entries. All clear.');
  process.exit(0);
}

console.error(`lint-route-map: ${violations.length} page(s) missing from route-map:\n`);
for (const v of violations) {
  console.error(`  ${v.file} -> expected routeMap['${v.path}']`);
}
process.exit(1);
