import Link from 'next/link';
import { workflowModules } from '@/data/workflow-modules';
import { StatusPill } from '@/components/site/StatusPill';
import { ReversibleCard } from '@/components/ui/ReversibleCard';

export function S4WorkflowCoverage() {
  return (
    <section
      id="s4-workflows"
      data-accent="yellow"
      className="room relative py-16 md:py-24 border-t border-steel/20"
      aria-label="Workflow coverage"
    >
      <div className="grid-lap">
        <div className="col-span-full mb-8">
          <h2 className="font-monument text-[clamp(42px,7vw,76px)] leading-[0.9]">
            WORKFLOW
            <br />
            COVERAGE
          </h2>
          <ReversibleCard
            title="Workflow Clarity"
            description="Every module is mapped to live capability status, so buyers know exactly what is ready now, enterprise-only, or still roadmap."
            className="max-w-2xl mt-4"
          />
        </div>

        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 gap-4">
          {workflowModules.map((module) => (
            <article key={module.id} className="border border-steel/20 bg-concrete/40 p-4">
              <div className="flex items-start justify-between gap-3 mb-2">
                <h3 className="font-monument text-[var(--text-h3)]">{module.title}</h3>
                <StatusPill status={module.status} />
              </div>
              <p className="text-sm text-steel mb-3">{module.summary}</p>
              <ul className="space-y-1 text-xs text-chalk">
                {module.steps.slice(0, 3).map((step) => (
                  <li key={step}>- {step}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>

        <div className="col-span-full mt-6">
          <Link
            href="/product"
            className="inline-flex items-center border border-pit-orange px-4 py-2 font-telemetry text-[11px] tracking-[0.12em] uppercase"
          >
            OPEN FULL PRODUCT WORKFLOWS
          </Link>
        </div>
      </div>
    </section>
  );
}
