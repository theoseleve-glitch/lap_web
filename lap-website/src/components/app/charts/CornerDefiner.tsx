/**
 * CornerDefiner.tsx — Interactive canvas for defining corner boundaries.
 *
 * Lets users click on a GPS track map to place entry (green), apex (yellow),
 * and exit (red) markers for user-defined corners. Snaps clicks to the
 * nearest track point and validates distance ordering (entry < apex < exit).
 */
'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@/lib/api-client';

/* ── Types ──────────────────────────────────── */

interface GpsPoint {
  lat: number;
  lon: number;
  dist: number;
  idx: number;
}

interface UserCorner {
  corner_index: number;
  entry: GpsPoint | null;
  apex: GpsPoint | null;
  exit: GpsPoint | null;
}

type PlacementMode = 'entry' | 'apex' | 'exit';

interface CornerDefinerProps {
  sessionId: string;
  latitudes: number[];
  longitudes: number[];
  distances: number[];
  onDone?: (corners: UserCorner[]) => void;
  className?: string;
}

/* ── Colors ─────────────────────────────────── */

const C = {
  bg: '#0B0C0F',
  track: '#30363d',
  trackHighlight: '#58a6ff',
  entry: '#00ff64',      // green
  apex: '#ffd700',       // gold/yellow
  exit: '#ff3c3c',       // red
  text: '#888',
  bright: '#F0EDE5',
  banner: 'rgba(88,166,255,0.15)',
};

/* ── Helpers ────────────────────────────────── */

function findNearestPoint(
  latitudes: number[], longitudes: number[], distances: number[],
  canvasX: number, canvasY: number,
  toCanvas: (lat: number, lon: number) => [number, number],
): GpsPoint | null {
  let bestDist = Infinity;
  let bestIdx = -1;

  for (let i = 0; i < latitudes.length; i++) {
    const [cx, cy] = toCanvas(latitudes[i], longitudes[i]);
    const d = (cx - canvasX) ** 2 + (cy - canvasY) ** 2;
    if (d < bestDist) {
      bestDist = d;
      bestIdx = i;
    }
  }

  if (bestIdx < 0 || bestDist > 400) return null; // 20px snap radius

  return {
    lat: latitudes[bestIdx],
    lon: longitudes[bestIdx],
    dist: distances[bestIdx],
    idx: bestIdx,
  };
}

/* ── Draw ───────────────────────────────────── */

function draw(
  canvas: HTMLCanvasElement,
  latitudes: number[], longitudes: number[], distances: number[],
  corners: UserCorner[],
  activeCorner: number | null,
  placementMode: PlacementMode,
) {
  const ctx = canvas.getContext('2d');
  if (!ctx || latitudes.length < 2) return;

  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = rect.width, h = rect.height;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, w, h);

  // Compute bounds
  const pad = 30;
  let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
  for (let i = 0; i < latitudes.length; i++) {
    if (latitudes[i] < minLat) minLat = latitudes[i];
    if (latitudes[i] > maxLat) maxLat = latitudes[i];
    if (longitudes[i] < minLon) minLon = longitudes[i];
    if (longitudes[i] > maxLon) maxLon = longitudes[i];
  }

  const latRange = maxLat - minLat || 0.001;
  const lonRange = maxLon - minLon || 0.001;
  const plotW = w - 2 * pad;
  const plotH = h - 2 * pad;
  const scale = Math.min(plotW / lonRange, plotH / latRange);

  const toCanvas = (lat: number, lon: number): [number, number] => {
    const x = pad + (lon - minLon) * scale + (plotW - lonRange * scale) / 2;
    const y = pad + (maxLat - lat) * scale + (plotH - latRange * scale) / 2;
    return [x, y];
  };

  // Draw track
  ctx.strokeStyle = C.track;
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let i = 0; i < latitudes.length; i++) {
    const [x, y] = toCanvas(latitudes[i], longitudes[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Draw corner segments
  for (const corner of corners) {
    if (corner.entry && corner.exit) {
      ctx.strokeStyle = C.trackHighlight;
      ctx.lineWidth = 4;
      ctx.beginPath();
      const startIdx = corner.entry.idx;
      const endIdx = corner.exit.idx;
      for (let i = Math.min(startIdx, endIdx); i <= Math.max(startIdx, endIdx); i++) {
        const [x, y] = toCanvas(latitudes[i], longitudes[i]);
        if (i === Math.min(startIdx, endIdx)) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Draw markers
    const drawMarker = (point: GpsPoint | null, color: string, label: string) => {
      if (!point) return;
      const [x, y] = toCanvas(point.lat, point.lon);
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.font = '10px "Space Mono", monospace';
      ctx.textAlign = 'center';
      ctx.fillText(label, x, y - 10);
    };

    drawMarker(corner.entry, C.entry, `C${corner.corner_index} Entry`);
    drawMarker(corner.apex, C.apex, `C${corner.corner_index} Apex`);
    drawMarker(corner.exit, C.exit, `C${corner.corner_index} Exit`);
  }

  // Banner
  ctx.fillStyle = C.text;
  ctx.font = '11px "Space Mono", monospace';
  ctx.textAlign = 'center';
  const modeLabel = activeCorner !== null
    ? `Corner ${activeCorner}: Click to place ${placementMode}`
    : 'Click "Add Corner" to start defining corners';
  ctx.fillText(modeLabel, w / 2, h - 8);
}

/* ── Component ──────────────────────────────── */

export function CornerDefiner({
  sessionId,
  latitudes,
  longitudes,
  distances,
  onDone,
  className = '',
}: CornerDefinerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [corners, setCorners] = useState<UserCorner[]>([]);
  const [activeCorner, setActiveCorner] = useState<number | null>(null);
  const [placementMode, setPlacementMode] = useState<PlacementMode>('entry');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Render function
  const render = useCallback(() => {
    if (!canvasRef.current) return;
    draw(canvasRef.current, latitudes, longitudes, distances, corners, activeCorner, placementMode);
  }, [latitudes, longitudes, distances, corners, activeCorner, placementMode]);

  useEffect(() => { render(); }, [render]);
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ro = new ResizeObserver(() => render());
    ro.observe(c);
    return () => ro.disconnect();
  }, [render]);

  // Canvas click handler
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (activeCorner === null) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    // Compute bounds for toCanvas
    const pad = 30;
    let minLat = Infinity, maxLat = -Infinity, minLon = Infinity, maxLon = -Infinity;
    for (let i = 0; i < latitudes.length; i++) {
      if (latitudes[i] < minLat) minLat = latitudes[i];
      if (latitudes[i] > maxLat) maxLat = latitudes[i];
      if (longitudes[i] < minLon) minLon = longitudes[i];
      if (longitudes[i] > maxLon) maxLon = longitudes[i];
    }
    const w = rect.width, h = rect.height;
    const latRange = maxLat - minLat || 0.001;
    const lonRange = maxLon - minLon || 0.001;
    const plotW = w - 2 * pad;
    const plotH = h - 2 * pad;
    const scale = Math.min(plotW / lonRange, plotH / latRange);
    const toCanvas = (lat: number, lon: number): [number, number] => {
      const cx = pad + (lon - minLon) * scale + (plotW - lonRange * scale) / 2;
      const cy = pad + (maxLat - lat) * scale + (plotH - latRange * scale) / 2;
      return [cx, cy];
    };

    const point = findNearestPoint(latitudes, longitudes, distances, x, y, toCanvas);
    if (!point) return;

    setCorners(prev => {
      const updated = [...prev];
      const idx = updated.findIndex(c => c.corner_index === activeCorner);
      if (idx < 0) return prev;
      const corner = { ...updated[idx] };

      // Validate distance order
      if (placementMode === 'apex' && corner.entry && point.dist <= corner.entry.dist) return prev;
      if (placementMode === 'exit' && corner.apex && point.dist <= corner.apex.dist) return prev;

      corner[placementMode] = point;
      updated[idx] = corner;
      return updated;
    });

    // Auto-advance mode
    if (placementMode === 'entry') setPlacementMode('apex');
    else if (placementMode === 'apex') setPlacementMode('exit');
    else {
      // Exit placed — done with this corner
      setActiveCorner(null);
      setPlacementMode('entry');
    }
  }, [activeCorner, placementMode, latitudes, longitudes, distances]);

  // Add new corner
  const addCorner = () => {
    const nextIndex = corners.length + 1;
    setCorners(prev => [...prev, {
      corner_index: nextIndex,
      entry: null, apex: null, exit: null,
    }]);
    setActiveCorner(nextIndex);
    setPlacementMode('entry');
  };

  // Remove corner
  const removeCorner = (index: number) => {
    setCorners(prev => {
      const filtered = prev.filter(c => c.corner_index !== index);
      // Re-index
      return filtered.map((c, i) => ({ ...c, corner_index: i + 1 }));
    });
    if (activeCorner === index) {
      setActiveCorner(null);
      setPlacementMode('entry');
    }
  };

  // Save
  const handleSave = async () => {
    const valid = corners.filter(c => c.entry && c.apex && c.exit);
    if (valid.length === 0) {
      setError('Define at least one complete corner (entry + apex + exit)');
      return;
    }

    setSaving(true);
    setError(null);
    try {
      const payload = valid.map(c => ({
        corner_index: c.corner_index,
        lat_entry: c.entry!.lat, lon_entry: c.entry!.lon,
        lat_apex: c.apex!.lat, lon_apex: c.apex!.lon,
        lat_exit: c.exit!.lat, lon_exit: c.exit!.lon,
        s_entry: c.entry!.dist, s_apex: c.apex!.dist, s_exit: c.exit!.dist,
      }));

      await api.post(`/sessions/${sessionId}/user-corners`, { corners: payload });

      // Trigger re-coaching with the new user-defined corners
      try {
        await api.post(`/sessions/${sessionId}/recoach`, {});
      } catch {
        // Recoach is best-effort — corners are saved regardless
      }

      onDone?.(valid);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save corners');
    } finally {
      setSaving(false);
    }
  };

  const completedCount = corners.filter(c => c.entry && c.apex && c.exit).length;

  return (
    <div className={`rounded-lg border border-steel/20 bg-concrete overflow-hidden ${className}`}>
      {/* Banner */}
      <div className="px-4 py-2 text-xs font-telemetry text-chalk/70" style={{ background: C.banner }}>
        Define your corners by clicking on the track, or let auto-detection handle it.
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        className="w-full cursor-crosshair"
        style={{ display: 'block', minHeight: '350px' }}
        onClick={handleCanvasClick}
        role="img"
        aria-label="Track map for defining corner boundaries"
      />

      {/* Controls */}
      <div className="p-4 border-t border-steel/10">
        {/* Corner list */}
        <div className="space-y-2 mb-4">
          {corners.map(c => (
            <div key={c.corner_index} className="flex items-center gap-2 text-xs font-telemetry">
              <span className={`w-16 ${activeCorner === c.corner_index ? 'text-chalk' : 'text-steel'}`}>
                C{c.corner_index}
              </span>
              <span className={c.entry ? 'text-green-400' : 'text-steel/40'}>
                {c.entry ? `Entry ${c.entry.dist.toFixed(0)}m` : 'Entry -'}
              </span>
              <span className={c.apex ? 'text-yellow-400' : 'text-steel/40'}>
                {c.apex ? `Apex ${c.apex.dist.toFixed(0)}m` : 'Apex -'}
              </span>
              <span className={c.exit ? 'text-red-400' : 'text-steel/40'}>
                {c.exit ? `Exit ${c.exit.dist.toFixed(0)}m` : 'Exit -'}
              </span>
              <button
                type="button"
                onClick={() => removeCorner(c.corner_index)}
                className="ml-auto text-steel hover:text-red-400 transition-colors"
              >
                x
              </button>
              {activeCorner !== c.corner_index && (
                <button
                  type="button"
                  onClick={() => { setActiveCorner(c.corner_index); setPlacementMode('entry'); }}
                  className="text-steel hover:text-chalk transition-colors"
                >
                  edit
                </button>
              )}
            </div>
          ))}
        </div>

        {error && <p className="text-red-400 text-xs mb-2">{error}</p>}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={addCorner}
            className="flex-1 px-4 py-2 border border-steel/30 text-chalk text-xs font-telemetry
              rounded hover:border-chalk/50 transition-colors"
          >
            + Add Corner
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || completedCount === 0}
            className="flex-1 px-4 py-2 bg-gold text-carbon text-xs font-monument rounded
              hover:bg-gold/90 transition-colors
              disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving...' : `Save ${completedCount} Corner${completedCount !== 1 ? 's' : ''}`}
          </button>
        </div>
      </div>
    </div>
  );
}
