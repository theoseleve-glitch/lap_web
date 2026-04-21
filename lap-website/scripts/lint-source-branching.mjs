#!/usr/bin/env node
// W8 CI gate — forbids branching on `session.source` in render code.
// All depth-scaling logic must gate on `session.capabilities.channels`
// or `optimizer.depth` instead. The "one big brain" principle (spec §10 Q4)
// is enforced here.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../src', import.meta.url));
const EXCLUDE_SUFFIXES = ['.test.ts', '.test.tsx'];
const EXCLUDE_DIRS = ['mocks', '__tests__'];
const EXCLUDE_FILES = ['types/contracts.ts'];

const PATTERN =
  /session\.source\s*[=!]==|\.source\s*[=!]==\s*['"](real_life|iracing|ac)['"]/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (EXCLUDE_DIRS.includes(name)) continue;
      yield* walk(full);
    } else {
      yield full;
    }
  }
}

const violations = [];
for (const file of walk(ROOT)) {
  const rel = relative(ROOT, file).replace(/\\/g, '/');
  if (EXCLUDE_FILES.some((p) => rel === p)) continue;
  if (EXCLUDE_SUFFIXES.some((s) => rel.endsWith(s))) continue;
  if (!['.ts', '.tsx'].includes(extname(file))) continue;
  const content = readFileSync(file, 'utf-8');
  content.split('\n').forEach((line, i) => {
    if (PATTERN.test(line)) violations.push(`${rel}:${i + 1}: ${line.trim()}`);
  });
}

if (violations.length) {
  console.error('[lint:source-branching] Forbidden source branching in render code:');
  for (const v of violations) console.error('  ' + v);
  console.error('\nUse `session.capabilities.channels` or `optimizer.depth` instead.');
  process.exit(1);
}
console.log('[lint:source-branching] OK — no source branching in render code');
