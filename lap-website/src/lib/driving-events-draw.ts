/**
 * Pure canvas drawing for the Phase 3 mistake tape.
 *
 * Geometry is INJECTED rather than computed here so these functions can be
 * unit-tested against a recording stub with no DOM. They mirror the shape of
 * the existing cross-session delta bar in SpeedTraceChart (a per-segment
 * strip along the bottom of the plot area), which is already proven on this
 * canvas.
 *
 * Events carry `s_norm_*` (0..1 per lap), not metres. Phase 2 moved to
 * `distance_norm` because absolute metres differenced across laps is a
 * coordinate artifact -- lap spans on real data vary by ~19 m, which is
 * larger than several detectors' firing thresholds. Convert at the drawing
 * boundary; never persist metres back onto an event.
 */
import { canQuoteMagnitude, type DrivingEvent } from '@/lib/driving-events';

export const TAPE_HEIGHT_PX = 8;

export interface TapeGeometry {
  /** Maps an ABSOLUTE lap distance in metres to a pixel x on this chart. */
  xToPixel: (metres: number) => number;
  plotX: number;
  plotY: number;
  plotW: number;
  plotH: number;
  /**
   * The TRUE length of the lap in metres — the denominator `s_norm` is a
   * fraction of. NOT the visible window: see `makeTapeGeometry`.
   */
  lapLengthM: number;
}

const COLORS: Record<string, string> = {
  over_slowing: 'rgba(255, 42, 42, 0.55)',
  late_throttle: 'rgba(250, 204, 21, 0.35)',
  re_braking: 'rgba(249, 115, 22, 0.55)',
  envelope_under_use: 'rgba(59, 130, 246, 0.45)',
};
const COLOR_UNKNOWN = 'rgba(148, 163, 184, 0.40)';

export function eventColor(e: DrivingEvent): string {
  return COLORS[e.event_type] ?? COLOR_UNKNOWN;
}

/** Pixel span of an event, or null when it has none. Clipped to the plot. */
function spanPx(e: DrivingEvent, geo: TapeGeometry): { x: number; w: number } | null {
  const a = e.s_norm_start;
  const b = e.s_norm_end;
  if (typeof a !== 'number' || typeof b !== 'number') return null;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (b < a) return null;  // inverted span is a producer bug, not something to guess at

  const rawL = geo.xToPixel(a * geo.lapLengthM);
  const rawR = geo.xToPixel(b * geo.lapLengthM);
  if (!Number.isFinite(rawL) || !Number.isFinite(rawR)) return null;

  const right = geo.plotX + geo.plotW;

  // Reject spans that do not intersect the visible window at all. This must come
  // before clipping: if we clamp both ends to the boundary, we lose the ability
  // to distinguish a span that straddles the edge from one entirely outside it.
  // An event outside the window should not mark the chart.
  if (rawR < geo.plotX || rawL > right) return null;

  // Now clip to the plot area.
  const l = Math.max(geo.plotX, Math.min(rawL, right));
  const r = Math.max(geo.plotX, Math.min(rawR, right));

  // Apply minimum width, but keep within bounds. When at the right boundary,
  // grow leftward (shift the span) rather than rightward, so a 1px indicator
  // stays inside the plot.
  let w = Math.max(1, r - l);
  let x = l;
  if (x + w > right) {
    x = Math.max(geo.plotX, right - w);
  }
  return { x, w };
}

/**
 * Build the geometry a chart hands to the tape drawers.
 *
 * TWO DIFFERENT LENGTHS, and conflating them is the bug this signature
 * exists to make impossible:
 *
 *  - `lapLengthM` is the LAP. `s_norm` is a fraction of it, so an event at
 *    `s_norm 0.2` on a 1100 m lap is at 220 m, full stop — that does not
 *    change when the driver zooms.
 *  - `xMin`/`xMax` are the VISIBLE WINDOW (`distRange`). They belong to
 *    `xToPixel`, which already maps absolute metres through the crop.
 *
 * This function previously set `lapLengthM = xMax - xMin` and then mapped
 * `xToPixel(xMin + s_norm * lapLengthM)`, i.e. it spread `s_norm ∈ [0,1]`
 * across the visible window whatever the crop. On a 1100 m lap cropped to
 * 400–900 m, an event at `s_norm 0.2` (220 m, outside the window, should not
 * draw at all) was drawn at 500 m — mid-plot, confidently, under a stretch of
 * curve it has nothing to do with. The field name, the doc comment and the
 * test all described the wrong thing in the same words, which is why the
 * reviewer who checked "the xMin offset by construction" confirmed it.
 *
 * Not reachable at the current visualize-page mount (`distRange` stays null
 * there), but `FocusMode.tsx:116,361` already wires both into this chart.
 *
 * Exported so a test can exercise THIS expression rather than a copy of it.
 */
export function makeTapeGeometry(a: {
  /** True lap length in metres. */
  lapLengthM: number;
  /** Visible window in metres — used only to reject a degenerate x-axis. */
  xMin: number; xMax: number;
  /** Absolute lap metres -> pixel x. Already accounts for the crop. */
  xToPixel: (metres: number) => number;
  plotX: number; plotY: number; plotW: number; plotH: number;
}): TapeGeometry | null {
  if (!Number.isFinite(a.lapLengthM) || a.lapLengthM <= 0) return null;
  const windowM = a.xMax - a.xMin;
  if (!Number.isFinite(windowM) || windowM <= 0) return null;
  return {
    xToPixel: a.xToPixel,
    plotX: a.plotX, plotY: a.plotY, plotW: a.plotW, plotH: a.plotH,
    lapLengthM: a.lapLengthM,
  };
}

/** The tape: one coloured segment per event along the bottom of the plot. */
export function drawMistakeTape(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  // Reject non-positive plot dimensions. A zero-width or zero-height plot has
  // no room for marks; drawing anyway violates the invariant "nothing paints
  // outside the plot". This can occur transiently during window resize.
  if (geo.plotW <= 0 || geo.plotH <= 0) return;

  ctx.save();
  const y = geo.plotY + geo.plotH - TAPE_HEIGHT_PX;
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = eventColor(e);
    ctx.fillRect(s.x, y, s.w, TAPE_HEIGHT_PX);
  }
  ctx.restore();
}

/** Full-height wash over each event's corner window. */
export function drawCornerShade(
  ctx: CanvasRenderingContext2D,
  events: DrivingEvent[],
  geo: TapeGeometry,
): void {
  if (!events?.length) return;
  // Reject non-positive plot dimensions to maintain the invariant.
  if (geo.plotW <= 0 || geo.plotH <= 0) return;

  ctx.save();
  for (const e of events) {
    const s = spanPx(e, geo);
    if (!s) continue;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.035)';
    ctx.fillRect(s.x, geo.plotY, s.w, geo.plotH);
  }
  ctx.restore();
}

/**
 * Label for one event. Obeys Global Constraint 1 by reading the payload's own
 * flags -- a magnitude that is not standalone-quotable is never shown as a
 * number, and a cost that is not attributable is never joined to it with
 * causal wording.
 */
export function eventLabel(e: DrivingEvent): string {
  const where = `C${e.corner_id} L${e.lap_number}`;
  const unit = typeof e.magnitude_unit === 'string' ? e.magnitude_unit.trim() : '';
  // A magnitude with no unit is not a smaller claim, it is an unreadable
  // one: `re_braking 9.8` says nothing about whether that is metres, m/s or
  // m/s². This used to emit exactly that, via `${e.magnitude_unit ?? ''}` --
  // the null-unit case silently produced a bare number in front of a driver.
  // No unit means no figure; the event still names itself.
  if (canQuoteMagnitude(e) && unit !== '') {
    return `${where} · ${e.event_type} ${e.magnitude!.toFixed(1)} ${unit}`;
  }
  return `${where} · ${e.event_type}`;
}

/* ── Grip envelope (g-g diagram boundary) ────────────────────────
 *
 * The g-g diagram used to draw `frictionR = maxG * 0.95`, where `maxG` was
 * the largest magnitude among the very points being plotted. A boundary
 * derived from the data it is drawn over cannot diagnose that data: it
 * moves whenever the data moves, so the driver can never be outside it.
 * Migration 085 supplies the honest alternative -- a per-corner measured
 * grip baseline (`grip_anchor_baseline_g`) tagged with a tier naming what
 * it was measured against (`grip_anchor_tier`). `resolveEnvelope` decides
 * what boundary, if any, may be drawn from that anchor.
 */

export interface AnchorSummary {
  baseline_g: number | null;
  tier: string | null;
  reason: string | null;
}

/**
 * Why `resolveEnvelope` decided what it decided.
 *
 * `refused` and `unrecognised_tier` were ONE outcome with ONE sentence until
 * the `session_envelope_ellipse_default_p2` typo was found. That is precisely
 * why it survived five review rounds: a build that does not recognise the
 * tier the backend actually sends is indistinguishable, on screen and in
 * every test, from a backend that honestly refused to measure. They are
 * opposite failures -- one is a statement about the driver's data, the other
 * is a bug in this file -- so they must never share a sentence again.
 */
export type EnvelopeOutcome =
  | 'drawn' | 'producer_refused' | 'unrecognised_tier' | 'no_baseline'
  | 'inconsistent' | 'loading' | 'load_failed';

export interface EnvelopeDecision {
  draw: boolean;
  radiusG: number | null;
  label: string;
  reason: string | null;
  outcome: EnvelopeOutcome;
}

/** Said only when the producer refused, or recorded no anchor at all. */
export const REFUSAL_LABEL = 'Grip limit not measured for this session';

/**
 * The tier this build refuses on, verbatim from `grip_anchor.TIER_REFUSED`.
 *
 * Exported and named because it is a BACKEND value, not a local flag: it is
 * matched against `grip_anchor_tier` as it arrives from the DB. The null-tier
 * bucket `aggregateAnchor` builds internally is deliberately NOT this string
 * (see `NO_ANCHOR_BUCKET`) -- when the two shared one value, a backend rename
 * would have stopped `explicitRefusal` from firing while the sentinel kept
 * every test green.
 */
export const TIER_REFUSED = 'refused';

/**
 * Internal bucket key for corners that recorded NO tier at all.
 *
 * Deliberately not a value the backend can send. TIER_REFUSED used to do both
 * jobs -- the exact match against the producer's tier AND this local bucket
 * -- so if `grip_anchor.py` ever renamed TIER_REFUSED, `explicitRefusal`
 * would stop firing (failing open on the STRONGEST refusal signal there is)
 * while this bucket kept quietly holding the old string and every test kept
 * passing. Given that these constants have already drifted once, the two
 * meanings get two symbols, and the sentinel is unrepresentable in the
 * column so it can never be confused with data.
 */
const NO_ANCHOR_BUCKET = '\u0000no-anchor-recorded';

/**
 * Drawable tiers and how each is worded to a driver.
 *
 * EVERY KEY HERE IS A BACKEND VALUE and must match `grip_anchor.py` byte for
 * byte -- `driving-events-tier-contract.test.ts` parses that file and fails
 * if they drift. `session_envelope_ellipse_default_p2` is spelled out in
 * full: it shipped for five review rounds as `session_envelope_default_p2`
 * (no `ellipse_`), a typo carried from the plan's Global Constraint 6 into
 * the brief and then into this table. Because `DRAWABLE_TIERS` is an exact
 * allow-list, the effect was that the tier the backend selects whenever
 * `friction.exponent_source !== 'fitted'` -- its DEFAULT, not its exception
 * (`grip_anchor.py:491-494`) -- could never draw, and every driver on it was
 * told "Grip limit not measured for this session".
 */
const TIER_LABEL: Record<string, string> = {
  session_envelope_ellipse_fitted: 'session envelope (fitted)',
  session_envelope_ellipse_default_p2: 'session envelope (default p=2)',
  driver_best_session: 'your best this session',
};

/**
 * The set of tiers permitted to draw a boundary -- an ALLOW-list, derived
 * from `TIER_LABEL`'s keys so the two cannot drift apart.
 *
 * This module previously excluded only the refused tier and `null`/`undefined`
 * (a DENY-list): any other string -- an unrecognised tier from a future
 * `grip_anchor.py` rename, a typo'd migration constant, a corrupted row --
 * fell through and drew a confident circle labelled with the raw string.
 * That is Global Constraint 2 inverted: an unknown measurement state
 * silently replaced with a plausible-looking one. Only a tier this build
 * actually recognises may draw; everything else refuses.
 */
export const DRAWABLE_TIERS: ReadonlySet<string> = new Set(Object.keys(TIER_LABEL));

/**
 * Decide what boundary, if any, the g-g diagram may draw.
 *
 * This replaces `frictionR = maxG * 0.95` -- a circle computed from the very
 * points it was drawn over, so it moved whenever the data moved and could
 * never place the driver outside it. `maxObservedG` is accepted ONLY so this
 * function can be given the whole picture; it is deliberately never used to
 * size the boundary. If the anchor refused -- or names any tier this build
 * does not recognise -- we draw nothing and say so.
 */
export function resolveEnvelope(
  anchor: AnchorSummary | null,
  _maxObservedG: number,
): EnvelopeDecision {
  if (!anchor || anchor.tier == null || anchor.tier === TIER_REFUSED) {
    // A refusal that WE derived, from per-corner baselines that do not agree
    // well enough to be one circle, is not the producer declining to measure.
    // Saying "not measured for this session" there would be false: it was
    // measured, several times, and the answers differ.
    if (anchor?.reason === REASON_BASELINES_DISAGREE) {
      return {
        draw: false, radiusG: null, reason: anchor.reason, outcome: 'inconsistent',
        label: 'Grip limit differs too much between corners to draw one boundary',
      };
    }
    return {
      draw: false, radiusG: null, reason: anchor?.reason ?? null,
      outcome: 'producer_refused', label: REFUSAL_LABEL,
    };
  }
  if (!DRAWABLE_TIERS.has(anchor.tier)) {
    // NOT the refusal sentence. The anchor did not refuse -- it named a tier
    // this build has no label for, which means either the backend added or
    // renamed one, or this table is wrong (it has been, exactly once, and
    // the shared sentence is what hid it). Naming the value is the whole
    // point: it is the one string that identifies the mismatch. Drawing
    // still refuses -- an unrecognised tier is not grounds for a boundary.
    return {
      draw: false, radiusG: null, reason: anchor.reason ?? null,
      outcome: 'unrecognised_tier',
      label: `Grip limit unreadable — this build does not recognise tier "${anchor.tier}"`,
    };
  }
  const g = anchor.baseline_g;
  if (typeof g !== 'number' || !Number.isFinite(g) || g <= 0) {
    return {
      draw: false, radiusG: null, reason: anchor.reason ?? null,
      outcome: 'no_baseline', label: REFUSAL_LABEL,
    };
  }
  const tier = TIER_LABEL[anchor.tier];
  return {
    draw: true, radiusG: g, reason: anchor.reason ?? null,
    outcome: 'drawn', label: `${g.toFixed(2)}G — ${tier}`,
  };
}

/**
 * Whether the anchor has been LOOKED UP yet, distinct from what it said.
 *
 * `GGExplorer` held a bare `AnchorSummary | null` initialised to `null`, and
 * `/gg-data` and `/corner-metrics` are independent fetches. Whenever gg-data
 * won the race the canvas painted "Grip limit not measured for this session"
 * and only later redrew with the arc -- a statement about the driver's data
 * made before anything had been looked at. The same `null` also absorbed a
 * network failure, so a 500 read as a measurement refusal too.
 *
 * `DrivingEventsPanel` already had this right with an explicit `loaded` gate;
 * this is the same idea in a form the g-g's pure draw path can consume.
 */
export type AnchorLoad =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'loaded'; anchor: AnchorSummary | null };

/** Said while the corner-metrics fetch is still in flight. */
export const LOADING_LABEL = 'Grip limit — loading…';
/** Said when that fetch failed. NOT a claim about the session's grip. */
export const LOAD_FAILED_LABEL =
  'Grip limit unavailable — could not load this session\'s corner data';

/**
 * `resolveEnvelope`, but for a lookup that may not have happened yet.
 *
 * The three not-drawn cases are deliberately three different sentences:
 * "we have not looked", "we could not look", and "we looked and the
 * producer refused". Only the last is a fact about the driver's data.
 */
export function resolveEnvelopeForLoad(
  load: AnchorLoad | null | undefined,
  maxObservedG: number,
): EnvelopeDecision {
  if (!load || load.status === 'loading') {
    return { draw: false, radiusG: null, reason: null, outcome: 'loading', label: LOADING_LABEL };
  }
  if (load.status === 'error') {
    return {
      draw: false, radiusG: null, reason: null,
      outcome: 'load_failed', label: LOAD_FAILED_LABEL,
    };
  }
  return resolveEnvelope(load.anchor, maxObservedG);
}

/** One row of `GET /sessions/<id>/corner-metrics` -- a `SELECT *`, so the
 * grip_anchor_* columns from migration 085 are already present; only the
 * fields this module reads are declared here. */
export interface CornerAnchorRow {
  grip_anchor_tier?: string | null;
  grip_anchor_reason?: string | null;
  grip_anchor_baseline_g?: number | null;
}

/**
 * Aggregate per-corner grip anchors to one session-level answer
 * (Global Constraint 3).
 *
 * - If ANY corner explicitly refused (`grip_anchor_tier === TIER_REFUSED`),
 *   the whole session refuses immediately -- degrading loudly is the
 *   point, not averaging a refusal away. The first refused row's reason
 *   is carried.
 * - A corner whose tier is null/absent recorded NO anchor at all -- that
 *   is not evidence of grip, so rather than being silently dropped from
 *   the vote (which would let a minority of successfully-anchored corners
 *   decide the session), it is folded into the NO_ANCHOR_BUCKET for the
 *   modal count below. It does not force refusal outright the way an
 *   explicit TIER_REFUSED row does; it only outweighs a good tier once
 *   enough corners share it, which is the "push toward" the brief asked
 *   for rather than a hard trigger.
 * - Otherwise, the modal (most frequent) tier wins; its first matching
 *   row supplies the representative baseline_g/reason. Note this may
 *   still be a tier `resolveEnvelope` does not recognise (e.g. renamed
 *   upstream) -- that check is `resolveEnvelope`'s job, not this one's;
 *   aggregation and drawability are deliberately separate concerns.
 * - A TIE at the top of the count -- two or more tiers (which may include
 *   the null-tier NO_ANCHOR_BUCKET) sharing the max count -- refuses.
 *   The count comparison below reads only `counts[t] === maxCount`, a
 *   value comparison with no dependency on which tier's rows the DB
 *   happened to return first, so the same input in any row order always
 *   resolves the same way. (An earlier version picked the first tier to
 *   reach the max via a `>` scan, which kept whichever tier's key was
 *   inserted into `counts` first -- i.e. whichever corner the `SELECT *`
 *   happened to return first. On an exact tie that made an identical
 *   session draw a confident circle or draw nothing depending on row
 *   order alone. An evenly split vote is not grounds for asserting a
 *   measured limit, so ties resolve toward refusal, not toward whoever
 *   arrived first.)
 */
export function aggregateAnchor(rows: CornerAnchorRow[] | null | undefined): AnchorSummary | null {
  if (!rows || rows.length === 0) return null;

  const explicitRefusal = rows.find((r) => r.grip_anchor_tier === TIER_REFUSED);
  if (explicitRefusal) {
    return { tier: TIER_REFUSED, baseline_g: null, reason: explicitRefusal.grip_anchor_reason ?? null };
  }

  const counts: Record<string, number> = {};
  for (const r of rows) {
    const t = r.grip_anchor_tier == null ? NO_ANCHOR_BUCKET : r.grip_anchor_tier;
    counts[t] = (counts[t] ?? 0) + 1;
  }

  const maxCount = Math.max(...Object.values(counts));
  const leaders = Object.keys(counts).filter((t) => counts[t] === maxCount);

  // leaders.length > 1: a genuine tie (2-way, 3-way, ...) -- ambiguous,
  // refuse regardless of which tiers are tied or what order they arrived
  // in. leaders[0] === NO_ANCHOR_BUCKET with no tie: the null-tier bucket
  // won outright (a real refused row would already have returned above).
  if (leaders.length > 1 || leaders[0] === NO_ANCHOR_BUCKET) {
    const noAnchorReason = rows.find((r) => r.grip_anchor_tier == null)?.grip_anchor_reason ?? null;
    return { tier: TIER_REFUSED, baseline_g: null, reason: noAnchorReason };
  }

  const modalTier = leaders[0];
  // Unreachable in practice: counts always has >=1 key (rows.length > 0 was
  // checked above), so leaders always has >=1 entry here -- the ties/refused
  // branch above already returned for leaders.length > 1. Written as an
  // explicit guard rather than a `leaders[0]!` assertion so a future change
  // to the leader-selection logic above fails safely (returns null) instead
  // of silently re-opening a hole noUncheckedIndexedAccess exists to close.
  if (modalTier === undefined) return null;
  const rep = rows.find((r) => r.grip_anchor_tier === modalTier);

  // ── The RADIUS, not just the tier ──────────────────────────────
  // This used to be `rep.grip_anchor_baseline_g` -- the FIRST modal-tier
  // row's baseline, and the query orders by (lap_number, corner_id), so the
  // circle's size was a sorting artifact. `baseline_g` is
  // `friction.lateral_max(corner_speed)/g` (grip_anchor.py:487), i.e. speed
  // dependent, so a hairpin and a sweeper legitimately differ. See
  // MAX_BASELINE_SPREAD for what "legitimately differ" measures out at on
  // real data, and why a materially split set refuses instead of averaging.
  const baselines = rows
    .filter((r) => r.grip_anchor_tier === modalTier)
    .map((r) => r.grip_anchor_baseline_g)
    .filter((g): g is number => typeof g === 'number' && Number.isFinite(g) && g > 0);

  const agreed = aggregateBaselines(baselines);
  if (agreed === 'disagree') {
    return { tier: TIER_REFUSED, baseline_g: null, reason: REASON_BASELINES_DISAGREE };
  }

  return {
    tier: modalTier,
    baseline_g: agreed,
    reason: rep?.grip_anchor_reason ?? null,
  };
}

/**
 * The largest relative disagreement between per-corner baselines that may
 * still be collapsed to ONE circle: (max - min) / median.
 *
 * MEASURED, not guessed. Rebuilding the friction envelope the way
 * `friction_model.build_friction_model` does (p95 of |a_lat| per speed bin)
 * over `fixtures/golden/OK_R3.csv` -- 201,875 real samples, Ouest Karting --
 * gives, across the speed band where cornering actually happens
 * (|a_lat| > 0.4 G, p5..p95 = 11.2..18.0 m/s):
 *
 *     bin p95 lateral: min 0.591 G, median 0.884 G, max 1.091 G
 *     spread = (1.091 - 0.591) / 0.884 = 56.6%
 *
 * A corner taken at 12 m/s and one at 18 m/s therefore get baselines that
 * differ by nearly 2x, both entirely correctly. One circle cannot represent
 * both, and the g-g plots EVERY corner's samples: size it from the wrong end
 * and a driver at the limit of a high-grip corner reads "I exceeded the
 * measured grip limit" for no reason but arithmetic.
 *
 * The 0.15 threshold comes from what the plot can actually show. The arc is
 * drawn at `rPx = (radiusG / axisMax) * (pW / 2)`; with axisMax ~1.15*maxG
 * (~1.25 G) and pW ~500 px on the visualize page that is ~200 px per G, and
 * the scatter dots have radius 1.2-2.5 px. At a 0.9 G median, 15% spread is
 * 0.135 G ~= 27 px -- an order of magnitude more than a dot, i.e. plainly
 * readable as inside-vs-outside. Below it the disagreement is not resolvable
 * on screen, so collapsing to the median asserts nothing a viewer could
 * contradict.
 *
 * CONSEQUENCE, stated plainly: on a session with the OK_R3 spread this
 * REFUSES and the g-g draws no boundary. That is the honest answer -- there
 * is no single measured grip limit for such a session -- but it does mean
 * the envelope will often not draw on real multi-speed data. Narrowing this
 * number is not the fix; a per-corner or speed-dependent envelope is.
 */
export const MAX_BASELINE_SPREAD = 0.15;

/**
 * Frontend-derived refusal reason. Namespaced so it can never collide with a
 * `grip_anchor.REASON_*` value arriving from the DB -- the contract test
 * asserts that. It is NOT a producer reason: the producer measured fine.
 */
export const REASON_BASELINES_DISAGREE = 'frontend:per_corner_baselines_disagree';

/**
 * One radius from many per-corner baselines, or `'disagree'`.
 *
 * The median, not the first row and not the mean: order-independent by
 * construction (it sorts a COPY, and the caller's array is never reordered),
 * and unmoved by one outlying corner. `'disagree'` when the set spans more
 * than `MAX_BASELINE_SPREAD`; `null` when there is nothing usable to
 * aggregate.
 */
export function aggregateBaselines(baselines: number[]): number | null | 'disagree' {
  const usable = baselines.filter((g) => Number.isFinite(g) && g > 0);
  if (usable.length === 0) return null;

  const s = [...usable].sort((a, b) => a - b);
  const mid = s.length >> 1;
  const median = s.length % 2 === 1 ? s[mid]! : (s[mid - 1]! + s[mid]!) / 2;
  if (!(median > 0)) return null;

  const spread = (s[s.length - 1]! - s[0]!) / median;
  if (spread > MAX_BASELINE_SPREAD) return 'disagree';
  return median;
}
