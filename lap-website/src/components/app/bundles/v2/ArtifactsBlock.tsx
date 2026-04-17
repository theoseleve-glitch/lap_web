'use client';

import { BACKEND_URL } from '@/lib/api-client';
import type { ArtifactPresentation } from '@/lib/api/bundles/types';

const ROLE_LABELS: Record<string, string> = {
  telemetry: 'Telemetry Data',
  analysis_json: 'Analysis Metadata',
  manifest: 'Bundle Manifest',
  aux: 'Auxiliary File',
  summary: 'Session Summary',
  surface_field: 'Surface Field',
  confidence_heatmap: 'Confidence Heatmap',
  planner_nominal: 'Standard Strategy',
  planner_robust: 'Safe Strategy',
  planner_exploitable: 'Race Strategy',
  racing_line_deltas: 'Racing Line Deltas',
  diagnostics: 'Diagnostics',
};

const STATE_ICONS: Record<string, { icon: string; color: string }> = {
  available: { icon: '\u2713', color: 'text-acid-green' },
  unavailable: { icon: '\u2717', color: 'text-steel/40' },
  gated: { icon: '\u26BF', color: 'text-marshal-yellow' },
  pending: { icon: '\u23F3', color: 'text-gold' },
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  artifacts: ArtifactPresentation[];
}

export function ArtifactsBlock({ artifacts }: Props) {
  if (artifacts.length === 0) {
    return (
      <div className="rounded-xl border border-steel/10 bg-concrete p-5">
        <p className="text-sm font-body text-steel">No artifacts available.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-steel/10 bg-concrete p-5">
      <h3 className="text-sm font-monument text-chalk mb-3">Files</h3>
      <ul className="space-y-1.5">
        {artifacts.map((a) => {
          const stateInfo = STATE_ICONS[a.state] ?? STATE_ICONS.unavailable;
          return (
            <li
              key={a.role}
              className="flex items-center justify-between text-sm py-1.5 border-b border-steel/5 last:border-0"
            >
              <div className="flex items-center gap-2 min-w-0">
                <span className={stateInfo.color}>{stateInfo.icon}</span>
                <span className={`font-body ${a.state === 'available' ? 'text-chalk' : 'text-steel/50'}`}>
                  {ROLE_LABELS[a.role] ?? a.role}
                </span>
                <span className="font-telemetry text-steel text-xs">{formatBytes(a.sizeBytes)}</span>
              </div>

              <div className="flex-shrink-0 ml-3">
                {a.state === 'available' && a.downloadUrl && (
                  <a
                    href={`${BACKEND_URL}${a.downloadUrl}`}
                    className="text-gold font-telemetry text-xs hover:text-gold/80 transition-colors"
                    download
                  >
                    Download
                  </a>
                )}
                {a.gateReason && (
                  <span className="text-steel/40 font-telemetry text-xs" title={a.gateReason}>
                    {a.state === 'gated' ? 'Locked' : a.state === 'pending' ? 'Pending' : 'Unavailable'}
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
