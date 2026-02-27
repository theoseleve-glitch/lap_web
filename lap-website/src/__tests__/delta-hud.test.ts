import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';

describe('DeltaHud store integration', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('delta jitter starts at 8 and can be reduced', () => {
    expect(useKernelStore.getState().hudDelta.jitter).toBe(8);
    useKernelStore.getState().setDeltaJitter(4);
    expect(useKernelStore.getState().hudDelta.jitter).toBe(4);
  });

  it('settling freezes jitter at 0', () => {
    useKernelStore.getState().settleDelta();
    const { hudDelta } = useKernelStore.getState();
    expect(hudDelta.settled).toBe(true);
    expect(hudDelta.jitter).toBe(0);
  });
});
