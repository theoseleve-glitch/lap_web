/**
 * The frontend's copies of backend closed vocabularies, checked against the
 * PRODUCER rather than against a document.
 *
 * WHY THIS FILE EXISTS. Phase 3 spent five review rounds hardening every path
 * that receives an UNKNOWN value -- allow-lists instead of deny-lists, ties
 * resolving toward refusal, unrecognised capability states reading as
 * degraded. Not one of those rounds checked that the KNOWN values were the
 * backend's. They were not: `TIER_LABEL` carried
 * `session_envelope_default_p2` where `grip_anchor.py` defines
 * `session_envelope_ellipse_default_p2`, a typo copied out of the plan. The
 * allow-list then did its job perfectly and refused the real tier -- the one
 * the backend selects by DEFAULT -- so every driver on it was told their grip
 * limit was not measured. A hand-written mock could never catch this,
 * because the mock is written from the same wrong list.
 *
 * So: parse the Python, do not retype it. Every assertion below reads
 * `telemetry_tool/*.py` at test time. If the backend renames a value, this
 * goes red naming both sides; if the file moves or stops parsing, this goes
 * red rather than silently passing on an empty set (a vocabulary check that
 * can vacuously pass is worth nothing -- that is the same failure mode as
 * `tsc --noEmit` being vacuous for this whole phase).
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { DRAWABLE_TIERS, TIER_REFUSED, REASON_BASELINES_DISAGREE } from '@/lib/driving-events-draw';
import { MAGNITUDE_UNITS } from '@/lib/driving-events';

// lap-website/src/__tests__ -> lap-website/src -> lap-website -> repo root
const REPO_ROOT = path.resolve(__dirname, '..', '..', '..');
const TELEMETRY_TOOL = path.join(REPO_ROOT, 'telemetry_tool');

function readBackend(file: string): string {
  const p = path.join(TELEMETRY_TOOL, file);
  if (!fs.existsSync(p)) {
    throw new Error(
      `Backend source of truth ${p} is missing. This test compares the ` +
      `frontend's copy of a closed vocabulary against the module that ` +
      `produces it; without that module it must FAIL, not skip. If the ` +
      `backend moved, repoint REPO_ROOT/TELEMETRY_TOOL -- do not delete ` +
      `this test.`);
  }
  return fs.readFileSync(p, 'utf8');
}

/**
 * Every `NAME = "value"` / `NAME: Final = "value"` string constant in a
 * module, as a name -> value map. Deliberately literal-only: a constant built
 * by an expression is not something this parser may guess at.
 */
function stringConstants(src: string): Map<string, string> {
  const out = new Map<string, string>();
  const re = /^([A-Z][A-Z0-9_]*)\s*(?::\s*Final\s*)?=\s*"([^"]*)"/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) out.set(m[1]!, m[2]!);
  return out;
}

/**
 * The members of a `NAME = frozenset({...})` / `NAME: Final = frozenset({...})`
 * literal, resolved through `stringConstants`.
 *
 * Throws on an unresolvable member rather than dropping it: a silently
 * shrunken expected-set is exactly how a vocabulary check passes while the
 * vocabularies differ.
 */
function frozensetOf(src: string, name: string): Set<string> {
  const re = new RegExp(
    `^${name}\\s*(?::\\s*Final\\s*)?=\\s*frozenset\\(\\{([\\s\\S]*?)\\}\\)`, 'm');
  const block = re.exec(src);
  if (!block) throw new Error(`could not find \`${name} = frozenset({...})\` in the backend source`);

  const consts = stringConstants(src);
  const members = new Set<string>();
  for (const raw of block[1]!.split(',')) {
    // Drop trailing comments, then whitespace.
    const token = raw.replace(/#.*$/gm, '').trim();
    if (!token) continue;
    if (/^"[^"]*"$/.test(token)) { members.add(token.slice(1, -1)); continue; }
    if (/^[A-Z][A-Z0-9_]*$/.test(token)) {
      const v = consts.get(token);
      if (v === undefined) {
        throw new Error(
          `\`${name}\` references ${token}, which this parser could not ` +
          `resolve to a string literal. Refusing to compare against an ` +
          `incomplete set.`);
      }
      members.add(v);
      continue;
    }
    throw new Error(`unparseable member of \`${name}\`: ${JSON.stringify(token)}`);
  }
  if (members.size === 0) throw new Error(`\`${name}\` parsed to an EMPTY set`);
  return members;
}

const sorted = (s: Iterable<string>) => Array.from(s).sort();

describe('the parser itself is not vacuous', () => {
  // A contract test whose parser silently returns nothing would pass forever.
  // These pin the parser against hand-written Python before it is pointed at
  // the real files.
  const SAMPLE = [
    'A_CONST: Final = "alpha"',
    'B_CONST = "beta"',
    'NOT_A_STRING = 42',
    'SOME_SET: Final = frozenset({',
    '    A_CONST,',
    '    B_CONST,',
    '    "gamma",  # inline literal with a comment',
    '})',
  ].join('\n');

  it('reads Final and plain string constants, and ignores non-strings', () => {
    const c = stringConstants(SAMPLE);
    expect(c.get('A_CONST')).toBe('alpha');
    expect(c.get('B_CONST')).toBe('beta');
    expect(c.has('NOT_A_STRING')).toBe(false);
  });

  it('resolves frozenset members through those constants', () => {
    expect(sorted(frozensetOf(SAMPLE, 'SOME_SET'))).toEqual(['alpha', 'beta', 'gamma']);
  });

  it('throws rather than returning a short set when a member does not resolve', () => {
    const broken = 'SOME_SET = frozenset({\n    MISSING_CONST,\n})';
    expect(() => frozensetOf(broken, 'SOME_SET')).toThrow(/could not resolve/);
  });

  it('throws when the named set is absent instead of comparing against nothing', () => {
    expect(() => frozensetOf(SAMPLE, 'NO_SUCH_SET')).toThrow(/could not find/);
  });
});

describe('grip anchor tier vocabulary matches telemetry_tool/grip_anchor.py', () => {
  const src = readBackend('grip_anchor.py');
  const backendTiers = frozensetOf(src, 'TIERS');

  it('sanity: the backend set is non-trivial and contains the refused tier', () => {
    expect(backendTiers.size).toBeGreaterThanOrEqual(3);
  });

  it('TIER_REFUSED is byte-identical to grip_anchor.TIER_REFUSED', () => {
    expect(TIER_REFUSED).toBe(stringConstants(src).get('TIER_REFUSED'));
  });

  it('the drawable tiers plus the refused tier ARE the backend vocabulary', () => {
    // This is the assertion the `session_envelope_ellipse_default_p2` typo
    // would have failed. DRAWABLE_TIERS is TIER_LABEL's key set, so a label
    // added, removed or misspelled here shows up as a set difference naming
    // both sides.
    const frontend = new Set<string>(Array.from(DRAWABLE_TIERS).concat(TIER_REFUSED));
    expect(sorted(frontend)).toEqual(sorted(backendTiers));
  });

  it('every drawable tier is a real backend tier, individually', () => {
    // Same fact, reported per value, so a failure names the offender rather
    // than dumping two sorted arrays.
    for (const tier of Array.from(DRAWABLE_TIERS)) {
      expect({ tier, known: backendTiers.has(tier) }).toEqual({ tier, known: true });
    }
  });

  it('does not claim the refused tier is drawable', () => {
    expect(DRAWABLE_TIERS.has(TIER_REFUSED)).toBe(false);
  });
});

describe("the backend's refused tier and our internal sentinel are separate things", () => {
  const MODULE = path.resolve(__dirname, '..', 'lib', 'driving-events-draw.ts');
  const src = fs.readFileSync(MODULE, 'utf8');
  // Strip comments; they legitimately discuss the string.
  const code = src.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/\/\/[^\n]*/g, ' ');

  it('has exactly one literal "refused" in the module, the constant itself', () => {
    // `'refused'` used to do two jobs: the exact match against the producer's
    // tier value AND the internal bucket for corners with no tier. If the
    // backend renamed TIER_REFUSED, `explicitRefusal` would stop firing —
    // failing OPEN on the strongest refusal signal there is — while the
    // bucket kept holding the old string and every test stayed green. One
    // literal, one meaning; the sentinel is NOT a backend value.
    const literals = code.match(/'refused'/g) ?? [];
    expect(literals.length).toBe(1);
    expect(code).toContain("export const TIER_REFUSED = 'refused'");
  });

  it('the no-anchor bucket sentinel cannot be a legal tier value', () => {
    const m = /const NO_ANCHOR_BUCKET = '([^']*)'/.exec(code);
    expect(m).not.toBeNull();
    const sentinel = JSON.parse(`"${m![1]!}"`) as string;
    const backendTiers = frozensetOf(readBackend('grip_anchor.py'), 'TIERS');
    expect(backendTiers.has(sentinel)).toBe(false);
    // and it is unrepresentable in the column, not merely unused today
    expect(/[ -]/.test(sentinel)).toBe(true);
  });

  it('our own refusal reason cannot collide with a grip_anchor REASON_*', () => {
    const consts = stringConstants(readBackend('grip_anchor.py'));
    const backendReasons = new Set(
      Array.from(consts.entries()).filter(([k]) => k.startsWith('REASON_')).map(([, v]) => v));
    expect(backendReasons.size).toBeGreaterThanOrEqual(5);  // parser sanity
    expect(backendReasons.has(REASON_BASELINES_DISAGREE)).toBe(false);
    // Namespaced on purpose: resolveEnvelope switches on this value to pick
    // a different sentence, so a collision would relabel a producer refusal.
    expect(REASON_BASELINES_DISAGREE.startsWith('frontend:')).toBe(true);
  });
});

describe('magnitude unit vocabulary matches telemetry_tool/driving_events.py', () => {
  const backendUnits = frozensetOf(readBackend('driving_events.py'), 'MAGNITUDE_UNITS');

  it('MAGNITUDE_UNITS is exactly the backend set', () => {
    // The type `MagnitudeUnit` is derived from this array, so this also pins
    // the closed union eventLabel switches on. Note `m/s2`, not `m/s²`: the
    // superscript spelling appeared in a test fixture on this branch and is
    // NOT a value the producer can emit.
    expect(sorted(MAGNITUDE_UNITS)).toEqual(sorted(backendUnits));
  });
});
