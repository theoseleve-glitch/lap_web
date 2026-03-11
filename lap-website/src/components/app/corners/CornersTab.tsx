'use client';

import { useState, useMemo, useCallback, useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { CoachingTable } from './CoachingTable';
import { CornerReplay } from '../corner-replay';
import { BrakePrecisionChart } from './BrakePrecisionChart';
import { CornerMasteryCard } from './CornerMasteryCard';
import { ThrottleOnsetMap } from './ThrottleOnsetMap';
import { ConsistencyHeatmap } from './ConsistencyHeatmap';
import { CornerGHistogram } from './CornerGHistogram';
import { CornerSpeedTrend } from './CornerSpeedTrend';
import { CornerDefiner } from '../charts/CornerDefiner';
import 'leaflet/dist/leaflet.css';

/* ── Types ──────────────────────────────────────────────── */

export interface HandlingEventData {
  event_type: 'understeer' | 'oversteer';
  severity: 'mild' | 'moderate' | 'severe';
  cause: string;
  cause_detail: string;
  corner_phase: 'entry' | 'mid' | 'exit';
  magnitude: number;
  time_cost_s?: number | null;
}

export interface CornerData {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: 'L' | 'R';
  available: boolean;
  entry_speed_actual?: number | null;
  entry_speed_theory?: number | null;
  apex_speed_actual?: number | null;
  apex_speed_theory?: number | null;
  exit_speed_actual?: number | null;
  exit_speed_theory?: number | null;
  time_loss_total_s?: number | null;
  grip_utilisation_pct?: number | null;
  primary_cause?: string | null;
  coaching_hint?: string | null;
  /* v2 fields */
  corner_type?: string | null;
  section_type?: string | null;
  mrp_distance_m?: number | null;
  mrp_speed_mps?: number | null;
  geometric_apex_m?: number | null;
  exit_importance?: number | null;
  is_user_defined?: boolean | null;
  handling_events?: HandlingEventData[] | null;
}

interface CornerPosition {
  corner_id: number;
  s_start: number;
  s_end: number;
  s_apex?: number;
  direction?: string;
  label?: string;
  lat: number;
  lon: number;
  brake_point_m?: number | null;
}

interface CornersTabProps {
  corners: CornerData[];
  sessionId: string;
}

type SubTab = 'coaching' | 'replay' | 'charts' | 'define';

const STORAGE_KEY = 'corner_sel_';

/* ── Interactive Track Map ────────────────────────────── */

function TrackOverviewMap({
  sessionId,
  corners,
  selected,
  onToggle,
}: {
  sessionId: string;
  corners: CornerData[];
  selected: Set<number>;
  onToggle: (id: number) => void;
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<Map<number, { marker: L.CircleMarker }>>(new Map());

  // Fetch corner GPS positions
  const { data: posData } = useQuery({
    queryKey: ['corner-positions', sessionId],
    queryFn: () => api.get<{ corners: CornerPosition[] }>(`/sessions/${sessionId}/corner-positions`),
    enabled: !!sessionId,
  });

  const positions = (posData?.corners ?? []).filter(
    (p) => p.lat !== 0 && p.lon !== 0 && isFinite(p.lat) && isFinite(p.lon),
  );

  useEffect(() => {
    if (!mapRef.current || positions.length === 0) return;
    let cancelled = false;

    (async () => {
      const L = (await import('leaflet')).default;
      if (cancelled || !mapRef.current) return;

      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
      }

      const map = L.map(mapRef.current, {
        zoomControl: true,
        attributionControl: false,
      });
      leafletMapRef.current = map;

      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
      }).addTo(map);

      // Fit to positions (guard against invalid bounds)
      const bounds = L.latLngBounds(positions.map((p) => [p.lat, p.lon]));
      if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [40, 40] });
      }

      // Draw corner markers
      const layers = new Map<number, { marker: L.CircleMarker }>();
      positions.forEach((pos) => {
        const isLeft = pos.direction === 'L';
        const isRight = pos.direction === 'R';
        const color = isLeft ? '#60a5fa' : isRight ? '#fb923c' : '#6b7280';
        const isSelected = selected.has(pos.corner_id);

        const marker = L.circleMarker([pos.lat, pos.lon], {
          radius: isSelected ? 10 : 7,
          fillColor: color,
          fillOpacity: isSelected ? 0.9 : 0.3,
          color: isSelected ? '#fff' : color,
          weight: isSelected ? 2 : 1,
        }).addTo(map);

        const dirArrow = pos.direction === 'L' ? '\u21B0' : pos.direction === 'R' ? '\u21B1' : '';
        marker.bindTooltip(`C${pos.corner_id} ${dirArrow}`, {
          permanent: true,
          direction: 'center',
          className: 'corner-map-label',
        });

        marker.on('click', () => onToggle(pos.corner_id));
        layers.set(pos.corner_id, { marker });
      });

      layersRef.current = layers;
    })();

    return () => {
      cancelled = true;
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [positions]);

  // Update marker styles when selection changes
  useEffect(() => {
    layersRef.current.forEach((layer, id) => {
      const isSelected = selected.has(id);
      layer.marker.setStyle({
        radius: isSelected ? 10 : 7,
        fillOpacity: isSelected ? 0.9 : 0.3,
        opacity: isSelected ? 1 : 0.5,
        weight: isSelected ? 2 : 1,
      });
    });
  }, [selected]);

  if (positions.length === 0) return null;

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden">
      <div ref={mapRef} style={{ width: '100%', height: '260px' }} />
      <style jsx global>{`
        .corner-map-label {
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          color: #fff;
          font-size: 10px;
          font-weight: 700;
          text-shadow: 0 0 4px rgba(0,0,0,0.8);
        }
        .corner-map-label::before {
          display: none;
        }
      `}</style>
    </div>
  );
}

/* ── Area of Interest Selector ────────────────────────── */

function AreaOfInterestBar({
  corners,
  selected,
  onToggle,
  onSelectAll,
  onClearAll,
}: {
  corners: CornerData[];
  selected: Set<number>;
  onToggle: (id: number) => void;
  onSelectAll: () => void;
  onClearAll: () => void;
}) {
  const allSelected = corners.length > 0 && corners.every((c) => selected.has(c.corner_id));

  return (
    <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 bg-concrete rounded-lg border border-steel/10">
      <span className="text-[10px] font-telemetry uppercase tracking-wider text-steel/50 mr-1">
        Areas of Interest
      </span>

      {/* Corner chips */}
      {corners.map((c) => {
        const isSelected = selected.has(c.corner_id);
        const dirColor = c.direction === 'L' ? '#60a5fa' : c.direction === 'R' ? '#fb923c' : '#6b7280';
        return (
          <button
            key={c.corner_id}
            type="button"
            onClick={() => onToggle(c.corner_id)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-telemetry
              border transition-all duration-150
              ${isSelected
                ? 'border-chalk/40 text-chalk bg-asphalt'
                : 'border-steel/20 text-steel/50 bg-concrete'
              }`}
          >
            <span
              className="w-2 h-2 rounded-full"
              style={{ background: isSelected ? dirColor : `${dirColor}40` }}
            />
            C{c.corner_id}
          </button>
        );
      })}

      {/* Select / Clear all */}
      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={allSelected ? onClearAll : onSelectAll}
          className="text-[10px] font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors px-1"
        >
          {allSelected ? 'Clear All' : 'Select All'}
        </button>
        <span className="text-[9px] text-steel/50 font-telemetry ml-1">
          {selected.size}/{corners.length}
        </span>
      </div>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────── */

interface GpsTraceData {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
}

export function CornersTab({ corners: rawCorners, sessionId }: CornersTabProps) {
  const corners = rawCorners ?? [];
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(corners.map((c) => c.corner_id)),
  );
  const [subTab, setSubTab] = useState<SubTab>('coaching');

  // Fetch GPS trace for CornerDefiner (only when 'define' tab is active)
  const { data: gpsTrace } = useQuery({
    queryKey: ['gps-trace-for-definer', sessionId],
    queryFn: () => api.get<GpsTraceData>(`/sessions/${sessionId}/gps-trace`),
    enabled: subTab === 'define',
    staleTime: 5 * 60 * 1000,
  });

  // Persist selection
  useEffect(() => {
    try {
      const raw = localStorage.getItem(`${STORAGE_KEY}${sessionId}`);
      if (raw) {
        const ids: number[] = JSON.parse(raw);
        if (Array.isArray(ids) && ids.length > 0) {
          setSelected(new Set(ids));
        }
      }
    } catch { /* ignore */ }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  useEffect(() => {
    try {
      localStorage.setItem(`${STORAGE_KEY}${sessionId}`, JSON.stringify(Array.from(selected)));
    } catch { /* ignore */ }
  }, [selected, sessionId]);

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(
    () => setSelected(new Set(corners.map((c) => c.corner_id))),
    [corners],
  );
  const clearAll = useCallback(() => setSelected(new Set()), []);

  const filtered = useMemo(
    () => corners.filter((c) => selected.has(c.corner_id)),
    [corners, selected],
  );

  if (corners.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-center py-12">
          <div className="text-center">
            <p className="text-steel font-telemetry text-sm mb-2">
              No corners detected for this session.
            </p>
            <p className="text-steel/60 font-telemetry text-xs mb-4">
              Corner detection requires GPS data with sufficient curvature changes.
            </p>
            <button
              type="button"
              onClick={() => setSubTab('define')}
              className="px-4 py-2 border border-pit-orange/50 text-pit-orange text-xs font-telemetry
                rounded hover:bg-pit-orange/10 transition-colors"
            >
              Define Corners Manually
            </button>
          </div>
        </div>
        {subTab === 'define' && (
          <div className="space-y-3">
            <p className="text-xs text-steel font-body">
              Click on the track to place entry, apex, and exit points for each corner. Saved corners will be used in future coaching analysis.
            </p>
            {gpsTrace?.latitudes?.length ? (
              <CornerDefiner
                sessionId={sessionId}
                latitudes={gpsTrace.latitudes}
                longitudes={gpsTrace.longitudes}
                distances={gpsTrace.distances}
                onDone={() => window.location.reload()}
              />
            ) : (
              <div className="flex items-center justify-center py-12 text-steel/60 text-sm">
                Loading GPS trace data...
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Track map + area of interest selector */}
      <TrackOverviewMap
        sessionId={sessionId}
        corners={corners}
        selected={selected}
        onToggle={toggle}
      />
      <AreaOfInterestBar
        corners={corners}
        selected={selected}
        onToggle={toggle}
        onSelectAll={selectAll}
        onClearAll={clearAll}
      />

      {/* Sub-tab navigation */}
      <div className="flex gap-1 border-b border-steel/10">
        {([
          { key: 'coaching' as SubTab, label: 'Corner Coaching' },
          { key: 'replay' as SubTab, label: 'Corner Replay' },
          { key: 'charts' as SubTab, label: 'Analysis Charts' },
          { key: 'define' as SubTab, label: 'Define Corners' },
        ]).map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setSubTab(tab.key)}
            className={`px-4 py-2 text-xs font-telemetry uppercase tracking-wider transition-colors relative ${
              subTab === tab.key
                ? 'text-acid-green'
                : 'text-steel hover:text-chalk'
            }`}
          >
            {tab.label}
            {subTab === tab.key && (
              <span className="absolute bottom-0 left-0 right-0 h-0.5 bg-acid-green" />
            )}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {subTab === 'coaching' && (
        <CoachingTable corners={filtered} />
      )}

      {subTab === 'replay' && (
        <CornerReplay sessionId={sessionId} cornerIds={Array.from(selected)} />
      )}

      {subTab === 'charts' && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <BrakePrecisionChart sessionId={sessionId} />
            <CornerMasteryCard sessionId={sessionId} />
            <ThrottleOnsetMap sessionId={sessionId} />
            <ConsistencyHeatmap sessionId={sessionId} />
          </div>
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Corner Lateral G Distribution</h3>
            <CornerGHistogram sessionId={sessionId} corners={corners} />
          </div>
          <div className="bg-concrete rounded-xl border border-steel/10 p-4">
            <h3 className="text-sm font-monument text-chalk mb-3">Corner Apex Speed Trend</h3>
            <p className="text-xs text-steel mb-3 font-body">Minimum speed per corner across laps — shows learning and consistency</p>
            <CornerSpeedTrend sessionId={sessionId} />
          </div>
        </div>
      )}

      {subTab === 'define' && (
        <div className="space-y-3">
          <p className="text-xs text-steel font-body">
            Click on the track to place entry, apex, and exit points for each corner. Saved corners will be used in future coaching analysis.
          </p>
          {gpsTrace?.latitudes?.length ? (
            <CornerDefiner
              sessionId={sessionId}
              latitudes={gpsTrace.latitudes}
              longitudes={gpsTrace.longitudes}
              distances={gpsTrace.distances}
              onDone={() => {
                // Switch back to coaching tab after defining corners
                setSubTab('coaching');
                // Reload page to pick up new coaching data
                window.location.reload();
              }}
            />
          ) : (
            <div className="flex items-center justify-center py-12 text-steel/60 text-sm">
              Loading GPS trace data...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
