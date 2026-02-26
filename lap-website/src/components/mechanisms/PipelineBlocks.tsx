'use client';

import { useMemo } from 'react';
import { ScrutineeringStamp } from '@/components/ui/ScrutineeringStamp';
import { pipelineStages } from '@/data/pipeline-stages';
import { colors } from '@/lib/tokens';

interface PipelineBlocksProps {
  progress: number; // 0-1 overall scroll progress for this room
  className?: string;
}

export function PipelineBlocks({ progress, className = '' }: PipelineBlocksProps) {
  const blockStates = useMemo(() => {
    return pipelineStages.map((_, i) => {
      const blockStart = i / pipelineStages.length;
      const blockEnd = (i + 1) / pipelineStages.length;
      const blockProgress = Math.max(0, Math.min(1, (progress - blockStart) / (blockEnd - blockStart)));
      return {
        fillPercent: blockProgress * 100,
        complete: blockProgress >= 1,
      };
    });
  }, [progress]);

  return (
    <div className={`flex flex-col md:flex-row gap-4 md:gap-0 ${className}`}>
      {pipelineStages.map((stage, i) => {
        const state = blockStates[i];
        return (
          <div key={stage.name} className="flex-1 flex flex-col items-center gap-3">
            {/* Block */}
            <div
              className="relative w-full h-32 md:h-48 border border-steel/30 overflow-hidden texture-dither"
              style={{ background: colors.concrete }}
            >
              {/* Fill */}
              <div
                className="absolute bottom-0 left-0 right-0 transition-all duration-300"
                style={{
                  height: `${state.fillPercent}%`,
                  background: `linear-gradient(to top, var(--accent), transparent)`,
                  opacity: 0.3,
                }}
              />

              {/* Stage name */}
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="font-monument text-[var(--text-h3)] opacity-40">
                  {stage.name}
                </span>
              </div>

              {/* Stamp on complete */}
              {state.complete && (
                <div className="absolute inset-0 flex items-center justify-center">
                  <ScrutineeringStamp
                    label={stage.stamp.label}
                    detail={stage.stamp.detail}
                    variant="slam"
                  />
                </div>
              )}
            </div>

            {/* Label */}
            <span className="font-telemetry text-steel">
              {stage.telemetryLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}
