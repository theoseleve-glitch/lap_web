'use client';

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { CornerReplayMap } from './CornerReplayMap';
import { CornerReplayCockpit, type CockpitFrame } from './CornerReplayCockpit';
import { CornerReplayControls } from './CornerReplayControls';
import type { CornerReplayTrace, CornerReplayCorner, ReplayWindow } from '@/types/corner-replay';

type PlaybackSpeed = 0.5 | 1 | 2;
type ViewMode = 'split' | 'cockpit' | 'map';

interface GpsPoint {
  lat: number;
  lon: number;
}

interface ReplayFrame {
  time: number;
  speed: number;
  throttle?: number;
  brake?: number;
  steeringAngle?: number;
  gLat: number;
  gLon: number;
  lat: number;
  lon: number;
}

interface CornerReplayData {
  corner_id: number;
  corner_name: string;
  frames: ReplayFrame[];
  gps_path: GpsPoint[];
  total_time: number;
}

interface CornerReplayProps {
  sessionId: string;
  cornerId: number;
}

/** Fallback data when API has no data or is still loading */
const EMPTY_FRAME: CockpitFrame = {
  speed: 0,
  gLat: 0,
  gLon: 0,
};

const EMPTY_GPS: GpsPoint[] = [];

export function CornerReplay({ sessionId, cornerId }: CornerReplayProps) {
  const [currentFrame, setCurrentFrame] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<PlaybackSpeed>(1);
  const [viewMode, setViewMode] = useState<ViewMode>('split');

  const rafRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);

  const { data, isLoading, error } = useQuery({
    queryKey: ['session', sessionId, 'corners', cornerId, 'replay'],
    queryFn: () =>
      api.get<CornerReplayData>(
        `/sessions/${sessionId}/corners/${cornerId}/replay`,
      ),
  });

  const frames = data?.frames ?? [];
  const gpsPath = data?.gps_path ?? EMPTY_GPS;
  const totalFrames = frames.length;
  const totalTime = data?.total_time ?? 0;

  // Compute time per frame assuming equal spacing
  const timePerFrame = totalFrames > 1 ? totalTime / (totalFrames - 1) : 0;
  const currentTime = currentFrame * timePerFrame;

  // Detect which optional channels are present in the data
  const hasPedalData = frames.some(
    (f) => f.throttle != null || f.brake != null,
  );
  const hasSteeringData = frames.some((f) => f.steeringAngle != null);

  // Bridge: convert old single-corner data shape into new CornerReplayMap props
  const mapTraces = useMemo((): Record<string, CornerReplayTrace> => {
    if (frames.length === 0) return {} as Record<string, CornerReplayTrace>;
    const trace: CornerReplayTrace = {
      lat: frames.map((f) => f.lat),
      lon: frames.map((f) => f.lon),
      dist_m: frames.map((_, i) => i), // synthetic distance
      speed_mps: frames.map((f) => f.speed),
      accel_lat: frames.map((f) => f.gLat),
      accel_lon: frames.map((f) => f.gLon),
    };
    if (hasPedalData) {
      trace.throttle = frames.map((f) => f.throttle ?? 0);
      trace.brake = frames.map((f) => f.brake ?? 0);
    }
    if (hasSteeringData) {
      trace.steering = frames.map((f) => f.steeringAngle ?? 0);
    }
    return { '1': trace };
  }, [frames, hasPedalData, hasSteeringData]);

  const mapCorners = useMemo<CornerReplayCorner[]>(() => {
    if (!data || gpsPath.length === 0) return [];
    const mid = Math.floor(gpsPath.length / 2);
    return [{
      corner_id: String(cornerId),
      label: data.corner_name ?? `C${cornerId}`,
      lat: gpsPath[mid]?.lat ?? 0,
      lon: gpsPath[mid]?.lon ?? 0,
      dist_m: mid,
    }];
  }, [data, cornerId, gpsPath]);

  const mapReplayWindow = useMemo<ReplayWindow | null>(() => {
    if (totalFrames === 0) return null;
    return {
      lap_number: 1,
      start_idx: 0,
      end_idx: totalFrames - 1,
      estimated_duration_s: totalTime,
    };
  }, [totalFrames, totalTime]);

  // Current cockpit frame
  const cockpitFrame: CockpitFrame =
    totalFrames > 0
      ? {
          speed: frames[currentFrame]?.speed ?? 0,
          throttle: frames[currentFrame]?.throttle,
          brake: frames[currentFrame]?.brake,
          steeringAngle: frames[currentFrame]?.steeringAngle,
          gLat: frames[currentFrame]?.gLat ?? 0,
          gLon: frames[currentFrame]?.gLon ?? 0,
        }
      : EMPTY_FRAME;

  // Animation loop
  const animate = useCallback(
    (timestamp: number) => {
      if (!isPlaying || totalFrames === 0) return;

      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
      }

      const elapsed = timestamp - lastTimeRef.current;
      // Target frame rate: ~60fps, advance frames proportionally to speed
      const frameDuration = timePerFrame > 0 ? (timePerFrame * 1000) / playbackSpeed : 16.67;

      if (elapsed >= frameDuration) {
        lastTimeRef.current = timestamp;
        setCurrentFrame((prev) => {
          const next = prev + 1;
          if (next >= totalFrames) {
            setIsPlaying(false);
            return totalFrames - 1;
          }
          return next;
        });
      }

      rafRef.current = requestAnimationFrame(animate);
    },
    [isPlaying, totalFrames, timePerFrame, playbackSpeed],
  );

  useEffect(() => {
    if (isPlaying) {
      lastTimeRef.current = 0;
      rafRef.current = requestAnimationFrame(animate);
    }
    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [isPlaying, animate]);

  // Reset frame when corner changes
  useEffect(() => {
    setCurrentFrame(0);
    setIsPlaying(false);
  }, [cornerId]);

  const handleTogglePlay = useCallback(() => {
    if (!isPlaying && currentFrame >= totalFrames - 1 && totalFrames > 0) {
      // Restart from beginning when at end
      setCurrentFrame(0);
    }
    setIsPlaying((prev) => !prev);
  }, [isPlaying, currentFrame, totalFrames]);

  const handleScrub = useCallback(
    (frame: number) => {
      setCurrentFrame(Math.min(frame, Math.max(totalFrames - 1, 0)));
      if (isPlaying) {
        setIsPlaying(false);
      }
    },
    [isPlaying, totalFrames],
  );

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin mx-auto mb-3" />
          <p className="text-steel font-telemetry text-sm">Loading corner replay...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <p className="text-safety-red font-telemetry text-sm mb-1">Failed to load replay data</p>
          <p className="text-steel font-telemetry text-xs">
            {error instanceof Error ? error.message : 'Unknown error'}
          </p>
        </div>
      </div>
    );
  }

  // Empty data
  if (totalFrames === 0) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-steel font-telemetry text-sm">No replay data available for this corner</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Header */}
      <div className="flex items-center justify-between px-1">
        <div>
          <h2 className="font-monument text-xl text-chalk tracking-tight">
            {data?.corner_name ?? `Corner ${cornerId}`}
          </h2>
          <p className="text-steel font-telemetry text-xs mt-0.5">
            Session {sessionId} -- Corner replay
          </p>
        </div>
      </div>

      {/* Visualization area */}
      <div className="flex-1 min-h-0">
        {viewMode === 'split' && (
          <div className="grid grid-cols-2 gap-3 h-full">
            <CornerReplayMap
              mode="review"
              traces={mapTraces}
              corners={mapCorners}
              cornerIndex={0}
              lapA={1}
              lapB={1}
              frame={currentFrame}
              replayWindow={mapReplayWindow}
            />
            <CornerReplayCockpit frame={cockpitFrame} hasPedalData={hasPedalData} hasSteeringData={hasSteeringData} />
          </div>
        )}

        {viewMode === 'cockpit' && (
          <div className="h-full">
            <CornerReplayCockpit frame={cockpitFrame} hasPedalData={hasPedalData} hasSteeringData={hasSteeringData} />
          </div>
        )}

        {viewMode === 'map' && (
          <div className="h-full">
            <CornerReplayMap
              mode="review"
              traces={mapTraces}
              corners={mapCorners}
              cornerIndex={0}
              lapA={1}
              lapB={1}
              frame={currentFrame}
              replayWindow={mapReplayWindow}
            />
          </div>
        )}
      </div>

      {/* Controls */}
      <CornerReplayControls
        isPlaying={isPlaying}
        currentFrame={currentFrame}
        totalFrames={totalFrames}
        playbackSpeed={playbackSpeed}
        viewMode={viewMode}
        currentTime={currentTime}
        totalTime={totalTime}
        onTogglePlay={handleTogglePlay}
        onScrub={handleScrub}
        onSpeedChange={setPlaybackSpeed}
        onViewModeChange={setViewMode}
      />
    </div>
  );
}
