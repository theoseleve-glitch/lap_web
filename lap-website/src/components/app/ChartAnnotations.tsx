/**
 * ChartAnnotations.tsx — Overlay annotation markers on canvas charts.
 *
 * Users double-click on the speed trace to add text annotations at specific
 * distance points. Annotations are persisted in localStorage per session.
 */
'use client';

import { useState, useEffect, useCallback, useRef } from 'react';

interface Annotation {
  id: string;
  distance: number; // meters
  text: string;
  color: string;
  createdAt: string;
}

const STORAGE_PREFIX = 'chart_annotations_';
const COLORS = ['#22C55E', '#FACC15', '#FF2A2A', '#58a6ff', '#bc8cff', '#C9A84C'];

function loadAnnotations(sessionId: string): Annotation[] {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + sessionId);
    if (raw) return JSON.parse(raw);
  } catch {}
  return [];
}

function saveAnnotations(sessionId: string, anns: Annotation[]) {
  try { localStorage.setItem(STORAGE_PREFIX + sessionId, JSON.stringify(anns)); } catch {}
}

interface Props {
  sessionId: string;
  /** ID of the canvas element to annotate */
  canvasId?: string;
}

export function ChartAnnotations({ sessionId, canvasId = 'speed-chart' }: Props) {
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [showPanel, setShowPanel] = useState(false);
  const colorIdx = useRef(0);

  useEffect(() => {
    setAnnotations(loadAnnotations(sessionId));
  }, [sessionId]);

  const addAnnotation = useCallback((distance: number) => {
    const id = `ann_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
    const color = COLORS[colorIdx.current % COLORS.length] ?? '#22C55E';
    colorIdx.current++;
    const ann: Annotation = {
      id,
      distance,
      text: 'Note',
      color,
      createdAt: new Date().toISOString(),
    };
    const updated = [...annotations, ann];
    setAnnotations(updated);
    saveAnnotations(sessionId, updated);
    setEditing(id);
    setEditText('Note');
  }, [annotations, sessionId]);

  const updateAnnotation = useCallback((id: string, text: string) => {
    const updated = annotations.map((a) => a.id === id ? { ...a, text } : a);
    setAnnotations(updated);
    saveAnnotations(sessionId, updated);
    setEditing(null);
  }, [annotations, sessionId]);

  const removeAnnotation = useCallback((id: string) => {
    const updated = annotations.filter((a) => a.id !== id);
    setAnnotations(updated);
    saveAnnotations(sessionId, updated);
  }, [annotations, sessionId]);

  // Listen for double-click on the canvas to add annotations
  useEffect(() => {
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
    if (!canvas) return;

    const handleDblClick = (e: MouseEvent) => {
      // Get chart bounds from ChartSync
      const cs = (window as unknown as { ChartSync?: { getChartBounds: () => { xMin: number; xMax: number; plotX: number; plotW: number } | null } }).ChartSync;
      const bounds = cs?.getChartBounds?.();
      if (!bounds) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const x = (e.clientX - rect.left) * scaleX;

      // Convert pixel to distance
      const relX = (x - bounds.plotX) / bounds.plotW;
      if (relX < 0 || relX > 1) return;
      const distance = bounds.xMin + relX * (bounds.xMax - bounds.xMin);
      addAnnotation(distance);
    };

    canvas.addEventListener('dblclick', handleDblClick);
    return () => canvas.removeEventListener('dblclick', handleDblClick);
  }, [canvasId, addAnnotation]);

  // Draw annotation markers on canvas after each redraw
  useEffect(() => {
    if (annotations.length === 0) return;
    const canvas = document.getElementById(canvasId) as HTMLCanvasElement | null;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const cs = (window as unknown as { ChartSync?: { getChartBounds: () => { xMin: number; xMax: number; yMin: number; yMax: number; plotX: number; plotY: number; plotW: number; plotH: number } | null } }).ChartSync;
    const bounds = cs?.getChartBounds?.();
    if (!bounds) return;

    // Draw markers
    for (const ann of annotations) {
      const relX = (ann.distance - bounds.xMin) / (bounds.xMax - bounds.xMin);
      if (relX < 0 || relX > 1) continue;
      const px = bounds.plotX + relX * bounds.plotW;

      // Vertical line
      ctx.strokeStyle = ann.color;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(px, bounds.plotY);
      ctx.lineTo(px, bounds.plotY + bounds.plotH);
      ctx.stroke();
      ctx.setLineDash([]);

      // Label
      ctx.fillStyle = ann.color;
      ctx.font = '10px Inter, sans-serif';
      ctx.fillText(ann.text, px + 3, bounds.plotY + 12);
    }
  }, [annotations, canvasId]);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setShowPanel(!showPanel)}
        className={`text-[10px] font-telemetry px-2 py-0.5 rounded border transition-colors ${
          annotations.length > 0
            ? 'border-pit-orange/40 text-pit-orange'
            : 'border-steel/20 text-steel hover:text-chalk'
        }`}
        title="Chart annotations"
      >
        {annotations.length > 0 ? `${annotations.length} note${annotations.length !== 1 ? 's' : ''}` : 'Annotate'}
      </button>

      {showPanel && annotations.length > 0 && (
        <div className="absolute right-0 top-full mt-1 z-30 bg-concrete border border-steel/20 rounded-lg p-3 shadow-xl min-w-[220px] max-h-[200px] overflow-y-auto">
          <p className="text-[10px] font-telemetry text-steel/60 uppercase tracking-wider mb-2">Annotations</p>
          {annotations.map((ann) => (
            <div key={ann.id} className="flex items-center gap-2 py-1">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: ann.color }} />
              {editing === ann.id ? (
                <input
                  type="text"
                  value={editText}
                  onChange={(e) => setEditText(e.target.value)}
                  onBlur={() => updateAnnotation(ann.id, editText)}
                  onKeyDown={(e) => { if (e.key === 'Enter') updateAnnotation(ann.id, editText); }}
                  className="flex-1 bg-asphalt border border-steel/20 text-chalk text-xs rounded px-1 py-0.5 focus:outline-none"
                  autoFocus
                />
              ) : (
                <span
                  className="flex-1 text-xs font-body text-chalk cursor-pointer hover:text-acid-green"
                  onClick={() => { setEditing(ann.id); setEditText(ann.text); }}
                >
                  {ann.text}
                </span>
              )}
              <span className="text-[9px] font-telemetry text-steel/40">{Math.round(ann.distance)}m</span>
              <button
                type="button"
                onClick={() => removeAnnotation(ann.id)}
                className="text-safety-red/60 hover:text-safety-red text-xs"
                title="Remove"
              >
                x
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
