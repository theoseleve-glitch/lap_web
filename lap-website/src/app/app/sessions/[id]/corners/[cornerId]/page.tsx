'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { CornerReplay } from '@/components/app/corner-replay';

export default function CornerReplayPage() {
  const params = useParams<{ id: string; cornerId: string }>();
  const sessionId = params.id;

  return (
    <div className="relative h-[calc(100vh-6rem)]">
      <h1 className="sr-only">Corner Replay</h1>
      <Link
        href={`/app/sessions/${sessionId}`}
        className="absolute top-3 left-3 z-10 px-3 py-1.5 bg-carbon/80 border border-steel/30 text-steel font-telemetry text-xs rounded hover:text-chalk hover:border-steel/60 transition-colors backdrop-blur-sm"
      >
        ← Session
      </Link>
      <CornerReplay sessionId={sessionId} />
    </div>
  );
}
