import type { PanelSpec } from '@/lib/panel-registry';
import { CoachingPanel } from './CoachingPanel';
import { OptimizerPanel } from './OptimizerPanel';

export const DEFAULT_PANELS: readonly PanelSpec[] = [
  { id: 'coaching', component: CoachingPanel, requires: [], order: 10, label: 'Coaching' },
  { id: 'optimizer', component: OptimizerPanel, requires: [], order: 20, label: 'Optimizer' },
];
