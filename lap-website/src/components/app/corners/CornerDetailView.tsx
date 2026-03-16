'use client';

import { useMemo } from 'react';
import type { CornerData, CornerMetricRow, TheoreticalData, CoachingData, GpsTrace } from './useCornerData';
import { CornerDetailHeader } from './CornerDetailHeader';
import { VerdictSection } from './VerdictSection';
import { SpeedComparisonBars } from './SpeedComparisonBars';
import { AccordionPanel } from './AccordionPanel';
import { LapByLapPanel } from './LapByLapPanel';
import { TheoreticalBestPanel } from './TheoreticalBestPanel';
import { HandlingEventsPanel } from './HandlingEventsPanel';
import { ProgressiveStepsPanel } from './ProgressiveStepsPanel';

interface CornerDetailViewProps {
  cornerId: number;
  data: {
    corners: CornerData[];
    metrics: CornerMetricRow[];
    theoretical: TheoreticalData | null;
    coaching: CoachingData | null;
    gpsTrace: GpsTrace | null;
  };
  onBack: () => void;
  onNavigate: (id: number) => void;
}

export function CornerDetailView({ cornerId, data, onBack, onNavigate }: CornerDetailViewProps) {
  const sortedCorners = useMemo(
    () => [...data.corners].sort((a, b) => a.corner_id - b.corner_id),
    [data.corners],
  );

  const cornerIndex = sortedCorners.findIndex((c) => c.corner_id === cornerId);
  const corner = sortedCorners[cornerIndex];

  const cornerMetrics = useMemo(
    () => data.metrics.filter((m) => m.corner_id === cornerId),
    [data.metrics, cornerId],
  );

  const theoCorner = useMemo(
    () => data.theoretical?.corner_coaching?.find((c) => c.corner_id === cornerId) ?? null,
    [data.theoretical, cornerId],
  );

  const focusArea = useMemo(
    () => data.coaching?.focus_areas?.find((fa) => fa.corner_ids?.includes(cornerId)) ?? null,
    [data.coaching, cornerId],
  );

  if (!corner) {
    return (
      <div className="py-12 text-center">
        <p className="text-steel font-body">Corner not found</p>
        <button onClick={onBack} className="text-acid-green text-sm mt-2 font-body">← Back to track</button>
      </div>
    );
  }

  const handlePrev = () => {
    if (cornerIndex > 0) onNavigate(sortedCorners[cornerIndex - 1].corner_id);
  };
  const handleNext = () => {
    if (cornerIndex < sortedCorners.length - 1) onNavigate(sortedCorners[cornerIndex + 1].corner_id);
  };

  return (
    <div>
      <CornerDetailHeader
        corner={corner}
        cornerIndex={cornerIndex}
        totalCorners={sortedCorners.length}
        onBack={onBack}
        onPrev={handlePrev}
        onNext={handleNext}
      />

      <VerdictSection corner={corner} />

      <SpeedComparisonBars corner={corner} />

      <div className="mt-4">
        <AccordionPanel title="Lap-by-Lap Breakdown" subtitle="Apex speed, brake point, exit speed across all laps">
          <LapByLapPanel metrics={cornerMetrics} />
        </AccordionPanel>

        <AccordionPanel title="Theoretical Best" subtitle="Physics-optimal speed profile vs your best lap">
          <TheoreticalBestPanel
            corner={corner}
            theoCorner={theoCorner}
            theoretical={data.theoretical}
            gpsTrace={data.gpsTrace}
          />
        </AccordionPanel>

        <AccordionPanel title="Handling Events" subtitle="Understeer / oversteer events at this corner">
          <HandlingEventsPanel events={corner.handling_events ?? []} />
        </AccordionPanel>

        <AccordionPanel title="Progressive Steps" subtitle="Step-by-step improvement plan for this corner">
          <ProgressiveStepsPanel
            focusArea={focusArea}
            coachingHint={corner.coaching_hint}
          />
        </AccordionPanel>
      </div>
    </div>
  );
}
