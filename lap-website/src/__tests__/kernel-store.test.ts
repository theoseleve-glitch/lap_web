import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { colors } from '@/lib/tokens';

describe('KernelStore', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes with default state', () => {
    // NOTE: Preloader (src/experience/preloader/Preloader.tsx) is orphaned —
    // never mounted anywhere in the app — so the store boots straight into
    // 'idle' with the preloader already marked complete (see store.ts
    // initialState), not a 'preloading' gate.
    const state = useKernelStore.getState();
    expect(state.currentChapter).toBe(0);
    expect(state.mode).toBe('idle');
    expect(state.qualityTier).toBe('high');
    expect(state.preloaderComplete).toBe(true);
    expect(state.loadProgress).toBe(1);
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

describe('Extended KernelStore — HUD state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes HUD tower with 8 sectors all pending', () => {
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors).toHaveLength(8);
    expect(hudTower.sectors[0].status).toBe('pending');
    expect(hudTower.activeSectorIndex).toBe(0);
  });

  it('completeSector marks sector completed with purple color', () => {
    const { completeSector } = useKernelStore.getState();
    completeSector(0);
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors[0].status).toBe('completed');
    expect(hudTower.sectors[0].color).toBe(colors.racingPurple);
    expect(hudTower.activeSectorIndex).toBe(1);
  });

  it('setSectorProgress updates progress for active sector', () => {
    const { setSectorProgress } = useKernelStore.getState();
    setSectorProgress(0, 0.5);
    expect(useKernelStore.getState().hudTower.sectors[0].progress).toBe(0.5);
  });

  it('initializes delta HUD state', () => {
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.value).toBe(0);
    expect(hudDelta.jitter).toBe(8);
    expect(hudDelta.settled).toBe(false);
  });

  it('setDeltaValue updates delta', () => {
    const { setDeltaValue } = useKernelStore.getState();
    setDeltaValue(-0.15);
    expect(useKernelStore.getState().hudDelta.value).toBe(-0.15);
  });

  it('setDeltaJitter clamps to 0-8', () => {
    const { setDeltaJitter } = useKernelStore.getState();
    setDeltaJitter(4);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(4);
    setDeltaJitter(-1);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(0);
    setDeltaJitter(20);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(8);
  });

  it('settleDelta freezes delta', () => {
    const { setDeltaValue, settleDelta } = useKernelStore.getState();
    setDeltaValue(-0.05);
    settleDelta();
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.settled).toBe(true);
    expect(hudDelta.jitter).toBe(0);
  });
});

describe('Extended KernelStore — reveal state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes reveal state', () => {
    const { reveal } = useKernelStore.getState();
    expect(reveal.maskCoverage).toBe(0);
    expect(reveal.brushRadius).toBe(80);
    expect(reveal.active).toBe(true);
  });

  it('setMaskCoverage clamps to 0-1', () => {
    const { setMaskCoverage } = useKernelStore.getState();
    setMaskCoverage(0.5);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(0.5);
    setMaskCoverage(2.0);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(1.0);
    setMaskCoverage(-1);
    expect(useKernelStore.getState().reveal.maskCoverage).toBe(0);
  });

  it('setRevealActive toggles reveal', () => {
    const { setRevealActive } = useKernelStore.getState();
    setRevealActive(false);
    expect(useKernelStore.getState().reveal.active).toBe(false);
  });
});

describe('Extended KernelStore — DRS state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes DRS as inactive', () => {
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(false);
    expect(drs.multiplier).toBe(1.0);
  });

  it('activateDrs sets active state with trigger', () => {
    const { activateDrs } = useKernelStore.getState();
    activateDrs('sector-gate');
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(true);
    expect(drs.remaining).toBe(2000);
    expect(drs.multiplier).toBe(1.4);
    expect(drs.trigger).toBe('sector-gate');
  });

  it('deactivateDrs resets to baseline', () => {
    const { activateDrs, deactivateDrs } = useKernelStore.getState();
    activateDrs('test');
    deactivateDrs();
    const { drs } = useKernelStore.getState();
    expect(drs.active).toBe(false);
    expect(drs.multiplier).toBe(1.0);
    expect(drs.remaining).toBe(0);
  });
});

describe('Extended KernelStore — track path state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes track path', () => {
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.heading).toBe(0);
    expect(trackPath.headingDelta).toBe(0);
    expect(trackPath.isCorner).toBe(false);
    expect(trackPath.pitMode).toBe(false);
    expect(trackPath.velocityMultiplier).toBe(1.0);
  });

  it('setTrackPath updates all path fields', () => {
    const { setTrackPath } = useKernelStore.getState();
    setTrackPath({ heading: 35, headingDelta: 35, isCorner: true });
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.heading).toBe(35);
    expect(trackPath.headingDelta).toBe(35);
    expect(trackPath.isCorner).toBe(true);
  });

  it('setPitMode toggles pit limiter', () => {
    const { setPitMode } = useKernelStore.getState();
    setPitMode(true);
    const { trackPath } = useKernelStore.getState();
    expect(trackPath.pitMode).toBe(true);
    expect(trackPath.velocityMultiplier).toBe(0.3);
  });

  it('setPitMode false restores velocity multiplier', () => {
    const { setPitMode } = useKernelStore.getState();
    setPitMode(true);
    setPitMode(false);
    expect(useKernelStore.getState().trackPath.velocityMultiplier).toBe(1.0);
  });
});

describe('Extended KernelStore — finish state', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initializes finish state', () => {
    const { finish } = useKernelStore.getState();
    expect(finish.crossed).toBe(false);
    expect(finish.finalDelta).toBe(0);
  });

  it('crossFinishLine sets crossed and freezes delta', () => {
    const { setDeltaValue, crossFinishLine } = useKernelStore.getState();
    setDeltaValue(-0.23);
    crossFinishLine();
    const { finish, hudDelta } = useKernelStore.getState();
    expect(finish.crossed).toBe(true);
    expect(finish.finalDelta).toBe(-0.23);
    expect(hudDelta.settled).toBe(true);
  });
});
