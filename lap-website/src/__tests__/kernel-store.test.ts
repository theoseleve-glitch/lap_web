import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';

describe('KernelStore', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes with default state', () => {
    const state = useKernelStore.getState();
    expect(state.currentChapter).toBe(0);
    expect(state.mode).toBe('preloading');
    expect(state.qualityTier).toBe('high');
    expect(state.preloaderComplete).toBe(false);
    expect(state.scrollVelocity).toBe(0);
    expect(state.pointerX).toBe(0.5);
    expect(state.pointerY).toBe(0.5);
  });

  it('setCurrentChapter clamps to valid range', () => {
    const { setCurrentChapter } = useKernelStore.getState();
    setCurrentChapter(5);
    expect(useKernelStore.getState().currentChapter).toBe(5);
    setCurrentChapter(-1);
    expect(useKernelStore.getState().currentChapter).toBe(0);
    setCurrentChapter(99);
    expect(useKernelStore.getState().currentChapter).toBe(10);
  });

  it('setMode transitions correctly', () => {
    const { setMode } = useKernelStore.getState();
    setMode('idle');
    expect(useKernelStore.getState().mode).toBe('idle');
    setMode('scrolling');
    expect(useKernelStore.getState().mode).toBe('scrolling');
  });

  it('completePreloader sets flag and mode', () => {
    const { completePreloader } = useKernelStore.getState();
    completePreloader();
    const state = useKernelStore.getState();
    expect(state.preloaderComplete).toBe(true);
    expect(state.loadProgress).toBe(1);
    expect(state.mode).toBe('idle');
  });

  it('setQualityTier updates tier', () => {
    const { setQualityTier } = useKernelStore.getState();
    setQualityTier('balanced');
    expect(useKernelStore.getState().qualityTier).toBe('balanced');
    setQualityTier('low');
    expect(useKernelStore.getState().qualityTier).toBe('low');
  });

  it('setPointer normalizes coordinates', () => {
    const { setPointer } = useKernelStore.getState();
    setPointer(0.3, 0.7);
    const state = useKernelStore.getState();
    expect(state.pointerX).toBe(0.3);
    expect(state.pointerY).toBe(0.7);
  });

  it('setScrollVelocity clamps to -1..1', () => {
    const { setScrollVelocity } = useKernelStore.getState();
    setScrollVelocity(0.5);
    expect(useKernelStore.getState().scrollVelocity).toBe(0.5);
    setScrollVelocity(3.0);
    expect(useKernelStore.getState().scrollVelocity).toBe(1.0);
    setScrollVelocity(-5.0);
    expect(useKernelStore.getState().scrollVelocity).toBe(-1.0);
  });
});
