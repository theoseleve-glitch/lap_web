import { describe, it, expect } from 'vitest';
import {
  TRACK_PATH,
  getChapterPath,
  getHeadingDelta,
  isCornerChapter,
} from '@/experience/narrative/TrackPath';

describe('TrackPath', () => {
  it('defines path for all 11 chapters', () => {
    expect(TRACK_PATH).toHaveLength(11);
    expect(TRACK_PATH[0].chapter).toBe(0);
    expect(TRACK_PATH[10].chapter).toBe(10);
  });

  it('getChapterPath returns config for valid chapter', () => {
    const path = getChapterPath(0);
    expect(path.type).toBe('straight');
    expect(path.heading).toBe(0);
    expect(path.label).toBe('Start Grid');
  });

  it('getChapterPath clamps out-of-range chapters', () => {
    expect(getChapterPath(-1).chapter).toBe(0);
    expect(getChapterPath(99).chapter).toBe(10);
  });

  it('getHeadingDelta computes delta from previous chapter', () => {
    expect(getHeadingDelta(1)).toBe(35);
    expect(getHeadingDelta(2)).toBe(0);
    expect(getHeadingDelta(3)).toBe(-55);
    expect(getHeadingDelta(0)).toBe(0);
  });

  it('isCornerChapter identifies corners correctly', () => {
    expect(isCornerChapter(0)).toBe(false);
    expect(isCornerChapter(1)).toBe(true);
    expect(isCornerChapter(2)).toBe(false);
    expect(isCornerChapter(3)).toBe(true);
    expect(isCornerChapter(8)).toBe(false);
  });

  it('pit-lane chapter has heading 0', () => {
    const pit = getChapterPath(8);
    expect(pit.type).toBe('pit-lane');
    expect(pit.heading).toBe(0);
  });
});
