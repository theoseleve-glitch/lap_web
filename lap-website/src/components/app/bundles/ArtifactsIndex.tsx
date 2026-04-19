'use client';

import { BACKEND_URL } from '@/lib/api-client';
import type { BundleArtifactRef } from '@/types/bundles';

const ROLE_LABELS: Record<string, string> = {
  telemetry: 'Telemetry Data',
  analysis_json: 'Analysis Metadata',
  manifest: 'Bundle Manifest',
  aux: 'Auxiliary File',
};

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  artifacts: BundleArtifactRef[];
  bundleId: string;
}

export function ArtifactsIndex({ artifacts, bundleId }: Props) {
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
      <ul className="space-y-2">
        {artifacts.map((a) => (
          <li
            key={a.path}
            className="flex items-center justify-between text-sm py-1.5 border-b border-steel/5 last:border-0"
          >
            <div>
              <span className="font-body text-chalk">
                {ROLE_LABELS[a.role] ?? a.role}
              </span>
              <span className="ml-2 font-telemetry text-steel text-xs">
                {formatBytes(a.size_bytes)}
              </span>
            </div>
            <a
              href={`${BACKEND_URL}${a.download_url}`}
              className="text-gold font-telemetry text-xs hover:text-gold/80 transition-colors"
              download
            >
              Download
            </a>
          </li>
        ))}
      </ul>
    </div>
  );
}
