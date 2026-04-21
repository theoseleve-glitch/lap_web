import type { ComponentType } from 'react';
import type {
  ChannelTag,
  CoachingContract,
  OptimizerContract,
  SessionCapabilities,
  SessionContract,
} from '@/types/contracts';

export interface PanelContext {
  session: SessionContract;
  coaching: CoachingContract | null;
  optimizer: OptimizerContract | null;
}

export interface PanelSpec {
  id: string;
  component: ComponentType<PanelContext>;
  requires: ChannelTag[];
  order: number;
  label: string;
}

export function selectPanels(
  panels: readonly PanelSpec[],
  capabilities: SessionCapabilities,
): PanelSpec[] {
  const channels = new Set<ChannelTag>(capabilities.channels ?? []);
  return [...panels]
    .filter((p) => p.requires.every((tag) => channels.has(tag)))
    .sort((a, b) => a.order - b.order);
}
