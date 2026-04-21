import { describe, it, expect } from 'vitest';
import type { ComponentType } from 'react';
import type { ChannelTag, SessionCapabilities } from '@/types/contracts';
import { selectPanels, type PanelSpec, type PanelContext } from './panel-registry';

const Stub: ComponentType<PanelContext> = () => null;

const P = (id: string, requires: ChannelTag[], order: number): PanelSpec => ({
  id, requires, order, label: id, component: Stub,
});

describe('selectPanels', () => {
  it('returns panels whose requirements are a subset of channels, sorted by order', () => {
    const panels = [
      P('coaching',  [],                         10),
      P('optimizer', [],                         20),
      P('inputs',    ['throttle', 'brake'],      30),
      P('shocks',    ['shock_defl'],             40),
    ];
    const caps: SessionCapabilities = { channels: ['gps', 'lat_g', 'throttle', 'brake'] };
    const result = selectPanels(panels, caps);
    expect(result.map((p) => p.id)).toEqual(['coaching', 'optimizer', 'inputs']);
  });

  it('excludes panels when any single required channel is missing', () => {
    const panels = [P('inputs', ['throttle', 'brake', 'steer'], 10)];
    const caps: SessionCapabilities = { channels: ['throttle', 'brake'] };
    expect(selectPanels(panels, caps)).toEqual([]);
  });

  it('handles missing channels list as empty set', () => {
    const panels = [P('always', [], 10), P('needs', ['gps'], 20)];
    const result = selectPanels(panels, {});
    expect(result.map((p) => p.id)).toEqual(['always']);
  });

  it('does not mutate input array', () => {
    const panels = [P('b', [], 20), P('a', [], 10)];
    const snapshot = [...panels];
    selectPanels(panels, { channels: [] });
    expect(panels).toEqual(snapshot);
  });
});
