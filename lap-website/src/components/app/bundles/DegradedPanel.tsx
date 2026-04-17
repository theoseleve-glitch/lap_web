'use client';

import type { ReadinessSummary } from '@/types/bundles';
import { ReadinessChecklist } from './ReadinessChecklist';

interface Props {
  readiness: ReadinessSummary;
}

export function DegradedPanel({ readiness }: Props) {
  return (
    <div className="rounded-xl border border-marshal-yellow/30 bg-marshal-yellow/5 p-5">
      <h3 className="text-sm font-monument text-marshal-yellow mb-3">
        Incomplete Session Data
      </h3>
      <p className="text-sm font-body text-steel mb-4">
        This bundle was accepted but is missing required fields for analysis.
        Re-export from the logger with complete metadata.
      </p>
      <ReadinessChecklist readiness={readiness} />
    </div>
  );
}
