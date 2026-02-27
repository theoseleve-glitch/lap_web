'use client';

import { useState } from 'react';
import { workflowModules } from '@/data/workflow-modules';
import { StatusPill } from '@/components/site/StatusPill';
import { useTranslation } from '@/i18n';

const GROUP_META = {
  engineer: { color: 'text-acid-green', border: 'border-acid-green/30', bg: 'bg-acid-green/5' },
  strategist: { color: 'text-pit-orange', border: 'border-pit-orange/30', bg: 'bg-pit-orange/5' },
  operations: { color: 'text-steel', border: 'border-steel/30', bg: 'bg-steel/5' },
} as const;

const groups = ['engineer', 'strategist', 'operations'] as const;

export function WorkflowCoverage() {
  const { t } = useTranslation();
  const [activeModule, setActiveModule] = useState(workflowModules[0].id);
  const active = workflowModules.find((m) => m.id === activeModule) ?? workflowModules[0];

  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-3">
        <span className="font-monument text-[clamp(32px,5vw,48px)] text-chalk">{workflowModules.length}</span>
        <span className="text-steel text-sm uppercase tracking-[0.12em] font-telemetry">
          {t('workflow.moduleCount', 'workflow modules')}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {groups.map((group) => {
          const meta = GROUP_META[group];
          const modules = workflowModules.filter((m) => m.group === group);
          return (
            <div key={group}>
              <h3 className={`font-monument text-xs uppercase tracking-[0.15em] mb-3 ${meta.color}`}>
                {t(`workflow.group.${group}`, group)}
              </h3>
              <div className="space-y-2">
                {modules.map((mod) => (
                  <button
                    key={mod.id}
                    type="button"
                    className={`w-full text-left px-3 py-2.5 border transition-all duration-300 ${
                      activeModule === mod.id
                        ? `${meta.border} ${meta.bg}`
                        : 'border-steel/15 hover:border-steel/30'
                    }`}
                    onClick={() => setActiveModule(mod.id)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className={`text-sm ${activeModule === mod.id ? 'text-chalk' : 'text-steel'}`}>
                        {t(`workflow.${mod.id}.title`, mod.title)}
                      </span>
                      <StatusPill status={mod.status} />
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      <div className="border border-steel/20 bg-concrete/30 p-5">
        <h3 className="font-monument text-[var(--text-h3)] mb-2">
          {t(`workflow.${active.id}.title`, active.title)}
        </h3>
        <p className="text-steel mb-4">{t(`workflow.${active.id}.summary`, active.summary)}</p>
        <ol className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {active.steps.map((step, i) => (
            <li key={step} className="border border-steel/20 bg-asphalt/40 px-3 py-2 text-sm text-chalk">
              <span className="font-telemetry text-steel mr-2">{String(i + 1).padStart(2, '0')}</span>
              {t(`workflow.${active.id}.step.${i}`, step)}
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
