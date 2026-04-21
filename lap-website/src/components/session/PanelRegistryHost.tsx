import { selectPanels, type PanelContext } from '@/lib/panel-registry';
import { DEFAULT_PANELS } from './panels';

export function PanelRegistryHost(ctx: PanelContext) {
  const panels = selectPanels(DEFAULT_PANELS, ctx.session.capabilities);
  return (
    <div className="space-y-4">
      {panels.map(({ id, component: Component }) => (
        <Component key={id} {...ctx} />
      ))}
    </div>
  );
}
