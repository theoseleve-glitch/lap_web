'use client';

import { useState, useCallback } from 'react';
import { useCornerData } from './useCornerData';
import { TrackMapView } from './TrackMapView';
import { CornerDetailView } from './CornerDetailView';
import { FullLapTrace } from './FullLapTrace';

export type { CornerData } from './useCornerData';

interface CornersTabProps {
  corners: unknown[];
  sessionId: string;
}

export function CornersTab({ sessionId }: CornersTabProps) {
  const data = useCornerData(sessionId);
  const [selectedCornerId, setSelectedCornerId] = useState<number | null>(null);

  const handleSelectCorner = useCallback((id: number) => setSelectedCornerId(id), []);
  const handleBack = useCallback(() => setSelectedCornerId(null), []);

  if (data.isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
        <span className="ml-3 text-steel text-sm font-body">Loading corner data...</span>
      </div>
    );
  }

  if (data.isError) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <p className="text-steel font-body text-sm">Failed to load corner data</p>
        <button
          onClick={data.refetchAll}
          className="px-4 py-2 bg-concrete text-chalk text-sm font-monument rounded border border-steel/20 hover:border-acid-green/50 transition-colors"
        >
          Try again
        </button>
      </div>
    );
  }

  if (data.corners.length === 0) {
    return (
      <div className="py-16 text-center">
        <p className="font-monument text-lg text-chalk mb-2">No corners detected</p>
        <p className="text-steel font-body text-sm max-w-md mx-auto">
          Corner detection requires sufficient GPS data with clear curvature changes.
        </p>
      </div>
    );
  }

  if (selectedCornerId !== null) {
    return (
      <CornerDetailView
        cornerId={selectedCornerId}
        data={data}
        onBack={handleBack}
        onNavigate={handleSelectCorner}
      />
    );
  }

  return (
    <>
      <TrackMapView
        corners={data.corners}
        gpsTrace={data.gpsTrace}
        theoretical={data.theoretical}
        onSelectCorner={handleSelectCorner}
      />
      <FullLapTrace
        theoretical={data.theoretical}
        gpsTrace={data.gpsTrace}
      />
    </>
  );
}
