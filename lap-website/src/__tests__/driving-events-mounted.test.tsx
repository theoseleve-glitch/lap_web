import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Tasks 1-6 all passed their own reviews while shipping nothing a user could
 * see: `showDrivingEvents` was never set true anywhere, and the panel was
 * mounted on no page. Unit tests could not catch that -- each component was
 * correct in isolation. This test asserts the components are actually
 * REACHED, which is the one property no component test can assert about
 * itself.
 */
const SRC = path.resolve(__dirname, '..');

// A file is "product code" only if it is a .ts/.tsx file that is NOT itself
// a test -- by directory (`__tests__/...`, handled in the walk below) AND by
// filename (colocated `*.test.ts(x)` / `*.spec.ts(x)`, e.g.
// `src/lib/safe-redirect.test.ts`, `src/middleware.test.ts`,
// `src/app/(marketing)/billing/page.test.tsx`). Directory-only filtering
// missed those six colocated files, so their string literals and comments
// were being scanned as if they were the real page/component code.
const TEST_FILE = /\.(test|spec)\.tsx?$/;

function isProductFile(name: string): boolean {
  return /\.tsx?$/.test(name) && !TEST_FILE.test(name);
}

// Strip comments before scanning. A `// showDrivingEvents` or
// `// <DrivingEventsPanel sessionId="x" />` left behind by a refactor (or
// planted as a decoy) must NOT satisfy these assertions -- only a live
// mount may. This is deliberately a simple, non-tokenizing stripper (it
// does not understand string/template literals, so a literal `//` or
// `/*` inside a string could theoretically be mis-stripped); that's an
// accepted trade-off for a test-only guard scanning our own source, not a
// general-purpose JS/TS parser.
function stripComments(code: string): string {
  return code
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\/\/[^\n]*/g, '');
}

function readAllSources(): string {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== '__tests__') walk(p); }
      else if (isProductFile(e.name)) out.push(stripComments(fs.readFileSync(p, 'utf8')));
    }
  };
  walk(SRC);
  return out.join('\n');
}

describe('the driving-events surfaces are actually reachable', () => {
  const sources = readAllSources();

  it('sets showDrivingEvents somewhere outside its own definition', () => {
    // A page must opt in, not merely the prop existing on the component.
    // Matches `showDrivingEvents={true}`, `showDrivingEvents=true`,
    // the JSX boolean-shorthand `showDrivingEvents` immediately followed by
    // `/>`, or the shorthand on its own line (immediately followed by a
    // newline) -- but NOT the prop's own `?: boolean` type declaration,
    // its `= false` default, or its `if (!showDrivingEvents ...)` usage
    // inside SpeedTraceChart.tsx, none of which are followed by any of
    // those tokens.
    expect(sources).toMatch(/showDrivingEvents(\s*=\s*\{?\s*true|\s*\/>|\s*\n)/);
  });

  it('mounts DrivingEventsPanel on a page', () => {
    // The component's own file only ever *declares*
    // `function DrivingEventsPanel(...)` -- it never writes the JSX tag
    // `<DrivingEventsPanel`, so this can only be satisfied by a caller.
    expect(sources).toContain('<DrivingEventsPanel');
  });
});
