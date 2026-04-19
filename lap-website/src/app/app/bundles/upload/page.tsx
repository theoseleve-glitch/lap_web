'use client';

import { useRouter } from 'next/navigation';
import { useCallback } from 'react';
import type { IntakeResult } from '@/types/bundles';
import { BundleUploadPanel } from '@/components/app/bundles/BundleUploadPanel';

export default function BundleUploadPage() {
  const router = useRouter();

  const handleSuccess = useCallback(
    (result: IntakeResult) => {
      router.push(`/app/bundles/${result.bundle_id}`);
    },
    [router],
  );

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <h1 className="text-xl font-monument text-chalk mb-2">Upload Session Bundle</h1>
      <p className="text-sm font-body text-steel mb-6">
        Upload a session bundle (.zip) exported from the Lap logger.
        The bundle must include a manifest and telemetry data.
      </p>

      <BundleUploadPanel onSuccess={handleSuccess} />
    </div>
  );
}
