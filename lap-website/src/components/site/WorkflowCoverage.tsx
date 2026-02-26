'use client';

import { useState } from 'react';
import { workflowModules } from '@/data/workflow-modules';
import { StatusPill } from '@/components/site/StatusPill';

const sessionTabs = ['Overview', 'Corners', 'Timeline', 'Analytics', 'Lap Data'] as const;

export function WorkflowCoverage() {
  const [activeTab, setActiveTab] = useState<(typeof sessionTabs)[number]>('Overview');

  return (
    <div className="space-y-6">
      {workflowModules.map((module) => (
        <article key={module.id} className="border border-steel/20 bg-concrete/50 p-5 md:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
            <h2 className="font-monument text-[clamp(26px,4vw,38px)]">{module.title}</h2>
            <StatusPill status={module.status} />
          </div>
          <p className="text-steel mb-4">{module.summary}</p>

          {module.id === 'session-intelligence' ? (
            <div className="border border-steel/20">
              <div className="flex flex-wrap border-b border-steel/20">
                {sessionTabs.map((tab) => (
                  <button
                    key={tab}
                    type="button"
                    className={`px-3 py-2 text-xs font-telemetry tracking-[0.12em] uppercase ${
                      activeTab === tab ? 'text-chalk bg-asphalt' : 'text-steel hover:text-chalk'
                    }`}
                    onClick={() => setActiveTab(tab)}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <div className="p-4 text-sm text-steel">
                Previewing <span className="text-chalk">{activeTab}</span> tab content for a live
                telemetry session debrief.
              </div>
            </div>
          ) : (
            <ol className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {module.steps.map((step, index) => (
                <li
                  key={step}
                  className="border border-steel/20 bg-asphalt/40 px-3 py-2 text-sm text-chalk"
                >
                  <span className="font-telemetry text-steel mr-2">{String(index + 1).padStart(2, '0')}</span>
                  {step}
                </li>
              ))}
            </ol>
          )}
        </article>
      ))}
    </div>
  );
}
