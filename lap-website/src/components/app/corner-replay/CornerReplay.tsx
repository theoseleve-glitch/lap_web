'use client';

import { useReducer, useRef, useCallback, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import type {
  CornerReplayData,
  PlaybackSpeed,
  ReplayWindow,
} from '@/types/corner-replay';
import { replayReducer, initialReplayState } from './replayReducer';
import { CornerReplayMap } from './CornerReplayMap';
import { CornerReplayCockpit, type CockpitFrame } from './CornerReplayCockpit';
import { CornerReplayControls } from './CornerReplayControls';
import { CornerMetricsPanel } from './CornerMetricsPanel';

interface CornerReplayProps {
  sessionId: string;
}

const SPEEDS: PlaybackSpeed[] = [0.25, 0.5, 1, 2];

export function CornerReplay({ sessionId }: CornerReplayProps) {
  const [state, dispatch] = useReducer(replayReducer, initialReplayState);
  const rafRef = useRef<number | null>(null);
  const lastTimeRef = useRef(0);

  // Fetch batch data
  const { data, error, isLoading } = useQuery({
    queryKey: ['corner-replay', sessionId],
    queryFn: () => api.get<CornerReplayData>(`/sessions/${sessionId}/corner-replay`),
    enabled: !!sessionId,
  });

  // Derived data
  const corners = data?.corners ?? [];
  const laps = data?.laps ?? [];
  const traces = data?.traces ?? {};
  const currentCorner = corners[state.cornerIndex] ?? null;
  const cornerWindows = currentCorner
    ? (data?.replay_windows?.[currentCorner.corner_id] ?? [])
    : [];
  const currentWindow: ReplayWindow | null = cornerWindows.find(
    (w) => w.lap_number === state.lapA
  ) ?? cornerWindows[0] ?? null;
  const totalFrames = currentWindow
    ? currentWindow.end_idx - currentWindow.start_idx + 1
    : 0;

  // Current corner metrics
  const currentMetrics = currentCorner
    ? (data?.corner_metrics?.[currentCorner.corner_id] ?? [])
    : [];

  // Build cockpit frame from current trace data
  const cockpitFrame: CockpitFrame = useMemo(() => {
    if (!currentWindow || !traces[String(state.lapA)]) {
      return { speed: 0, gLat: 0, gLon: 0 };
    }
    const trace = traces[String(state.lapA)];
    const idx = Math.min(
      currentWindow.start_idx + state.frame,
      (trace.speed_mps?.length ?? 1) - 1
    );
    const speedMps = trace.speed_mps?.[idx] ?? 0;
    const frame: CockpitFrame = {
      speed: speedMps * 3.6,
      gLat: trace.accel_lat?.[idx] ?? 0,
      gLon: trace.accel_lon?.[idx] ?? 0,
    };
    if (data?.has_pedal_data) {
      frame.brake = trace.brake?.[idx] ?? 0;
      frame.throttle = trace.throttle?.[idx] ?? 0;
    }
    if (data?.has_steering_data) {
      frame.steeringAngle = trace.steering?.[idx] ?? 0;
    }
    return frame;
  }, [traces, state.lapA, state.frame, currentWindow, data?.has_pedal_data, data?.has_steering_data]);

  // Animation loop
  const animate = useCallback(
    (timestamp: number) => {
      if (!state.playing || totalFrames === 0) return;

      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
      }

      const elapsed = timestamp - lastTimeRef.current;
      const frameDuration = (1000 / 60) / state.speed; // ~60fps scaled by speed

      if (elapsed >= frameDuration) {
        lastTimeRef.current = timestamp;
        const nextFrame = state.frame + 1;
        if (nextFrame >= totalFrames) {
          dispatch({ type: 'SET_FRAME', frame: totalFrames - 1 });
          dispatch({ type: 'TOGGLE_PLAY' }); // stop at end
          return;
        }
        dispatch({ type: 'SET_FRAME', frame: nextFrame });
      }

      rafRef.current = requestAnimationFrame(animate);
    },
    [state.playing, state.speed, state.frame, totalFrames],
  );

  useEffect(() => {
    if (state.playing) {
      lastTimeRef.current = 0;
      rafRef.current = requestAnimationFrame(animate);
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [state.playing, animate]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't capture if user is typing in an input
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          dispatch({ type: 'TOGGLE_PLAY' });
          break;
        case 'ArrowLeft':
          e.preventDefault();
          dispatch({ type: 'PREV_CORNER', total: corners.length });
          break;
        case 'ArrowRight':
          e.preventDefault();
          dispatch({ type: 'NEXT_CORNER', total: corners.length });
          break;
        case '[': {
          const currentIdx = SPEEDS.indexOf(state.speed);
          if (currentIdx > 0) {
            dispatch({ type: 'SET_SPEED', speed: SPEEDS[currentIdx - 1] });
          }
          break;
        }
        case ']': {
          const currentIdx = SPEEDS.indexOf(state.speed);
          if (currentIdx < SPEEDS.length - 1) {
            dispatch({ type: 'SET_SPEED', speed: SPEEDS[currentIdx + 1] });
          }
          break;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [corners.length, state.speed]);

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin" />
      </div>
    );
  }

  // Error states
  if (error) {
    const errMsg = (error as Error)?.message ?? String(error);
    // Check for specific error codes
    if (errMsg.includes('key corners') || errMsg.includes('409')) {
      return (
        <div className="rounded-lg border border-steel/20 bg-concrete p-6 text-center">
          <p className="text-steel font-telemetry text-sm mb-2">No corners selected for this track.</p>
          <p className="text-steel/60 font-telemetry text-xs">
            Re-run analysis to select corners of interest.
          </p>
        </div>
      );
    }
    if (errMsg.includes('Insufficient') || errMsg.includes('422')) {
      return (
        <div className="rounded-lg border border-steel/20 bg-concrete p-6 text-center">
          <p className="text-steel font-telemetry text-sm">
            This session has fewer than 2 GPS laps. Corner replay requires at least 2.
          </p>
        </div>
      );
    }
    if (errMsg.includes('not found') || errMsg.includes('404')) {
      return (
        <div className="rounded-lg border border-steel/20 bg-concrete p-6 text-center">
          <p className="text-steel font-telemetry text-sm">Session not found or has been deleted.</p>
        </div>
      );
    }
    return (
      <div className="rounded-lg border border-steel/20 bg-concrete p-6 text-center">
        <p className="text-steel font-telemetry text-sm mb-2">Failed to load corner replay data.</p>
        <p className="text-steel/60 font-telemetry text-xs">Check your connection and try again.</p>
      </div>
    );
  }

  // No data
  if (!data || corners.length === 0) {
    return (
      <div className="rounded-lg border border-steel/20 bg-concrete p-6 text-center">
        <p className="text-steel font-telemetry text-sm">No corner data available.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Controls */}
      <CornerReplayControls
        mode={state.mode}
        corners={corners}
        cornerIndex={state.cornerIndex}
        laps={laps}
        lapA={state.lapA}
        lapB={state.lapB}
        frame={state.frame}
        totalFrames={totalFrames}
        playing={state.playing}
        speed={state.speed}
        onModeChange={(mode) => dispatch({ type: 'SET_MODE', mode })}
        onCornerChange={(index) => dispatch({ type: 'SET_CORNER', index })}
        onPrevCorner={() => dispatch({ type: 'PREV_CORNER', total: corners.length })}
        onNextCorner={() => dispatch({ type: 'NEXT_CORNER', total: corners.length })}
        onLapAChange={(lap) => dispatch({ type: 'SET_LAP_A', lap })}
        onLapBChange={(lap) => dispatch({ type: 'SET_LAP_B', lap })}
        onScrub={(frame) => dispatch({ type: 'SET_FRAME', frame })}
        onTogglePlay={() => dispatch({ type: 'TOGGLE_PLAY' })}
        onSpeedChange={(speed) => dispatch({ type: 'SET_SPEED', speed })}
      />

      {/* Map + Cockpit side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-lg border border-steel/20 bg-concrete overflow-hidden" style={{ minHeight: '300px' }}>
          <CornerReplayMap
            mode={state.mode}
            traces={traces}
            corners={corners}
            cornerIndex={state.cornerIndex}
            lapA={state.lapA}
            lapB={state.lapB}
            frame={state.frame}
            replayWindow={currentWindow}
          />
        </div>
        <div className="space-y-4">
          <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden" style={{ minHeight: '200px' }}>
            <CornerReplayCockpit
              frame={cockpitFrame}
              hasPedalData={data.has_pedal_data}
              hasSteeringData={data.has_steering_data}
            />
          </div>
          {currentCorner && (
            <CornerMetricsPanel
              corner={currentCorner}
              metrics={currentMetrics}
              selectedLap={state.lapA}
            />
          )}
        </div>
      </div>

      {/* Keyboard hints */}
      <div className="flex items-center gap-4 text-[10px] text-steel/40 font-telemetry">
        <span>Space: Play/Pause</span>
        <span>←→: Prev/Next Corner</span>
        <span>[ ]: Speed</span>
      </div>
    </div>
  );
}
