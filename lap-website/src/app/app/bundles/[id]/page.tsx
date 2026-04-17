'use client';

import { useParams } from 'next/navigation';
import {
  useBundleDetail,
  useBundleRun,
  useBundleArtifacts,
  useTriggerAnalysis,
  mapSessionPresentation,
  mapRunPresentation,
  mapArtifactPresentation,
} from '@/lib/api/bundles';
import type { ArtifactPresentation } from '@/lib/api/bundles/types';

import { IdentityBlock } from '@/components/app/bundles/v2/IdentityBlock';
import { ReadinessBlock } from '@/components/app/bundles/v2/ReadinessBlock';
import { RunBlock } from '@/components/app/bundles/v2/RunBlock';
import { ArtifactsBlock } from '@/components/app/bundles/v2/ArtifactsBlock';

export default function BundleDetailPage() {
  const params = useParams();
  const bundleId = params.id as string;

  const { data: bundleDTO, isLoading: bundleLoading } = useBundleDetail(bundleId);
  const { data: runDTO } = useBundleRun(bundleId);
  const { data: artifactsDTO } = useBundleArtifacts(bundleId);
  const triggerMutation = useTriggerAnalysis(bundleId);

  // ── Loading skeleton ──────────────────────────────────────
  if (bundleLoading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-4">
        <div className="h-40 rounded-xl bg-concrete animate-pulse" />
        <div className="h-32 rounded-xl bg-concrete animate-pulse" />
      </div>
    );
  }

  // ── Not found ─────────────────────────────────────────────
  if (!bundleDTO) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <div className="rounded-xl border border-safety-red/30 bg-safety-red/5 p-5">
          <p className="text-sm font-body text-safety-red">Session not found.</p>
        </div>
      </div>
    );
  }

  // ── Map to presentation types ─────────────────────────────
  const session = mapSessionPresentation(bundleDTO);
  const run = runDTO ? mapRunPresentation(runDTO) : null;

  // Enrich session with run data
  if (run) {
    session.supportTier = run.supportTier;
    session.runLifecycle = run.lifecycle;
    session.warnings = run.warnings;
  }

  const canAnalyze = session.readiness === 'ready';
  const availableKinds = runDTO?.artifacts_available ?? [];
  const artifacts: ArtifactPresentation[] = (artifactsDTO?.artifacts ?? []).map((a) =>
    mapArtifactPresentation(a, runDTO ?? null, availableKinds),
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Identity + Readiness */}
        <div className="space-y-4">
          <IdentityBlock session={session} />
          <ReadinessBlock session={session} />
        </div>

        {/* Right: Run + Artifacts */}
        <div className="space-y-4">
          <RunBlock
            run={run}
            onAnalyze={() => triggerMutation.mutate(false)}
            onRetry={() => triggerMutation.mutate(true)}
            isAnalyzing={triggerMutation.isPending}
            canAnalyze={canAnalyze}
          />
          {artifacts.length > 0 && <ArtifactsBlock artifacts={artifacts} />}
        </div>
      </div>
    </div>
  );
}
