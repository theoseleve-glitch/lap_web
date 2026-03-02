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
import 'leaflet/dist/leaflet.css';

/* ── Types ──────────────────────────────────────────────── */

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

type SubTab = 'coaching' | 'replay' | 'charts';

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

  const positions = posData?.corners ?? [];

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

      // Fit to positions
      const bounds = L.latLngBounds(positions.map((p) => [p.lat, p.lon]));
      map.fitBounds(bounds, { padding: [40, 40] });

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
        <span className="text-[9px] text-steel/30 font-telemetry ml-1">
          {selected.size}/{corners.length}
        </span>
      </div>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────── */

export function CornersTab({ corners, sessionId }: CornersTabProps) {
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(corners.map((c) => c.corner_id)),
  );
  const [subTab, setSubTab] = useState<SubTab>('coaching');

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
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <p className="text-steel font-telemetry text-sm mb-2">
            No corners detected for this session.
          </p>
          <p className="text-steel/40 font-telemetry text-xs">
            Corner detection requires GPS data with sufficient curvature changes.
          </p>
        </div>
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
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <BrakePrecisionChart sessionId={sessionId} />
          <CornerMasteryCard sessionId={sessionId} />
          <ThrottleOnsetMap sessionId={sessionId} />
          <ConsistencyHeatmap sessionId={sessionId} />
        </div>
      )}
    </div>
  );
}
