import { describe, it, expect, beforeEach } from 'vitest';
import { useKernelStore } from '@/experience/state/store';

describe('TimingTower store integration', () => {
  beforeEach(() => {
    useKernelStore.setState(useKernelStore.getInitialState());
  });

  it('initial tower has 8 pending sectors', () => {
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors).toHaveLength(8);
    expect(hudTower.sectors.every(s => s.status === 'pending')).toBe(true);
  });

  it('completing a sector turns it purple', () => {
    useKernelStore.getState().completeSector(0);
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors[0].status).toBe('completed');
    expect(hudTower.sectors[0].color).toBe('#D946EF');
  });

  it('sector progress updates independently', () => {
    useKernelStore.getState().setSectorProgress(2, 0.75);
    const { hudTower } = useKernelStore.getState();
    expect(hudTower.sectors[2].progress).toBe(0.75);
  });
});
