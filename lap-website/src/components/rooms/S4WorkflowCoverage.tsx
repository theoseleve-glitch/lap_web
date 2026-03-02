'use client';

import Link from 'next/link';
import { workflowModules } from '@/data/workflow-modules';
import type { WorkflowModule } from '@/data/workflow-modules';
import { StatusPill } from '@/components/site/StatusPill';
import { ReversibleCard } from '@/components/ui/ReversibleCard';
import { TrackCard } from '@/components/ui/TrackCard';
import { useTranslation } from '@/i18n';

const WORKFLOW_TRANSLATION_MAP: Record<string, { titleKey: string; summaryKey: string; stepKeys: string[] }> = {
  'upload-analyze': {
    titleKey: 'workflow.uploadAnalyze.title',
    summaryKey: 'workflow.uploadAnalyze.summary',
    stepKeys: ['workflow.uploadAnalyze.step1', 'workflow.uploadAnalyze.step2', 'workflow.uploadAnalyze.step3', 'workflow.uploadAnalyze.step4'],
  },
  'session-intelligence': {
    titleKey: 'workflow.sessionIntelligence.title',
    summaryKey: 'workflow.sessionIntelligence.summary',
    stepKeys: ['workflow.sessionIntelligence.step1', 'workflow.sessionIntelligence.step2', 'workflow.sessionIntelligence.step3', 'workflow.sessionIntelligence.step4', 'workflow.sessionIntelligence.step5'],
  },
  'comparison-progress': {
    titleKey: 'workflow.comparisonProgress.title',
    summaryKey: 'workflow.comparisonProgress.summary',
    stepKeys: ['workflow.comparisonProgress.step1', 'workflow.comparisonProgress.step2', 'workflow.comparisonProgress.step3'],
  },
  'coaching-plans': {
    titleKey: 'workflow.coachingPlans.title',
    summaryKey: 'workflow.coachingPlans.summary',
    stepKeys: ['workflow.coachingPlans.step1', 'workflow.coachingPlans.step2', 'workflow.coachingPlans.step3'],
  },
  'visualization-workspace': {
    titleKey: 'workflow.vizWorkspace.title',
    summaryKey: 'workflow.vizWorkspace.summary',
    stepKeys: ['workflow.vizWorkspace.step1', 'workflow.vizWorkspace.step2', 'workflow.vizWorkspace.step3', 'workflow.vizWorkspace.step4'],
  },
  'strategy-control-room': {
    titleKey: 'workflow.strategyRoom.title',
    summaryKey: 'workflow.strategyRoom.summary',
    stepKeys: ['workflow.strategyRoom.step1', 'workflow.strategyRoom.step2', 'workflow.strategyRoom.step3', 'workflow.strategyRoom.step4'],
  },
  'data-management': {
    titleKey: 'workflow.dataManagement.title',
    summaryKey: 'workflow.dataManagement.summary',
    stepKeys: ['workflow.dataManagement.step1', 'workflow.dataManagement.step2', 'workflow.dataManagement.step3', 'workflow.dataManagement.step4'],
  },
  'account-team': {
    titleKey: 'workflow.accountTeam.title',
    summaryKey: 'workflow.accountTeam.summary',
    stepKeys: ['workflow.accountTeam.step1', 'workflow.accountTeam.step2', 'workflow.accountTeam.step3'],
  },
  'data-rights': {
    titleKey: 'workflow.dataRights.title',
    summaryKey: 'workflow.dataRights.summary',
    stepKeys: ['workflow.dataRights.step1', 'workflow.dataRights.step2', 'workflow.dataRights.step3'],
  },
};

const GROUP_ORDER: WorkflowModule['group'][] = [
  'engineer',
  'strategist',
  'operations',
];

const GROUP_LABEL_KEYS: Record<WorkflowModule['group'], { labelKey: string; color: string }> = {
  engineer: { labelKey: 'home.workflow.groupEngineer', color: 'text-chalk' },
  strategist: { labelKey: 'home.workflow.groupStrategist', color: 'text-gold' },
  operations: { labelKey: 'home.workflow.groupOperations', color: 'text-steel' },
};

export function S4WorkflowCoverage() {
  const { t } = useTranslation();

  return (
    <section
      id="s4-workflows"
      data-accent="yellow"
      className="room relative py-16 md:py-24 border-t border-chalk/15"
      aria-label="Workflow coverage"
    >
      <div className="grid-lap">
        <div className="col-span-full mb-8">
          <h2 className="font-monument text-[clamp(42px,7vw,76px)] leading-[0.9]">
            {t('home.workflow.heading1')}
            <br />
            {t('home.workflow.heading2')}
          </h2>
          <ReversibleCard
            title={t('home.workflow.cardTitle')}
            description={t('home.workflow.cardDescription')}
            className="max-w-2xl mt-4"
          />
        </div>

        {GROUP_ORDER.map((group) => {
          const modules = workflowModules.filter((m) => m.group === group);
          if (modules.length === 0) return null;
          const { labelKey, color } = GROUP_LABEL_KEYS[group];

          return (
            <div key={group} className="col-span-full mb-8">
              <h3
                className={`font-monument text-[var(--text-h3)] ${color} mb-4`}
              >
                {t(labelKey)}
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {modules.map((module) => {
                  const translationInfo = WORKFLOW_TRANSLATION_MAP[module.id];
                  const title = translationInfo ? t(translationInfo.titleKey) : module.title;
                  const summary = translationInfo ? t(translationInfo.summaryKey) : module.summary;
                  const steps = translationInfo
                    ? translationInfo.stepKeys.map((key) => t(key))
                    : module.steps;

                  return (
                    <TrackCard
                      key={module.id}
                      title={title}
                      description={summary}
                    >
                      <div className="flex items-start justify-between gap-3 mb-2">
                        <StatusPill status={module.status} />
                      </div>
                      <ul className="space-y-1 text-xs text-chalk">
                        {steps.slice(0, 3).map((step) => (
                          <li key={step}>- {step}</li>
                        ))}
                      </ul>
                    </TrackCard>
                  );
                })}
              </div>
            </div>
          );
        })}

        <div className="col-span-full mt-6">
          <Link
            href="/product"
            className="inline-flex items-center border border-gold px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase text-gold hover:bg-gold hover:text-asphalt transition-colors duration-[420ms]"
          >
            {t('cta.openFullProduct')}
          </Link>
        </div>
      </div>
    </section>
  );
}
