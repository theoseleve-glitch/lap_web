#!/usr/bin/env node
/**
 * Design-token enforcement linter.
 *
 * Forbids raw visual values in TSX/TS files that should use design tokens:
 *   1. Raw hex colors (#xxx, #xxxxxx, #xxxxxxxx)
 *   2. Non-token border-radius (raw rounded-[Npx] or border-radius: Npx)
 *   3. Raw box-shadow in inline style= attributes
 *
 * Scans: src/app/, src/components/
 * Exit 0 with warning (non-blocking) — see bottom comment to make blocking.
 *
 * Run: node scripts/lint-design-tokens.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const SCAN_DIRS = [
  path.resolve(process.cwd(), 'src/app'),
  path.resolve(process.cwd(), 'src/components'),
];

// Files and directories exempt from all rules
const EXEMPT_PATHS = [
  'src/styles/',
  'src/lib/tokens.ts',
  'src/data/brand.ts',
  'tailwind.config.ts',
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

function isExempt(filePath) {
  const r = rel(filePath);
  return EXEMPT_PATHS.some((prefix) => r.startsWith(prefix) || r === prefix);
}

// ── Rule helpers ──────────────────────────────────────────────────────

/**
 * Rule 1: Forbid raw hex colors.
 * Matches #xxx, #xxxxxx, #xxxxxxxx (with word boundary or start-of-token).
 * Skips: comments, imports, `// token-ok` on same line, tailwind color
 * class strings (bg-*, text-*, border-*, etc.), canvas drawing code.
 */
const HEX_RE = /(?:^|[^&\w])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?!\w)/;

function checkHexColor(line, trimmed) {
  if (!HEX_RE.test(line)) return null;
  // Per-line exemptions
  if (/\/\/\s*token-ok/.test(line)) return null;
  if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return null;
  if (trimmed.startsWith('import ')) return null;
  // Canvas/chart drawing — runtime color assignment
  if (/ctx\.(fillStyle|strokeStyle|shadowColor)\s*=/.test(line)) return null;
  // Tailwind color classes next to the hex (likely a config/mapping, not raw usage)
  // Skip lines that are pure tailwind class strings with color names
  if (/\b(bg|text|border|ring|shadow|from|to|via)-[a-z]/.test(line) && /["'`]/.test(line)) {
    // Only skip if the hex is inside a comment-like or mapping context on this line
    // Be conservative: still flag if the hex is clearly in a style prop
    if (!/style\s*=/.test(line)) return null;
  }
  return 'no-raw-hex';
}

/**
 * Rule 2: Forbid non-token border-radius.
 * Forbids: rounded-[12px], rounded-[0.5rem], border-radius: 8px, etc.
 * Allows: rounded-lg, rounded-xl, rounded-2xl, rounded-full,
 *         rounded-1, rounded-2, rounded-3, rounded-4 (custom tokens).
 */
const RAW_ROUNDED_RE = /rounded-\[\s*\d+/;
const RAW_BORDER_RADIUS_RE = /border-radius\s*:\s*\d+/;

function checkBorderRadius(line, trimmed) {
  if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return null;
  if (/\/\/\s*token-ok/.test(line)) return null;
  if (RAW_ROUNDED_RE.test(line)) return 'no-raw-border-radius';
  if (RAW_BORDER_RADIUS_RE.test(line)) return 'no-raw-border-radius';
  return null;
}

/**
 * Rule 3: Forbid raw box-shadow in inline style= attributes.
 * Allows Tailwind shadow-* classes.
 */
const INLINE_SHADOW_RE = /style\s*=\s*\{?\{?[^}]*box-shadow\s*:/i;

function checkBoxShadow(line, trimmed) {
  if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return null;
  if (/\/\/\s*token-ok/.test(line)) return null;
  if (INLINE_SHADOW_RE.test(line)) return 'no-raw-box-shadow';
  return null;
}

// ── Main scan ─────────────────────────────────────────────────────────

const violations = [];

for (const dir of SCAN_DIRS) {
  for (const filePath of walk(dir)) {
    if (isExempt(filePath)) continue;

    const source = fs.readFileSync(filePath, 'utf-8');
    const lines = source.split('\n');
    const fileRel = rel(filePath);

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      const rules = [
        checkHexColor(line, trimmed),
        checkBorderRadius(line, trimmed),
        checkBoxShadow(line, trimmed),
      ];

      for (const rule of rules) {
        if (rule) {
          violations.push({
            file: fileRel,
            line: i + 1,
            rule,
            context: trimmed.substring(0, 80),
          });
        }
      }
    }
  }
}

// ── Output ────────────────────────────────────────────────────────────

if (violations.length === 0) {
  console.log('lint-design-tokens: No violations found. All clear.');
  process.exit(0);
}

console.warn(`lint-design-tokens: ${violations.length} violation(s) found:\n`);
for (const v of violations) {
  console.warn(`  ${v.file}:${v.line} — ${v.rule} — ${v.context}`);
}

// Non-blocking exit — there are ~274 existing hex violations to fix incrementally.
console.warn(`\nlint-design-tokens: ${violations.length} total (non-blocking, exit 0)`);
process.exit(0);

// To make this linter blocking, replace the exit above with:
// process.exit(1);
