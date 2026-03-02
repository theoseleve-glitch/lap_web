/**
 * CornerPicker.tsx — Interactive Leaflet map for mid-analysis corner selection.
 *
 * Renders the full GPS track polyline with colored corner segments.
 * User clicks to select/deselect corners for detailed coaching analysis.
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import 'leaflet/dist/leaflet.css';

/* ── Types ──────────────────────────────────────────── */

interface Corner {
  corner_id: number;
  direction: string;
  lat: number;
  lon: number;
  dist_m: number;
  s_start: number | null;
  s_end: number | null;
  s_apex: number | null;
}

export interface TrackLayout {
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  speeds: number[];
  corners: Corner[];
  track_id?: string;
}

interface CornerPickerProps {
  trackLayout: TrackLayout;
  onSubmit: (selectedIds: number[]) => void;
  isSubmitting: boolean;
}

/* ── Helpers ──────────────────────────────────────────── */

/** Find the polyline index closest to a given distance value. */
function distToIndex(distances: number[], dist: number): number {
  let lo = 0;
  let hi = distances.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (distances[mid] < dist) lo = mid + 1;
    else hi = mid;
  }
  return Math.min(lo, distances.length - 1);
}

const LEFT_COLOR = '#60a5fa';   // blue-400
const RIGHT_COLOR = '#fb923c';  // orange-400
const NEUTRAL_COLOR = '#6b7280'; // gray-500

/* ── Component ──────────────────────────────────────── */

export function CornerPicker({ trackLayout, onSubmit, isSubmitting }: CornerPickerProps) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<Map<number, { segment: L.Polyline; marker: L.CircleMarker }>>(new Map());

  const allIds = trackLayout.corners.map((c) => c.corner_id);
  const [selected, setSelected] = useState<Set<number>>(() => new Set(allIds));

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectAll = useCallback(() => setSelected(new Set(allIds)), [allIds]);
  const clearAll = useCallback(() => setSelected(new Set()), []);

  // ── Build map ──────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return;
    let cancelled = false;

    (async () => {
      const L = (await import('leaflet')).default;
      if (cancelled || !mapRef.current) return;

      // Prevent double-init
      if (leafletMapRef.current) {
        leafletMapRef.current.remove();
        leafletMapRef.current = null;
      }

      const { latitudes, longitudes, distances, corners } = trackLayout;
      if (latitudes.length === 0) return;

      const coords: L.LatLngExpression[] = latitudes.map((lat, i) => [lat, longitudes[i]]);

      const map = L.map(mapRef.current, {
        zoomControl: true,
        attributionControl: false,
      });
      leafletMapRef.current = map;

      // Dark tile layer
      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
      }).addTo(map);

      // Full track polyline (neutral)
      const trackLine = L.polyline(coords, {
        color: NEUTRAL_COLOR,
        weight: 3,
        opacity: 0.5,
      }).addTo(map);

      map.fitBounds(trackLine.getBounds(), { padding: [30, 30] });

      // Corner segments + apex markers
      const layers = new Map<number, { segment: L.Polyline; marker: L.CircleMarker }>();

      corners.forEach((cn) => {
        const color = cn.direction === 'L' ? LEFT_COLOR : cn.direction === 'R' ? RIGHT_COLOR : NEUTRAL_COLOR;

        // Segment polyline (s_start to s_end)
        let segCoords = coords;
        if (cn.s_start != null && cn.s_end != null && distances.length > 0) {
          const startIdx = distToIndex(distances, cn.s_start);
          const endIdx = distToIndex(distances, cn.s_end);
          segCoords = coords.slice(startIdx, endIdx + 1);
        }

        const segment = L.polyline(segCoords, {
          color,
          weight: 6,
          opacity: 1.0,
        }).addTo(map);

        // Apex marker
        const marker = L.circleMarker([cn.lat, cn.lon], {
          radius: 10,
          fillColor: color,
          fillOpacity: 1,
          color: '#fff',
          weight: 2,
        }).addTo(map);

        // Label
        const dirArrow = cn.direction === 'L' ? '\u21B0' : cn.direction === 'R' ? '\u21B1' : '';
        marker.bindTooltip(`C${cn.corner_id + 1} ${dirArrow}`, {
          permanent: true,
          direction: 'center',
          className: 'corner-label',
        });

        // Click handlers
        segment.on('click', () => {
          const id = cn.corner_id;
          // Use callback form to toggle
          setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
          });
        });
        marker.on('click', () => {
          const id = cn.corner_id;
          setSelected((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
          });
        });

        layers.set(cn.corner_id, { segment, marker });
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
  }, [trackLayout]);

  // ── Update visual selection state ──────────────────
  useEffect(() => {
    layersRef.current.forEach((layer, id) => {
      const isSelected = selected.has(id);
      layer.segment.setStyle({ opacity: isSelected ? 1.0 : 0.25, weight: isSelected ? 6 : 3 });
      layer.marker.setStyle({ fillOpacity: isSelected ? 1.0 : 0.3, opacity: isSelected ? 1.0 : 0.4 });
    });
  }, [selected]);

  const handleSubmit = () => {
    onSubmit(Array.from(selected));
  };

  const totalCorners = trackLayout.corners.length;
  const selectedCount = selected.size;

  return (
    <div className="rounded-lg border border-steel/20 bg-concrete overflow-hidden">
      {/* Map */}
      <div
        ref={mapRef}
        style={{ width: '100%', height: '400px' }}
      />

      {/* Controls */}
      <div className="p-4 border-t border-steel/10">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-3">
            <span className="font-telemetry text-chalk text-sm">
              {selectedCount} / {totalCorners} corners selected
            </span>
            <button
              type="button"
              onClick={selectedCount === totalCorners ? clearAll : selectAll}
              className="text-xs font-telemetry text-pit-orange hover:text-pit-orange/80 transition-colors"
            >
              {selectedCount === totalCorners ? 'Clear All' : 'Select All'}
            </button>
          </div>

          {/* Direction legend */}
          <div className="flex items-center gap-4 text-xs font-telemetry text-steel">
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-1.5 rounded-full" style={{ background: LEFT_COLOR }} />
              Left
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-3 h-1.5 rounded-full" style={{ background: RIGHT_COLOR }} />
              Right
            </span>
          </div>
        </div>

        {/* Corner chips */}
        <div className="flex flex-wrap gap-2 mb-4">
          {trackLayout.corners.map((cn) => {
            const isSelected = selected.has(cn.corner_id);
            const color = cn.direction === 'L' ? LEFT_COLOR : cn.direction === 'R' ? RIGHT_COLOR : NEUTRAL_COLOR;
            const dirArrow = cn.direction === 'L' ? '\u21B0' : cn.direction === 'R' ? '\u21B1' : '';
            return (
              <button
                key={cn.corner_id}
                type="button"
                onClick={() => toggle(cn.corner_id)}
                className={`
                  inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-telemetry
                  border transition-all duration-150
                  ${isSelected
                    ? 'border-chalk/40 text-chalk bg-asphalt'
                    : 'border-steel/20 text-steel/50 bg-concrete'
                  }
                `}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{ background: isSelected ? color : `${color}40` }}
                />
                C{cn.corner_id + 1} {dirArrow}
              </button>
            );
          })}
        </div>

        {/* Submit */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isSubmitting || selectedCount === 0}
          className="w-full px-6 py-3 bg-gold text-carbon font-monument text-sm rounded-lg
            hover:bg-gold/90 transition-colors
            disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-gold"
        >
          {isSubmitting ? 'Resuming Analysis...' : `Continue Analysis (${selectedCount} corners)`}
        </button>
      </div>

      {/* Leaflet tooltip styles */}
      <style jsx global>{`
        .corner-label {
          background: transparent !important;
          border: none !important;
          box-shadow: none !important;
          color: #fff;
          font-size: 10px;
          font-weight: 700;
          text-shadow: 0 0 4px rgba(0,0,0,0.8);
        }
        .corner-label::before {
          display: none;
        }
      `}</style>
    </div>
  );
}
