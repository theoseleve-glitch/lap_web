import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';
import { tickDrs } from '@/experience/narrative/DrsController';

describe('DRS tick logic', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('tickDrs does nothing when DRS inactive', () => {
    tickDrs(16);
    expect(useKernelStore.getState().drs.active).toBe(false);
  });

  it('tickDrs decrements remaining time', () => {
    useKernelStore.getState().activateDrs('test');
    tickDrs(100);
    expect(useKernelStore.getState().drs.remaining).toBe(1900);
    expect(useKernelStore.getState().drs.active).toBe(true);
  });

  it('tickDrs deactivates when remaining reaches 0', () => {
    useKernelStore.getState().activateDrs('test');
    tickDrs(2000);
    expect(useKernelStore.getState().drs.active).toBe(false);
    expect(useKernelStore.getState().drs.multiplier).toBe(1.0);
  });

  it('tickDrs decays multiplier in final 500ms', () => {
    useKernelStore.getState().activateDrs('test');
    tickDrs(1600);
    const drs = useKernelStore.getState().drs;
    expect(drs.remaining).toBe(400);
    expect(drs.multiplier).toBeLessThan(1.4);
    expect(drs.multiplier).toBeGreaterThan(1.0);
  });
});
