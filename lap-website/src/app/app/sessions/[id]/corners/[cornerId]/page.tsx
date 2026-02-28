'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { CornerReplay } from '@/components/app/corner-replay';

export default function CornerReplayPage() {
  const params = useParams<{ id: string; cornerId: string }>();
  const sessionId = params.id;
  const cornerId = parseInt(params.cornerId, 10);

  if (isNaN(cornerId)) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-6rem)]">
        <div className="text-center">
          <p className="text-safety-red font-telemetry text-sm mb-3">Invalid corner ID</p>
          <Link href={`/app/sessions/${sessionId}`} className="text-pit-orange font-telemetry text-xs hover:underline">
            ← Back to session
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-[calc(100vh-6rem)]">
      <h1 className="sr-only">Corner Replay</h1>
      <Link
        href={`/app/sessions/${sessionId}`}
        className="absolute top-3 left-3 z-10 px-3 py-1.5 bg-carbon/80 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk hover:border-steel/60 transition-colors backdrop-blur-sm"
      >
        ← Session
      </Link>
      <CornerReplay sessionId={sessionId} cornerId={cornerId} />
    </div>
  );
}
