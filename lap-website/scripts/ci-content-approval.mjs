#!/usr/bin/env node
/**
 * CI content approval gate.
 *
 * On PRs that touch content paths, verifies the PR description
 * contains "Content QA completed" checkbox (checked).
 *
 * Requires GITHUB_EVENT_PATH (set by GitHub Actions).
 * Exit 1 if content files changed but checkbox is missing.
 */

import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

const CONTENT_PATHS = [
  'src/app/(marketing)/',
  'src/app/(auth)/',
  'src/content/',
  'src/data/brand.ts',
  'src/data/benefits.ts',
  'src/data/copy.ts',
  'src/data/faq.ts',
  'src/data/personas.ts',
  'src/i18n/',
];

function getChangedFiles() {
  try {
    const base = process.env.GITHUB_BASE_REF || 'main';
    const diff = execFileSync('git', ['diff', '--name-only', `origin/${base}...HEAD`], {
      encoding: 'utf-8',
    });
    return diff.trim().split('\n').filter(Boolean);
  } catch {
    return [];
  }
}

function getPrBody() {
  const eventPath = process.env.GITHUB_EVENT_PATH;
  if (!eventPath || !fs.existsSync(eventPath)) return '';
  try {
    const event = JSON.parse(fs.readFileSync(eventPath, 'utf-8'));
    return event.pull_request?.body || '';
  } catch {
    return '';
  }
}

const changed = getChangedFiles();
const contentChanged = changed.some((f) =>
  CONTENT_PATHS.some((p) => f.startsWith(p) || f.startsWith(`lap-website/${p}`)),
);

if (!contentChanged) {
  console.log('ci-content-approval: No content files changed. Skipping.');
  process.exit(0);
}

const prBody = getPrBody();
const hasCheckbox = /\[x\]\s*\*{0,2}Content QA completed\*{0,2}/i.test(prBody);

if (hasCheckbox) {
  console.log('ci-content-approval: Content QA checkbox found. Passed.');
  process.exit(0);
} else {
  console.error(
    'ci-content-approval: Content files changed but PR description is missing:\n' +
    '  - [x] **Content QA completed**\n\n' +
    'Add and check this item in your PR description, then push again.',
  );
  process.exit(1);
}
