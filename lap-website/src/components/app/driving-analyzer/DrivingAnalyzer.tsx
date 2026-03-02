'use client';

import { useReducer, useRef, useCallback, useEffect, useMemo } from 'react';
import type { DrivingAnalyzerProps, SectionDef, PlaybackSpeed, AnalyzerTrace } from './types';
import { PLAYBACK_SPEEDS, DEFAULT_CHARTS } from './types';
import { analyzerReducer, initialAnalyzerState } from './analyzerReducer';
import { useAnalyzerData, closestIndex } from './useAnalyzerData';
import { AnalyzerSectionTabs } from './AnalyzerSectionTabs';
import { AnalyzerTrackMap } from './AnalyzerTrackMap';
import { AnalyzerChartStack } from './AnalyzerChartStack';
import { AnalyzerPlaybar } from './AnalyzerPlaybar';
import { AnalyzerLapSelector } from './AnalyzerLapSelector';
import { AnalyzerCockpit } from './AnalyzerCockpit';
import { AnalyzerReadouts } from './AnalyzerReadouts';

export default function DrivingAnalyzer({ sessionId, cornerFilter, onClose }: DrivingAnalyzerProps) {
  const [state, dispatch] = useReducer(analyzerReducer, initialAnalyzerState);
  const rafRef = useRef<number | null>(null);
  const lastTimeRef = useRef(0);

  const { traces, sections, laps, hasPedalData, hasSteeringData, isLoading, error } =
    useAnalyzerData(sessionId, cornerFilter);

  // Filter sections if cornerFilter is provided
  const filteredSections = useMemo<SectionDef[]>(() => {
    if (!cornerFilter?.length) return sections;
    return sections.filter(
      (s) => s.id === 'full' || (s.cornerIndex != null && cornerFilter.includes(s.cornerIndex)),
    );
  }, [sections, cornerFilter]);

  // Current active section definition
  const activeSection = useMemo(
    () => filteredSections.find((s) => s.id === state.activeSection) ?? filteredSections[0] ?? null,
    [filteredSections, state.activeSection],
  );

  // Current primary trace
  const primaryTrace: AnalyzerTrace | null = traces[String(state.primaryLap)] ?? Object.values(traces)[0] ?? null;
  const overlayTrace: AnalyzerTrace | null = state.overlayLap ? (traces[String(state.overlayLap)] ?? null) : null;

  // Set initial lap when data loads
  useEffect(() => {
    if (laps.length > 0 && !traces[String(state.primaryLap)]) {
      dispatch({ type: 'SET_LAP', lap: laps[0].lap_number });
    }
  }, [laps, traces, state.primaryLap]);

  // Distance range for active section
  const sectionRange = useMemo(() => {
    if (!activeSection) return { min: 0, max: 0 };
    return { min: activeSection.startDist, max: activeSection.endDist };
  }, [activeSection]);

  // Max distance for the full trace
  const maxDistance = primaryTrace
    ? primaryTrace.distance[primaryTrace.distance.length - 1]
    : 0;

  // Effective min/max for playback
  const playMin = activeSection?.id === 'full' ? 0 : sectionRange.min;
  const playMax = activeSection?.id === 'full' ? maxDistance : sectionRange.max;

  // Get speed at a given distance (m/s)
  const getSpeedAtDistance = useCallback(
    (d: number): number => {
      if (!primaryTrace) return 0;
      const idx = closestIndex(primaryTrace.distance, d);
      return (primaryTrace.speed[idx] ?? 0) / 3.6; // km/h → m/s
    },
    [primaryTrace],
  );

  // rAF playback engine — advances distance based on car's actual speed
  const animate = useCallback(
    (timestamp: number) => {
      if (!state.playing) return;

      if (lastTimeRef.current === 0) {
        lastTimeRef.current = timestamp;
        rafRef.current = requestAnimationFrame(animate);
        return;
      }

      const elapsed = timestamp - lastTimeRef.current;
      lastTimeRef.current = timestamp;

      const speedMps = getSpeedAtDistance(state.currentDistance);
      const distanceDelta = speedMps * (elapsed / 1000) * state.playbackSpeed;
      const next = state.currentDistance + distanceDelta;

      if (next >= playMax) {
        dispatch({ type: 'SET_DISTANCE', distance: playMax });
        dispatch({ type: 'TOGGLE_PLAY' });
        return;
      }

      dispatch({ type: 'SET_DISTANCE', distance: next });
      rafRef.current = requestAnimationFrame(animate);
    },
    [state.playing, state.playbackSpeed, state.currentDistance, playMax, getSpeedAtDistance],
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
    const handleKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;

      switch (e.key) {
        case ' ':
          e.preventDefault();
          dispatch({ type: 'TOGGLE_PLAY' });
          break;
        case 'ArrowLeft':
          e.preventDefault();
          dispatch({
            type: 'SET_DISTANCE',
            distance: Math.max(playMin, state.currentDistance - (e.shiftKey ? 100 : 10)),
          });
          break;
        case 'ArrowRight':
          e.preventDefault();
          dispatch({
            type: 'SET_DISTANCE',
            distance: Math.min(playMax, state.currentDistance + (e.shiftKey ? 100 : 10)),
          });
          break;
        case '[': {
          const idx = PLAYBACK_SPEEDS.indexOf(state.playbackSpeed);
          if (idx > 0) dispatch({ type: 'SET_SPEED', speed: PLAYBACK_SPEEDS[idx - 1] });
          break;
        }
        case ']': {
          const idx = PLAYBACK_SPEEDS.indexOf(state.playbackSpeed);
          if (idx < PLAYBACK_SPEEDS.length - 1) dispatch({ type: 'SET_SPEED', speed: PLAYBACK_SPEEDS[idx + 1] });
          break;
        }
        case 'Escape':
          onClose();
          break;
        default:
          // Number keys 1-9 jump to sections
          if (e.key >= '1' && e.key <= '9') {
            const secIdx = Number(e.key) - 1;
            if (secIdx < filteredSections.length) {
              dispatch({ type: 'SET_SECTION', section: filteredSections[secIdx].id });
            }
          }
      }
    };

    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [state.currentDistance, state.playbackSpeed, playMin, playMax, filteredSections, onClose]);

  // Build current cockpit-style values from cursor position
  const cursorIdx = primaryTrace ? closestIndex(primaryTrace.distance, state.currentDistance) : 0;
  const cursorValues = useMemo(() => {
    if (!primaryTrace) return { speed: 0, gLat: 0, gLon: 0, brake: 0, throttle: 0, steering: 0 };
    const i = cursorIdx;
    return {
      speed: primaryTrace.speed[i] ?? 0,
      gLat: primaryTrace.gLat[i] ?? 0,
      gLon: primaryTrace.gLon[i] ?? 0,
      brake: primaryTrace.brake[i] ?? 0,
      throttle: primaryTrace.throttle[i] ?? 0,
      steering: primaryTrace.steering[i] ?? 0,
    };
  }, [primaryTrace, cursorIdx]);

  // Visible chart configs (filtered by data availability)
  const visibleCharts = useMemo(() => {
    return DEFAULT_CHARTS.filter((c) => {
      if (!state.visibleCharts.includes(c.type)) return false;
      if (c.type === 'brake-throttle' && !hasPedalData) return false;
      if (c.type === 'steering' && !hasSteeringData) return false;
      return true;
    });
  }, [state.visibleCharts, hasPedalData, hasSteeringData]);

  // Turn radius from speed and lateral g
  const turnRadius = useMemo(() => {
    const vMs = cursorValues.speed / 3.6;
    const gLat = Math.abs(cursorValues.gLat);
    if (gLat < 0.05 || vMs < 1) return null;
    return (vMs * vMs) / (gLat * 9.81);
  }, [cursorValues.speed, cursorValues.gLat]);

  // Loading overlay
  if (isLoading) {
    return (
      <div className="fixed inset-0 z-50 bg-asphalt/98 flex items-center justify-center">
        <div className="text-center">
          <div className="w-10 h-10 border-2 border-steel/30 border-t-acid-green rounded-full animate-spin mx-auto mb-4" />
          <p className="text-steel font-telemetry text-sm">Loading telemetry data...</p>
        </div>
      </div>
    );
  }

  // Error overlay
  if (error || !primaryTrace) {
    return (
      <div className="fixed inset-0 z-50 bg-asphalt/98 flex items-center justify-center">
        <div className="text-center max-w-sm">
          <p className="text-chalk font-telemetry text-sm mb-2">
            {error ? 'Failed to load telemetry data' : 'No trace data available'}
          </p>
          <p className="text-steel/60 text-xs mb-4">
            {error instanceof Error ? error.message : 'The session may lack GPS data.'}
          </p>
          <button onClick={onClose} className="px-4 py-2 bg-concrete border border-steel/20 rounded text-chalk text-sm font-body hover:bg-steel/10">
            Close
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-asphalt flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 bg-concrete/80 border-b border-steel/10">
        <div className="flex items-center gap-3">
          <h2 className="font-monument text-sm text-chalk tracking-wide">DRIVING ANALYZER</h2>
          <AnalyzerLapSelector
            laps={laps}
            primaryLap={state.primaryLap}
            overlayLap={state.overlayLap}
            onPrimaryChange={(lap) => dispatch({ type: 'SET_LAP', lap })}
            onOverlayChange={(lap) => dispatch({ type: 'SET_OVERLAY_LAP', lap })}
          />
        </div>
        <button
          onClick={onClose}
          className="flex items-center gap-1.5 px-3 py-1.5 text-steel hover:text-chalk text-xs font-telemetry transition-colors"
        >
          Close
          <kbd className="text-[9px] px-1 py-0.5 rounded bg-asphalt border border-steel/20 text-steel/50">Esc</kbd>
        </button>
      </div>

      {/* Section tabs */}
      <AnalyzerSectionTabs
        sections={filteredSections}
        activeSection={state.activeSection}
        onSectionChange={(s) => dispatch({ type: 'SET_SECTION', section: s })}
      />

      {/* 3-column layout */}
      <div className="flex-1 flex min-h-0">
        {/* Left: Track Map + Cockpit (32%) */}
        <div className="flex flex-col" style={{ width: '32%' }}>
          <div className="flex-1 min-h-0">
            <AnalyzerTrackMap
              trace={primaryTrace}
              overlayTrace={overlayTrace}
              currentDistance={state.currentDistance}
              activeSection={activeSection}
              sections={filteredSections}
            />
          </div>
          <div className="h-[200px] border-t border-steel/10">
            <AnalyzerCockpit
              speed={cursorValues.speed}
              gLat={cursorValues.gLat}
              gLon={cursorValues.gLon}
              brake={cursorValues.brake}
              throttle={cursorValues.throttle}
              steering={cursorValues.steering}
              hasPedalData={hasPedalData}
              hasSteeringData={hasSteeringData}
            />
          </div>
        </div>

        {/* Center: Readouts (13%) */}
        <div className="border-l border-r border-steel/10" style={{ width: '13%' }}>
          <AnalyzerReadouts
            speed={cursorValues.speed}
            gLat={cursorValues.gLat}
            gLon={cursorValues.gLon}
            distance={state.currentDistance}
            turnRadius={turnRadius}
            gear={null}
          />
        </div>

        {/* Right: Chart Stack (55%) */}
        <div className="flex-1 min-h-0 overflow-hidden">
          <AnalyzerChartStack
            trace={primaryTrace}
            overlayTrace={overlayTrace}
            charts={visibleCharts}
            currentDistance={state.currentDistance}
            sectionRange={activeSection?.id !== 'full' ? sectionRange : null}
            onScrub={(d) => dispatch({ type: 'SET_DISTANCE', distance: d })}
          />
        </div>
      </div>

      {/* Bottom playbar */}
      <AnalyzerPlaybar
        playing={state.playing}
        currentDistance={state.currentDistance}
        minDistance={playMin}
        maxDistance={playMax}
        playbackSpeed={state.playbackSpeed}
        lapTime={primaryTrace.lapTime}
        currentTime={null}
        onTogglePlay={() => dispatch({ type: 'TOGGLE_PLAY' })}
        onScrub={(d) => dispatch({ type: 'SET_DISTANCE', distance: d })}
        onSpeedChange={(s: PlaybackSpeed) => dispatch({ type: 'SET_SPEED', speed: s })}
      />
    </div>
  );
}
