#!/usr/bin/env node
// W8 CI gate — forbids raw hex colors and Tailwind default-palette classes
// in new/edited session-related files. Design tokens only:
// asphalt / concrete / chalk / steel / gold / acid-green / safety-red /
// marshal-yellow / racing-purple (from src/styles/tokens.css).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, extname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../src', import.meta.url));

// Scoped to W8's new files only. Pre-existing violations in
// app/app/sessions/*.tsx are a separate hygiene problem and out of scope for
// this workstream; this gate prevents NEW session-layer code from regressing.
const WATCH_GLOBS = [
  'components/session/',
];

const DISALLOWED_TW = [
  'red', 'blue', 'green', 'yellow', 'orange', 'purple', 'pink',
  'emerald', 'cyan', 'amber', 'zinc', 'gray', 'slate', 'neutral', 'stone',
  'lime', 'sky', 'indigo', 'violet', 'fuchsia', 'rose', 'teal',
];
const HEX_RE = /#[0-9A-Fa-f]{3,8}\b/;
const TW_RE = new RegExp(
  `(bg|text|border|ring|divide|from|to|via|fill|stroke)-(${DISALLOWED_TW.join('|')})-\\d{2,3}`,
);

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) yield* walk(full);
    else yield full;
  }
}

function watched(rel) {
  return WATCH_GLOBS.some((g) => rel === g || rel.startsWith(g));
}

const violations = [];
for (const file of walk(ROOT)) {
  const rel = relative(ROOT, file).replace(/\\/g, '/');
  if (!watched(rel)) continue;
  if (!['.ts', '.tsx'].includes(extname(file))) continue;
  if (rel.endsWith('.test.ts') || rel.endsWith('.test.tsx')) continue;
  const content = readFileSync(file, 'utf-8');
  content.split('\n').forEach((line, i) => {
    if (HEX_RE.test(line) || TW_RE.test(line)) {
      violations.push(`${rel}:${i + 1}: ${line.trim()}`);
    }
  });
}

if (violations.length) {
  console.error('[lint:session-tokens] Raw hex or Tailwind default colors in session files:');
  for (const v of violations) console.error('  ' + v);
  console.error(
    '\nUse design tokens from src/styles/tokens.css ' +
      '(asphalt, concrete, chalk, steel, gold, acid-green, safety-red, marshal-yellow, racing-purple).',
  );
  process.exit(1);
}
console.log('[lint:session-tokens] OK — all session files use design tokens');
