import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { getTransitionType, transitionMap } from '@/experience/transitions/TransitionLibrary';
import { rooms } from '@/lib/tokens';

describe('Kernel Integration', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('rooms array has 11 entries matching expected chapter IDs', () => {
    expect(rooms).toHaveLength(11);
    expect(rooms[0].id).toBe('start-grid');
    expect(rooms[10].id).toBe('podium');
  });

  it('transition map covers all adjacent room pairs', () => {
    for (let i = 0; i < rooms.length - 1; i++) {
      const from = rooms[i].id;
      const to = rooms[i + 1].id;
      const type = getTransitionType(from, to);
      expect(type).not.toBe('none');
      expect(['crossfade-blur', 'mask-wipe', 'velocity-warp', 'refraction']).toContain(type);
    }
  });

  it('transition map has exactly 10 entries (11 rooms - 1)', () => {
    expect(Object.keys(transitionMap)).toHaveLength(10);
  });

  it('preloader complete transitions to idle mode', () => {
    expect(useKernelStore.getState().mode).toBe('preloading');
    useKernelStore.getState().completePreloader();
    expect(useKernelStore.getState().mode).toBe('idle');
    expect(useKernelStore.getState().preloaderComplete).toBe(true);
  });

  it('quality tier cascades correctly', () => {
    const { setQualityTier } = useKernelStore.getState();
    setQualityTier('balanced');
    expect(useKernelStore.getState().qualityTier).toBe('balanced');
    setQualityTier('low');
    expect(useKernelStore.getState().qualityTier).toBe('low');
  });

  it('chapter navigation updates current chapter', () => {
    const { setCurrentChapter, setChapterProgress } = useKernelStore.getState();
    setCurrentChapter(5);
    setChapterProgress(0.75);
    expect(useKernelStore.getState().currentChapter).toBe(5);
    expect(useKernelStore.getState().chapterProgress).toBe(0.75);
  });

  it('scroll velocity is clamped to [-1, 1]', () => {
    const { setScrollVelocity } = useKernelStore.getState();
    setScrollVelocity(5);
    expect(useKernelStore.getState().scrollVelocity).toBe(1);
    setScrollVelocity(-3);
    expect(useKernelStore.getState().scrollVelocity).toBe(-1);
  });

  it('fallback transition is crossfade-blur for unknown pairs', () => {
    expect(getTransitionType('unknown-from', 'unknown-to')).toBe('crossfade-blur');
  });
});
