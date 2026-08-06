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

function readAllSources(): string {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== '__tests__') walk(p); }
      else if (/\.tsx?$/.test(e.name)) out.push(fs.readFileSync(p, 'utf8'));
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
