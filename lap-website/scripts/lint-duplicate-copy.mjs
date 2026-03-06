#!/usr/bin/env node
/**
 * Build-time lint: detects duplicate copy blocks across marketing pages.
 *
 * Extracts H2/H3 text and following paragraph content from TSX pages.
 * Normalizes whitespace/punctuation/case, then flags:
 *   - exact matches
 *   - similarity > threshold (Jaccard on word trigrams)
 *
 * Exit code 1 on duplicates found (fails CI on main).
 *
 * Config: lint-duplicate-copy.config.json (optional)
 *   { "ignorePatterns": ["Loading form...", "Loading..."] }
 *
 * Usage: node scripts/lint-duplicate-copy.mjs
 */

import fs from 'node:fs';
import path from 'node:path';

const MARKETING_DIR = path.resolve(process.cwd(), 'src/app/(marketing)');
const SIMILARITY_THRESHOLD = 0.85;

// Load optional config
let ignorePatterns = [];
const configPath = path.resolve(process.cwd(), 'lint-duplicate-copy.config.json');
if (fs.existsSync(configPath)) {
  const config = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  ignorePatterns = config.ignorePatterns || [];
}

// Legal boilerplate always ignored
const BUILTIN_IGNORE = [
  'loading form...', 'loading...', 'loading billing panel...',
  'submitting...', 'full', 'none',
];

function walk(dir) {
  const results = [];
  if (!fs.existsSync(dir)) return results;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) results.push(...walk(full));
    else if (/\.(tsx|ts|jsx|mdx?)$/.test(entry.name)) results.push(full);
  }
  return results;
}

function normalize(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function trigrams(text) {
  const words = text.split(' ');
  const set = new Set();
  for (let i = 0; i <= words.length - 3; i++) {
    set.add(words.slice(i, i + 3).join(' '));
  }
  return set;
}

function jaccard(a, b) {
  const intersection = new Set([...a].filter(x => b.has(x)));
  const union = new Set([...a, ...b]);
  return union.size === 0 ? 0 : intersection.size / union.size;
}

function extractCopyBlocks(source) {
  const blocks = [];
  const hRe = /<h[23][^>]*>([^<]{4,})<\/h[23]>/g;
  let m;
  while ((m = hRe.exec(source)) !== null) {
    blocks.push(m[1].trim());
  }
  const pRe = /<p[^>]*>([^<]{15,})<\/p>/g;
  while ((m = pRe.exec(source)) !== null) {
    blocks.push(m[1].trim());
  }
  const descRe = /description=["']([^"']{15,})["']/g;
  while ((m = descRe.exec(source)) !== null) {
    blocks.push(m[1].trim());
  }
  return blocks;
}

// Collect all blocks from all files
const allBlocks = [];
const files = walk(MARKETING_DIR);

for (const filePath of files) {
  const source = fs.readFileSync(filePath, 'utf-8');
  const blocks = extractCopyBlocks(source);
  const relPath = path.relative(process.cwd(), filePath).replace(/\\/g, '/');
  for (const text of blocks) {
    const norm = normalize(text);
    if (norm.length < 10) continue;
    if (BUILTIN_IGNORE.includes(norm)) continue;
    if (ignorePatterns.some(p => norm.includes(normalize(p)))) continue;
    allBlocks.push({ file: relPath, text, normalized: norm });
  }
}

// Detect duplicates
const duplicates = [];
const seen = new Map();

for (const block of allBlocks) {
  if (seen.has(block.normalized)) {
    const existing = seen.get(block.normalized);
    if (existing.some(e => e.file !== block.file)) {
      duplicates.push({
        type: 'exact',
        text: block.text,
        files: [...new Set([...existing.map(e => e.file), block.file])],
      });
    }
    existing.push(block);
  } else {
    seen.set(block.normalized, [block]);
  }
}

// Similarity check (only between different files)
const exactNorms = new Set(duplicates.map(d => normalize(d.text)));
const blocksByFile = new Map();
for (const block of allBlocks) {
  if (exactNorms.has(block.normalized)) continue;
  if (!blocksByFile.has(block.file)) blocksByFile.set(block.file, []);
  blocksByFile.get(block.file).push(block);
}

const fileList = [...blocksByFile.keys()];
for (let i = 0; i < fileList.length; i++) {
  for (let j = i + 1; j < fileList.length; j++) {
    const blocksA = blocksByFile.get(fileList[i]);
    const blocksB = blocksByFile.get(fileList[j]);
    for (const a of blocksA) {
      const triA = trigrams(a.normalized);
      if (triA.size < 3) continue;
      for (const b of blocksB) {
        const triB = trigrams(b.normalized);
        if (triB.size < 3) continue;
        const sim = jaccard(triA, triB);
        if (sim >= SIMILARITY_THRESHOLD) {
          duplicates.push({
            type: `similar (${(sim * 100).toFixed(0)}%)`,
            text: a.text,
            text2: b.text,
            files: [fileList[i], fileList[j]],
          });
        }
      }
    }
  }
}

// Report
if (duplicates.length === 0) {
  console.log('lint-duplicate-copy: No duplicates found.');
  process.exit(0);
} else {
  console.error(`lint-duplicate-copy: Found ${duplicates.length} duplicate(s):\n`);
  for (const dup of duplicates) {
    console.error(`  [${dup.type}] "${dup.text.slice(0, 80)}..."`);
    if (dup.text2) console.error(`    vs: "${dup.text2.slice(0, 80)}..."`);
    console.error(`    in: ${dup.files.join(', ')}`);
    console.error('');
  }
  process.exit(1);
}
