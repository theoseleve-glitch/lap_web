import { describe, it, expect } from 'vitest';
import { replayReducer, initialReplayState } from '../replayReducer';

describe('replayReducer', () => {
  it('SET_MODE resets frame and stops playing', () => {
    const state = { ...initialReplayState, frame: 50, playing: true };
    const next = replayReducer(state, { type: 'SET_MODE', mode: 'split' });
    expect(next.mode).toBe('split');
    expect(next.frame).toBe(0);
    expect(next.playing).toBe(false);
  });

  it('SET_CORNER resets frame and stops playing', () => {
    const state = { ...initialReplayState, frame: 50, playing: true };
    const next = replayReducer(state, { type: 'SET_CORNER', index: 2 });
    expect(next.cornerIndex).toBe(2);
    expect(next.frame).toBe(0);
    expect(next.playing).toBe(false);
  });

  it('NEXT_CORNER wraps around', () => {
    const state = { ...initialReplayState, cornerIndex: 2 };
    const next = replayReducer(state, { type: 'NEXT_CORNER', total: 3 });
    expect(next.cornerIndex).toBe(0);
  });

  it('PREV_CORNER wraps around', () => {
    const state = { ...initialReplayState, cornerIndex: 0 };
    const next = replayReducer(state, { type: 'PREV_CORNER', total: 3 });
    expect(next.cornerIndex).toBe(2);
  });

  it('TOGGLE_PLAY toggles playing', () => {
    const next = replayReducer(initialReplayState, { type: 'TOGGLE_PLAY' });
    expect(next.playing).toBe(true);
    const next2 = replayReducer(next, { type: 'TOGGLE_PLAY' });
    expect(next2.playing).toBe(false);
  });

  it('SET_SPEED changes speed', () => {
    const next = replayReducer(initialReplayState, { type: 'SET_SPEED', speed: 2 });
    expect(next.speed).toBe(2);
  });

  it('SET_FRAME sets frame', () => {
    const next = replayReducer(initialReplayState, { type: 'SET_FRAME', frame: 42 });
    expect(next.frame).toBe(42);
  });

  it('SET_LAP_A resets frame', () => {
    const state = { ...initialReplayState, frame: 50 };
    const next = replayReducer(state, { type: 'SET_LAP_A', lap: 3 });
    expect(next.lapA).toBe(3);
    expect(next.frame).toBe(0);
  });
});
