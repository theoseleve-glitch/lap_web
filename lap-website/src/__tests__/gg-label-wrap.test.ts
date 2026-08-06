/**
 * `wrapLabel` and `drawWrappedLabel` (GGExplorer.tsx) are the mechanism
 * behind the fix-round-2 label-clipping fix -- "Grip limit not measured for
 * this session" and the longer drawn-envelope tier labels were being
 * invisibly clipped by the plot area's `ctx.clip()` at laptop widths, and
 * these two pure functions are what stopped that. They shipped with zero
 * direct test coverage: `grep -rn "wrapLabel\|drawWrappedLabel" src/`
 * outside GGExplorer.tsx itself returned nothing before this file.
 *
 * Same no-DOM canvas-recorder technique as driving-events.test.ts and
 * speed-trace-tape-stacking.test.ts, but with a real `measureText` --
 * those recorders return `undefined` for every call, which is fine for
 * `fillRect`/`fillText` (void), but `wrapLabel` reads
 * `ctx.measureText(...).width`, so a bare void-recorder would throw.
 */
import { describe, it, expect } from 'vitest';
import { wrapLabel, drawWrappedLabel } from '@/components/shared/charts/GGExplorer';

const WIDTH_PER_CHAR = 6;

function stubCtx() {
  const fillTextCalls: Array<{ text: string; x: number; y: number }> = [];
  const ctx = {
    measureText: (text: string) => ({ width: text.length * WIDTH_PER_CHAR }) as TextMetrics,
    fillText: (text: string, x: number, y: number) => { fillTextCalls.push({ text, x, y }); },
  } as unknown as CanvasRenderingContext2D;
  return { ctx, fillTextCalls };
}

describe('wrapLabel', () => {
  it("wraps a normal sentence, and lines.join(' ') reconstructs the original text", () => {
    const { ctx } = stubCtx();
    const text = 'the quick brown fox jumps over the lazy dog';
    const lines = wrapLabel(ctx, text, 18 * WIDTH_PER_CHAR);
    expect(lines.length).toBeGreaterThan(1);
    expect(lines.join(' ')).toBe(text);
  });

  it('gives a single word longer than maxWidth its own line and never drops it', () => {
    const { ctx } = stubCtx();
    const longWord = 'b'.repeat(20);
    const text = `a ${longWord} c`;
    const lines = wrapLabel(ctx, text, 8 * WIDTH_PER_CHAR);
    expect(lines).toContain(longWord);
    expect(lines.join(' ')).toBe(text);
  });

  it('behaves the same way for a string with no spaces at all', () => {
    const { ctx } = stubCtx();
    const word = 'x'.repeat(30);
    const lines = wrapLabel(ctx, word, 5 * WIDTH_PER_CHAR);
    expect(lines).toEqual([word]);
  });

  it('terminates immediately with one word per line at maxWidth 0, no throw, no hang', () => {
    const { ctx } = stubCtx();
    const text = 'one two three four';
    expect(wrapLabel(ctx, text, 0)).toEqual(['one', 'two', 'three', 'four']);
  });

  it('terminates immediately with one word per line at a negative maxWidth, no throw, no hang', () => {
    const { ctx } = stubCtx();
    const text = 'one two three four';
    expect(wrapLabel(ctx, text, -100)).toEqual(['one', 'two', 'three', 'four']);
  });

  it('returns [] for an empty string', () => {
    const { ctx } = stubCtx();
    expect(wrapLabel(ctx, '', 100)).toEqual([]);
  });

  it('terminates promptly on a long realistic string at maxWidth: 1', () => {
    const { ctx } = stubCtx();
    const text =
      'Grip limit not measured for this session, and this sentence is deliberately '
      + 'longer and more realistic than the actual label to make sure the loop '
      + 'still terminates promptly rather than hanging';
    const start = Date.now();
    const lines = wrapLabel(ctx, text, 1);
    expect(Date.now() - start).toBeLessThan(1000);
    // maxWidth of 1 can't fit any non-empty candidate, so every word ends
    // up alone on its own line -- same degeneration as maxWidth <= 0.
    expect(lines.length).toBe(text.split(' ').length);
  });

  /**
   * DECISION (fix round 3): a whitespace-only string collapses to `[]` --
   * zero lines for non-empty input -- because `' '.split(' ')` yields two
   * empty strings and the trailing `if (line)` never fires on either. Left
   * UNGUARDED as a documented accepted precondition (see the doc comment
   * on wrapLabel in GGExplorer.tsx): every real caller passes one of
   * resolveEnvelope's two hardcoded label literals, never user- or
   * DB-sourced text, and neither literal is blank, so this path is
   * unreachable today. Locked in here so a future change to this function
   * alters it knowingly rather than by silent accident.
   */
  it('collapses a whitespace-only string to zero lines (documented, not guarded)', () => {
    const { ctx } = stubCtx();
    expect(wrapLabel(ctx, ' ', 100)).toEqual([]);
  });
});

describe('drawWrappedLabel', () => {
  it('draws one fillText call per wrapped line, at x held constant and y increasing by lineHeight', () => {
    const { ctx, fillTextCalls } = stubCtx();
    const text = 'the quick brown fox jumps over the lazy dog';
    drawWrappedLabel(ctx, text, 5, 20, 18 * WIDTH_PER_CHAR, 11);
    expect(fillTextCalls.length).toBeGreaterThan(1);
    expect(fillTextCalls.map((c) => c.text).join(' ')).toBe(text);
    fillTextCalls.forEach((call, i) => {
      expect(call.x).toBe(5);
      expect(call.y).toBe(20 + i * 11);
    });
  });

  it('draws nothing for an empty string, without throwing', () => {
    const { ctx, fillTextCalls } = stubCtx();
    expect(() => drawWrappedLabel(ctx, '', 10, 10, 100)).not.toThrow();
    expect(fillTextCalls.length).toBe(0);
  });
});
