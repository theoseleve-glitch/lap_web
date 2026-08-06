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
  xToPixel: (metres: number) => number;
  plotX: number;
  plotY: number;
  plotW: number;
  plotH: number;
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
 * The `xMin` offset is the whole point. `s_norm` is a fraction of the LAP,
 * but the chart's x-axis may be cropped by a zoom (`distRange`), so the
 * fraction must be measured from the visible window's start, not from zero.
 * Getting this wrong shifts every event by the crop offset -- silently, and
 * proportionally to how far the user has zoomed.
 *
 * Exported so a test can exercise THIS expression rather than a copy of it.
 */
export function makeTapeGeometry(a: {
  xMin: number; xMax: number;
  xToPixel: (metres: number) => number;
  plotX: number; plotY: number; plotW: number; plotH: number;
}): TapeGeometry | null {
  const lapLengthM = a.xMax - a.xMin;
  if (!Number.isFinite(lapLengthM) || lapLengthM <= 0) return null;
  return {
    xToPixel: (m: number) => a.xToPixel(a.xMin + m),
    plotX: a.plotX, plotY: a.plotY, plotW: a.plotW, plotH: a.plotH,
    lapLengthM,
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
  if (canQuoteMagnitude(e)) {
    return `${where} · ${e.event_type} ${e.magnitude!.toFixed(1)}${e.magnitude_unit ?? ''}`;
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
export type EnvelopeOutcome = 'drawn' | 'refused' | 'unrecognised_tier' | 'no_baseline';

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
 * This module previously excluded only `'refused'` and `null`/`undefined`
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
    return {
      draw: false, radiusG: null, reason: anchor?.reason ?? null,
      outcome: 'refused', label: REFUSAL_LABEL,
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
 * - If ANY corner explicitly refused (`grip_anchor_tier === 'refused'`),
 *   the whole session refuses immediately -- degrading loudly is the
 *   point, not averaging a refusal away. The first refused row's reason
 *   is carried.
 * - A corner whose tier is null/absent recorded NO anchor at all -- that
 *   is not evidence of grip, so rather than being silently dropped from
 *   the vote (which would let a minority of successfully-anchored corners
 *   decide the session), it is folded into the 'refused' bucket for the
 *   modal count below. It does not force refusal outright the way an
 *   explicit 'refused' row does; it only outweighs a good tier once
 *   enough corners share it, which is the "push toward" the brief asked
 *   for rather than a hard trigger.
 * - Otherwise, the modal (most frequent) tier wins; its first matching
 *   row supplies the representative baseline_g/reason. Note this may
 *   still be a tier `resolveEnvelope` does not recognise (e.g. renamed
 *   upstream) -- that check is `resolveEnvelope`'s job, not this one's;
 *   aggregation and drawability are deliberately separate concerns.
 * - A TIE at the top of the count -- two or more tiers (which may include
 *   the null-tier 'refused' bucket) sharing the max count -- refuses.
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

  const explicitRefusal = rows.find((r) => r.grip_anchor_tier === 'refused');
  if (explicitRefusal) {
    return { tier: 'refused', baseline_g: null, reason: explicitRefusal.grip_anchor_reason ?? null };
  }

  const counts: Record<string, number> = {};
  for (const r of rows) {
    const t = r.grip_anchor_tier == null ? 'refused' : r.grip_anchor_tier;
    counts[t] = (counts[t] ?? 0) + 1;
  }

  const maxCount = Math.max(...Object.values(counts));
  const leaders = Object.keys(counts).filter((t) => counts[t] === maxCount);

  // leaders.length > 1: a genuine tie (2-way, 3-way, ...) -- ambiguous,
  // refuse regardless of which tiers are tied or what order they arrived
  // in. leaders[0] === 'refused' with no tie: the null-tier bucket won
  // outright (a real 'refused' row would already have returned above).
  if (leaders.length > 1 || leaders[0] === 'refused') {
    const noAnchorReason = rows.find((r) => r.grip_anchor_tier == null)?.grip_anchor_reason ?? null;
    return { tier: 'refused', baseline_g: null, reason: noAnchorReason };
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
  return {
    tier: modalTier,
    baseline_g: rep?.grip_anchor_baseline_g ?? null,
    reason: rep?.grip_anchor_reason ?? null,
  };
}
