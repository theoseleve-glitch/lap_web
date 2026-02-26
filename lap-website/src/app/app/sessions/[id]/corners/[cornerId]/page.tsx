'use client';

import { useParams } from 'next/navigation';
import { CornerReplay } from '@/components/app/corner-replay';

export default function CornerReplayPage() {
  const params = useParams<{ id: string; cornerId: string }>();
  const sessionId = params.id;
  const cornerId = parseInt(params.cornerId, 10);

  if (isNaN(cornerId)) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <p className="text-safety-red font-telemetry text-sm">Invalid corner ID</p>
      </div>
    );
  }

  return (
    <div className="h-[calc(100vh-6rem)]">
      <CornerReplay sessionId={sessionId} cornerId={cornerId} />
    </div>
  );
}
