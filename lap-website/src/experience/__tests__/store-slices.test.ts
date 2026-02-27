import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '../state/store';

describe('Background slice', () => {
  beforeEach(() => {
    useKernelStore.setState({
      background: { cornerYaw: 0, cornerBank: 0, streakIntensity: 0, ribbonProgress: 0 },
    });
  });

  it('setCornerYaw updates yaw', () => {
    useKernelStore.getState().setCornerYaw(3.5);
    expect(useKernelStore.getState().background.cornerYaw).toBe(3.5);
  });

  it('setCornerBank updates bank', () => {
    useKernelStore.getState().setCornerBank(-1.5);
    expect(useKernelStore.getState().background.cornerBank).toBe(-1.5);
  });

  it('setStreakIntensity clamps to 0-1', () => {
    useKernelStore.getState().setStreakIntensity(1.5);
    expect(useKernelStore.getState().background.streakIntensity).toBe(1);
    useKernelStore.getState().setStreakIntensity(-0.5);
    expect(useKernelStore.getState().background.streakIntensity).toBe(0);
  });

  it('setStreakIntensity accepts values in range', () => {
    useKernelStore.getState().setStreakIntensity(0.7);
    expect(useKernelStore.getState().background.streakIntensity).toBe(0.7);
  });

  it('setRibbonProgress clamps to 0-1', () => {
    useKernelStore.getState().setRibbonProgress(2.0);
    expect(useKernelStore.getState().background.ribbonProgress).toBe(1);
    useKernelStore.getState().setRibbonProgress(-1.0);
    expect(useKernelStore.getState().background.ribbonProgress).toBe(0);
  });
});

describe('SafetyCar slice', () => {
  beforeEach(() => {
    useKernelStore.setState({
      safetyCar: { active: false, reason: '', enteredAt: 0 },
    });
  });

  it('enterSafetyCar sets active + reason + timestamp', () => {
    const before = Date.now();
    useKernelStore.getState().enterSafetyCar('low-fps');
    const sc = useKernelStore.getState().safetyCar;
    expect(sc.active).toBe(true);
    expect(sc.reason).toBe('low-fps');
    expect(sc.enteredAt).toBeGreaterThanOrEqual(before);
  });

  it('exitSafetyCar clears state', () => {
    useKernelStore.getState().enterSafetyCar('test');
    useKernelStore.getState().exitSafetyCar();
    const sc = useKernelStore.getState().safetyCar;
    expect(sc.active).toBe(false);
    expect(sc.reason).toBe('');
    expect(sc.enteredAt).toBe(0);
  });

  it('enterSafetyCar with webgl-context-lost reason', () => {
    useKernelStore.getState().enterSafetyCar('webgl-context-lost');
    expect(useKernelStore.getState().safetyCar.reason).toBe('webgl-context-lost');
  });
});

describe('Asset slice', () => {
  beforeEach(() => {
    useKernelStore.setState({
      assets: { loaded: {}, visible: {} },
    });
  });

  it('setAssetLoaded tracks individual assets', () => {
    useKernelStore.getState().setAssetLoaded('helmet', true);
    expect(useKernelStore.getState().assets.loaded['helmet']).toBe(true);
    expect(useKernelStore.getState().assets.loaded['tire']).toBeUndefined();
  });

  it('setAssetLoaded can unload assets', () => {
    useKernelStore.getState().setAssetLoaded('helmet', true);
    useKernelStore.getState().setAssetLoaded('helmet', false);
    expect(useKernelStore.getState().assets.loaded['helmet']).toBe(false);
  });

  it('setAssetVisible tracks visibility', () => {
    useKernelStore.getState().setAssetVisible('halo', true);
    expect(useKernelStore.getState().assets.visible['halo']).toBe(true);
  });

  it('multiple assets tracked independently', () => {
    useKernelStore.getState().setAssetLoaded('helmet', true);
    useKernelStore.getState().setAssetLoaded('tire', true);
    useKernelStore.getState().setAssetLoaded('halo', false);
    const { loaded } = useKernelStore.getState().assets;
    expect(loaded['helmet']).toBe(true);
    expect(loaded['tire']).toBe(true);
    expect(loaded['halo']).toBe(false);
  });
});
