'use client';

import { useEffect, useState, useMemo, useCallback, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { api } from '@/lib/api-client';

// ── Types ────────────────────────────────────────────────────────

interface DriverListItem {
  id: number;
  name: string;
}

interface AvgScores {
  pace: number | null;
  consistency: number | null;
  execution: number | null;
  robustness: number | null;
}

interface TrendPoint {
  session_date: string;
  total_score: number;
}

interface DriverStats {
  sessions: number;
  avg_score: number;
  best_score: number;
  tracks: number;
}

interface DriverSide {
  driver: { id: number; name: string };
  avg_scores: AvgScores;
  trend: TrendPoint[];
  stats: DriverStats;
}

interface ComparisonData {
  driver_a: DriverSide;
  driver_b: DriverSide;
}

// ── Helpers ──────────────────────────────────────────────────────

function deltaColor(delta: number): string {
  if (delta === 0) return 'text-steel';
  return delta > 0 ? 'text-green-400' : 'text-red-400';
}

function formatDelta(delta: number | null, decimals = 1): string {
  if (delta == null || !isFinite(delta)) return '--';
  const sign = delta > 0 ? '+' : '';
  return `${sign}${delta.toFixed(decimals)}`;
}

// ── Driver Selector Dropdown ────────────────────────────────────

function DriverSelector({
  label,
  drivers,
  selectedId,
  onChange,
  accentColor,
}: {
  label: string;
  drivers: DriverListItem[];
  selectedId: string;
  onChange: (id: string) => void;
  accentColor: string;
}) {
  return (
    <div className="flex-1">
      <label className="block text-xs font-monument uppercase tracking-wider mb-2" style={{ color: accentColor }}>
        {label}
      </label>
      <select
        value={selectedId}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-concrete border border-steel/30 rounded px-3 py-2.5 text-chalk font-body text-sm
          focus:outline-none focus:ring-1 appearance-none cursor-pointer"
        style={{
          borderColor: selectedId ? accentColor + '40' : undefined,
          // @ts-expect-error -- focus ring color
          '--tw-ring-color': accentColor + '50',
        }}
      >
        <option value="">Select a driver...</option>
        {drivers.map((d) => (
          <option key={d.id} value={String(d.id)}>
            {d.name}
          </option>
        ))}
      </select>
    </div>
  );
}

// ── Score Comparison Card ───────────────────────────────────────

function ScoreCompareCard({
  label,
  scoreA,
  scoreB,
  max,
  colorA,
  colorB,
}: {
  label: string;
  scoreA: number | null;
  scoreB: number | null;
  max: number;
  colorA: string;
  colorB: string;
}) {
  const pctA = scoreA != null ? Math.min((scoreA / max) * 100, 100) : 0;
  const pctB = scoreB != null ? Math.min((scoreB / max) * 100, 100) : 0;
  const delta = scoreA != null && scoreB != null ? scoreA - scoreB : null;

  return (
    <div className="bg-concrete rounded-xl border border-steel/10 p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-monument text-chalk">{label}</h4>
        {delta != null && (
          <span className={`text-xs font-telemetry ${deltaColor(delta)}`}>
            A {formatDelta(delta)}
          </span>
        )}
      </div>

      {/* Driver A bar */}
      <div className="mb-2">
        <div className="flex justify-between text-xs mb-1">
          <span className="font-body" style={{ color: colorA }}>Driver A</span>
          <span className="font-telemetry text-chalk">
            {scoreA != null ? scoreA.toFixed(1) : '--'} / {max}
          </span>
        </div>
        <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pctA}%`, backgroundColor: colorA }}
          />
        </div>
      </div>

      {/* Driver B bar */}
      <div>
        <div className="flex justify-between text-xs mb-1">
          <span className="font-body" style={{ color: colorB }}>Driver B</span>
          <span className="font-telemetry text-chalk">
            {scoreB != null ? scoreB.toFixed(1) : '--'} / {max}
          </span>
        </div>
        <div className="w-full h-2 bg-asphalt rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{ width: `${pctB}%`, backgroundColor: colorB }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Radar Chart (Canvas 2D) ─────────────────────────────────────

const RADAR_LABELS = ['Pace', 'Consistency', 'Execution', 'Robustness'];
const RADAR_MAX = 25;
const RADAR_RINGS = [5, 10, 15, 20, 25];

function RadarChart({
  scoresA,
  scoresB,
  colorA,
  colorB,
  driverAName,
  driverBName,
}: {
  scoresA: AvgScores;
  scoresB: AvgScores;
  colorA: string;
  colorB: string;
  driverAName: string;
  driverBName: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const maybeCtx = canvas.getContext('2d');
    if (!maybeCtx) return;
    const c = maybeCtx; // non-null alias for nested functions

    const dpr = window.devicePixelRatio || 1;
    const logicalW = 400;
    const logicalH = 400;
    canvas.width = logicalW * dpr;
    canvas.height = logicalH * dpr;
    canvas.style.width = `${logicalW}px`;
    canvas.style.height = `${logicalH}px`;
    c.scale(dpr, dpr);

    const cx = logicalW / 2;
    const cy = logicalH / 2;
    const radius = 140;
    const numAxes = 4;
    const angleStep = (2 * Math.PI) / numAxes;
    const startAngle = -Math.PI / 2; // Top

    // Clear
    c.clearRect(0, 0, logicalW, logicalH);

    // Draw grid rings
    c.strokeStyle = '#8A8F9830';
    c.lineWidth = 1;
    for (const ring of RADAR_RINGS) {
      const r = (ring / RADAR_MAX) * radius;
      c.beginPath();
      for (let i = 0; i <= numAxes; i++) {
        const angle = startAngle + i * angleStep;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.closePath();
      c.stroke();
    }

    // Draw axes
    c.strokeStyle = '#8A8F9850';
    c.lineWidth = 1;
    for (let i = 0; i < numAxes; i++) {
      const angle = startAngle + i * angleStep;
      c.beginPath();
      c.moveTo(cx, cy);
      c.lineTo(cx + radius * Math.cos(angle), cy + radius * Math.sin(angle));
      c.stroke();
    }

    // Draw axis labels
    c.fillStyle = '#F3F0E8';
    c.font = '13px Inter, sans-serif';
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    const labelOffset = 20;
    for (let i = 0; i < numAxes; i++) {
      const angle = startAngle + i * angleStep;
      const lx = cx + (radius + labelOffset) * Math.cos(angle);
      const ly = cy + (radius + labelOffset) * Math.sin(angle);
      c.fillText(RADAR_LABELS[i], lx, ly);
    }

    // Draw ring value labels (right side of top axis)
    c.fillStyle = '#8A8F98';
    c.font = '10px IBM Plex Mono, monospace';
    c.textAlign = 'left';
    c.textBaseline = 'middle';
    for (const ring of RADAR_RINGS) {
      const r = (ring / RADAR_MAX) * radius;
      c.fillText(String(ring), cx + 4, cy - r);
    }

    // Helper to draw a polygon for a set of scores
    function drawPolygon(
      scores: (number | null)[],
      strokeColor: string,
      fillColor: string,
    ) {
      c.beginPath();
      for (let i = 0; i < numAxes; i++) {
        const val = Math.max(0, Math.min(scores[i] ?? 0, RADAR_MAX));
        const r = (val / RADAR_MAX) * radius;
        const angle = startAngle + i * angleStep;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.closePath();
      c.fillStyle = fillColor;
      c.fill();
      c.strokeStyle = strokeColor;
      c.lineWidth = 2;
      c.stroke();

      // Draw dots at vertices
      for (let i = 0; i < numAxes; i++) {
        const val = Math.max(0, Math.min(scores[i] ?? 0, RADAR_MAX));
        const r = (val / RADAR_MAX) * radius;
        const angle = startAngle + i * angleStep;
        const x = cx + r * Math.cos(angle);
        const y = cy + r * Math.sin(angle);
        c.beginPath();
        c.arc(x, y, 4, 0, 2 * Math.PI);
        c.fillStyle = strokeColor;
        c.fill();
      }
    }

    const valsA = [scoresA.pace, scoresA.consistency, scoresA.execution, scoresA.robustness];
    const valsB = [scoresB.pace, scoresB.consistency, scoresB.execution, scoresB.robustness];

    // Draw B first (behind), then A
    drawPolygon(valsB, colorB, colorB + '4D'); // 0.3 alpha ~ 4D hex
    drawPolygon(valsA, colorA, colorA + '4D');

    // Legend
    const legendY = logicalH - 16;
    c.font = '11px Inter, sans-serif';

    // Driver A legend
    c.fillStyle = colorA;
    c.fillRect(cx - 120, legendY - 6, 12, 12);
    c.fillStyle = '#F3F0E8';
    c.textAlign = 'left';
    c.fillText(driverAName, cx - 104, legendY);

    // Driver B legend
    c.fillStyle = colorB;
    c.fillRect(cx + 20, legendY - 6, 12, 12);
    c.fillStyle = '#F3F0E8';
    c.fillText(driverBName, cx + 36, legendY);
  }, [scoresA, scoresB, colorA, colorB, driverAName, driverBName]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full max-w-[400px] h-auto mx-auto"
      style={{ aspectRatio: '1 / 1' }}
    />
  );
}

// ── Trend Line Chart (Canvas 2D) ────────────────────────────────

function TrendChart({
  trendA,
  trendB,
  colorA,
  colorB,
  driverAName,
  driverBName,
}: {
  trendA: TrendPoint[];
  trendB: TrendPoint[];
  colorA: string;
  colorB: string;
  driverAName: string;
  driverBName: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const maybeCtx = canvas.getContext('2d');
    if (!maybeCtx) return;
    const c = maybeCtx; // non-null alias for nested functions

    const dpr = window.devicePixelRatio || 1;
    const logicalW = 600;
    const logicalH = 400;
    canvas.width = logicalW * dpr;
    canvas.height = logicalH * dpr;
    canvas.style.width = '100%';
    canvas.style.height = 'auto';
    c.scale(dpr, dpr);

    // Chart area with margins
    const marginLeft = 50;
    const marginRight = 20;
    const marginTop = 20;
    const marginBottom = 60;
    const chartW = logicalW - marginLeft - marginRight;
    const chartH = logicalH - marginTop - marginBottom;

    c.clearRect(0, 0, logicalW, logicalH);

    // Combine all dates for the x-axis
    const allDates = [
      ...trendA.map((p) => p.session_date),
      ...trendB.map((p) => p.session_date),
    ].sort();
    const uniqueDates = Array.from(new Set(allDates));

    if (uniqueDates.length === 0) {
      c.fillStyle = '#8A8F98';
      c.font = '14px Inter, sans-serif';
      c.textAlign = 'center';
      c.fillText('No trend data available', logicalW / 2, logicalH / 2);
      return;
    }

    const yMin = 0;
    const yMax = 100;
    const ySteps = [0, 20, 40, 60, 80, 100];

    // Map date string to x position
    function dateToX(date: string): number {
      const idx = uniqueDates.indexOf(date);
      if (uniqueDates.length === 1) return marginLeft + chartW / 2;
      return marginLeft + (idx / (uniqueDates.length - 1)) * chartW;
    }

    function valToY(val: number): number {
      return marginTop + chartH - ((val - yMin) / (yMax - yMin)) * chartH;
    }

    // Draw Y grid lines
    c.strokeStyle = '#8A8F9820';
    c.lineWidth = 1;
    c.fillStyle = '#8A8F98';
    c.font = '10px IBM Plex Mono, monospace';
    c.textAlign = 'right';
    c.textBaseline = 'middle';
    for (const step of ySteps) {
      const y = valToY(step);
      c.beginPath();
      c.moveTo(marginLeft, y);
      c.lineTo(marginLeft + chartW, y);
      c.stroke();
      c.fillText(String(step), marginLeft - 8, y);
    }

    // Draw X axis labels (show a subset if many)
    c.fillStyle = '#8A8F98';
    c.font = '10px IBM Plex Mono, monospace';
    c.textAlign = 'center';
    c.textBaseline = 'top';
    const maxLabels = 8;
    const labelStep = Math.max(1, Math.ceil(uniqueDates.length / maxLabels));
    for (let i = 0; i < uniqueDates.length; i += labelStep) {
      const x = dateToX(uniqueDates[i]);
      // Shorten date display
      const shortDate = uniqueDates[i].slice(5); // "MM-DD" from "YYYY-MM-DD"
      c.save();
      c.translate(x, marginTop + chartH + 8);
      c.rotate(Math.PI / 6);
      c.fillText(shortDate, 0, 0);
      c.restore();
    }

    // Y axis label
    c.save();
    c.fillStyle = '#8A8F98';
    c.font = '11px Inter, sans-serif';
    c.textAlign = 'center';
    c.translate(14, marginTop + chartH / 2);
    c.rotate(-Math.PI / 2);
    c.fillText('Total Score', 0, 0);
    c.restore();

    // Draw line for a trend dataset
    function drawLine(trend: TrendPoint[], color: string) {
      if (trend.length === 0) return;

      const sorted = [...trend].sort((a, b) => a.session_date.localeCompare(b.session_date));

      c.strokeStyle = color;
      c.lineWidth = 2;
      c.lineJoin = 'round';
      c.lineCap = 'round';
      c.beginPath();
      for (let i = 0; i < sorted.length; i++) {
        const x = dateToX(sorted[i].session_date);
        const y = valToY(sorted[i].total_score);
        if (i === 0) c.moveTo(x, y);
        else c.lineTo(x, y);
      }
      c.stroke();

      // Dots
      for (const pt of sorted) {
        const x = dateToX(pt.session_date);
        const y = valToY(pt.total_score);
        c.beginPath();
        c.arc(x, y, 4, 0, 2 * Math.PI);
        c.fillStyle = color;
        c.fill();
        c.strokeStyle = '#161A20';
        c.lineWidth = 1.5;
        c.stroke();
      }
    }

    drawLine(trendB, colorB);
    drawLine(trendA, colorA);

    // Legend
    const legendY = logicalH - 12;
    c.font = '11px Inter, sans-serif';
    c.textBaseline = 'middle';

    c.fillStyle = colorA;
    c.fillRect(logicalW / 2 - 120, legendY - 6, 12, 12);
    c.fillStyle = '#F3F0E8';
    c.textAlign = 'left';
    c.fillText(driverAName, logicalW / 2 - 104, legendY);

    c.fillStyle = colorB;
    c.fillRect(logicalW / 2 + 20, legendY - 6, 12, 12);
    c.fillStyle = '#F3F0E8';
    c.fillText(driverBName, logicalW / 2 + 36, legendY);
  }, [trendA, trendB, colorA, colorB, driverAName, driverBName]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full"
      style={{ aspectRatio: '3 / 2' }}
    />
  );
}

// ── Summary Stats Table ─────────────────────────────────────────

function CompareRow({
  label,
  valueA,
  valueB,
  delta,
  deltaColorClass,
}: {
  label: string;
  valueA: string;
  valueB: string;
  delta: string | null;
  deltaColorClass: string;
}) {
  return (
    <tr className="border-b border-steel/5 hover:bg-asphalt/50 transition-colors">
      <td className="px-4 py-3 text-steel font-body text-sm">{label}</td>
      <td className="px-4 py-3 text-right font-telemetry text-chalk text-sm">{valueA}</td>
      <td className="px-4 py-3 text-right font-telemetry text-chalk text-sm">{valueB}</td>
      <td className={`px-4 py-3 text-right font-telemetry text-sm ${deltaColorClass}`}>
        {delta ?? '--'}
      </td>
    </tr>
  );
}

// ── Main Page ───────────────────────────────────────────────────

const COLOR_A = '#3ddc84'; // acid-green
const COLOR_B = '#ff8c00'; // pit-orange

export default function CompareDriversPage() {
  const searchParams = useSearchParams();

  const [drivers, setDrivers] = useState<DriverListItem[]>([]);
  const [loadingDrivers, setLoadingDrivers] = useState(true);

  const [driverAId, setDriverAId] = useState('');
  const [driverBId, setDriverBId] = useState('');

  const [comparison, setComparison] = useState<ComparisonData | null>(null);
  const [loadingComparison, setLoadingComparison] = useState(false);
  const [compError, setCompError] = useState<string | null>(null);

  // Pre-populate from URL search params (?a=...&b=...)
  useEffect(() => {
    const paramA = searchParams.get('a');
    const paramB = searchParams.get('b');
    if (paramA) setDriverAId(paramA);
    if (paramB) setDriverBId(paramB);
  }, [searchParams]);

  // Fetch drivers list
  useEffect(() => {
    let cancelled = false;

    async function fetchDrivers() {
      setLoadingDrivers(true);
      try {
        const res = await api.get<DriverListItem[]>('/drivers');
        if (!cancelled) {
          setDrivers(Array.isArray(res) ? res : []);
        }
      } catch {
        // Non-critical -- show empty list
      } finally {
        if (!cancelled) setLoadingDrivers(false);
      }
    }

    fetchDrivers();
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetch comparison when both selected
  useEffect(() => {
    if (!driverAId || !driverBId) {
      setComparison(null);
      setCompError(null);
      return;
    }

    let cancelled = false;

    async function fetchComparison() {
      setLoadingComparison(true);
      setCompError(null);

      try {
        const res = await api.get<ComparisonData>(
          `/compare/drivers?a=${encodeURIComponent(driverAId)}&b=${encodeURIComponent(driverBId)}`,
        );
        if (!cancelled) {
          setComparison(res);
        }
      } catch (err) {
        if (!cancelled) {
          setCompError(err instanceof Error ? err.message : 'Failed to load comparison');
        }
      } finally {
        if (!cancelled) setLoadingComparison(false);
      }
    }

    fetchComparison();
    return () => {
      cancelled = true;
    };
  }, [driverAId, driverBId]);

  const swapDrivers = useCallback(() => {
    const oldA = driverAId;
    const oldB = driverBId;
    setDriverAId(oldB);
    setDriverBId(oldA);
  }, [driverAId, driverBId]);

  // ── Derived comparison stats ──────────────────────────────────

  const compStats = useMemo(() => {
    if (!comparison) return null;

    const a = comparison.driver_a;
    const b = comparison.driver_b;

    const sessionsDelta = a.stats.sessions - b.stats.sessions;
    const avgScoreDelta = a.stats.avg_score - b.stats.avg_score;
    const bestScoreDelta = a.stats.best_score - b.stats.best_score;
    const tracksDelta = a.stats.tracks - b.stats.tracks;

    return { sessionsDelta, avgScoreDelta, bestScoreDelta, tracksDelta };
  }, [comparison]);

  // ── Render ────────────────────────────────────────────────────

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-monument text-chalk tracking-tight">Compare Drivers</h1>
        <p className="text-steel text-sm font-body mt-1">
          Select two drivers to compare their average scores, trends, and performance statistics side by side.
        </p>
      </div>

      {/* Driver selectors */}
      <div className="bg-concrete rounded-xl border border-steel/10 p-5 mb-6">
        {loadingDrivers ? (
          <div className="flex items-center justify-center py-4">
            <div className="w-5 h-5 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
            <span className="text-steel font-body text-sm">Loading drivers...</span>
          </div>
        ) : (
          <div className="flex items-end gap-4">
            <DriverSelector
              label="Driver A"
              drivers={drivers}
              selectedId={driverAId}
              onChange={setDriverAId}
              accentColor={COLOR_A}
            />

            <button
              type="button"
              onClick={swapDrivers}
              className="shrink-0 mb-0.5 p-2 rounded-lg border border-steel/20 text-steel hover:text-chalk hover:border-steel/40 transition-colors"
              title="Swap drivers"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
                <path
                  fillRule="evenodd"
                  d="M13.2 2.24a.75.75 0 00.04 1.06l2.1 1.95H6.75a.75.75 0 000 1.5h8.59l-2.1 1.95a.75.75 0 101.02 1.1l3.5-3.25a.75.75 0 000-1.1l-3.5-3.25a.75.75 0 00-1.06.04zm-6.4 8a.75.75 0 00-1.06-.04l-3.5 3.25a.75.75 0 000 1.1l3.5 3.25a.75.75 0 101.02-1.1l-2.1-1.95h8.59a.75.75 0 000-1.5H4.66l2.1-1.95a.75.75 0 00.04-1.06z"
                  clipRule="evenodd"
                />
              </svg>
            </button>

            <DriverSelector
              label="Driver B"
              drivers={drivers}
              selectedId={driverBId}
              onChange={setDriverBId}
              accentColor={COLOR_B}
            />
          </div>
        )}
      </div>

      {/* Loading comparison */}
      {loadingComparison && (
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-acid-green border-t-transparent rounded-full animate-spin mr-3" />
          <span className="text-steel font-body text-sm">Comparing drivers...</span>
        </div>
      )}

      {/* Comparison error */}
      {compError && (
        <div className="bg-concrete rounded-xl border border-safety-red/30 p-6 text-center">
          <p className="text-safety-red font-body text-sm">{compError}</p>
        </div>
      )}

      {/* Empty state */}
      {!driverAId && !driverBId && !loadingComparison && (
        <div className="bg-concrete rounded-xl border border-steel/10 p-12 text-center">
          <p className="font-telemetry text-4xl text-steel/30 mb-4">vs</p>
          <h2 className="font-monument text-lg text-chalk mb-2">Pick Two Drivers</h2>
          <p className="text-steel font-body text-sm max-w-md mx-auto">
            Use the dropdowns above to select two drivers. The comparison will load automatically.
          </p>
        </div>
      )}

      {/* Comparison results */}
      {comparison && !loadingComparison && (
        <div className="space-y-6">
          {/* ── Score Comparison Cards (2x2 grid) ──────────── */}
          <div>
            <h2 className="text-lg font-monument text-chalk mb-4">Score Breakdown</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ScoreCompareCard
                label="Pace"
                scoreA={comparison.driver_a.avg_scores.pace}
                scoreB={comparison.driver_b.avg_scores.pace}
                max={25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Consistency"
                scoreA={comparison.driver_a.avg_scores.consistency}
                scoreB={comparison.driver_b.avg_scores.consistency}
                max={25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Execution"
                scoreA={comparison.driver_a.avg_scores.execution}
                scoreB={comparison.driver_b.avg_scores.execution}
                max={25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
              <ScoreCompareCard
                label="Robustness"
                scoreA={comparison.driver_a.avg_scores.robustness}
                scoreB={comparison.driver_b.avg_scores.robustness}
                max={25}
                colorA={COLOR_A}
                colorB={COLOR_B}
              />
            </div>
          </div>

          {/* ── Radar + Trend Charts (side by side) ─────── */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Radar Chart */}
            <div className="bg-concrete rounded-xl border border-steel/10 p-5">
              <h2 className="text-lg font-monument text-chalk mb-4">Score Profile</h2>
              <RadarChart
                scoresA={comparison.driver_a.avg_scores}
                scoresB={comparison.driver_b.avg_scores}
                colorA={COLOR_A}
                colorB={COLOR_B}
                driverAName={comparison.driver_a.driver.name}
                driverBName={comparison.driver_b.driver.name}
              />
            </div>

            {/* Trend Line Chart */}
            <div className="bg-concrete rounded-xl border border-steel/10 p-5">
              <h2 className="text-lg font-monument text-chalk mb-4">Score Trend</h2>
              <TrendChart
                trendA={comparison.driver_a.trend}
                trendB={comparison.driver_b.trend}
                colorA={COLOR_A}
                colorB={COLOR_B}
                driverAName={comparison.driver_a.driver.name}
                driverBName={comparison.driver_b.driver.name}
              />
            </div>
          </div>

          {/* ── Summary Stats Table ────────────────────── */}
          <div>
            <h2 className="text-lg font-monument text-chalk mb-4">Summary Statistics</h2>
            <div className="bg-concrete rounded-xl border border-steel/10 overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-steel/10">
                      <th className="text-left px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                        Stat
                      </th>
                      <th className="text-right px-4 py-3 font-body font-normal text-xs uppercase tracking-wider" style={{ color: COLOR_A }}>
                        {comparison.driver_a.driver.name}
                      </th>
                      <th className="text-right px-4 py-3 font-body font-normal text-xs uppercase tracking-wider" style={{ color: COLOR_B }}>
                        {comparison.driver_b.driver.name}
                      </th>
                      <th className="text-right px-4 py-3 text-steel font-body font-normal text-xs uppercase tracking-wider">
                        Delta
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    <CompareRow
                      label="Sessions"
                      valueA={String(comparison.driver_a.stats.sessions)}
                      valueB={String(comparison.driver_b.stats.sessions)}
                      delta={
                        compStats
                          ? formatDelta(compStats.sessionsDelta, 0)
                          : null
                      }
                      deltaColorClass={
                        compStats ? deltaColor(compStats.sessionsDelta) : 'text-steel'
                      }
                    />
                    <CompareRow
                      label="Avg Score"
                      valueA={comparison.driver_a.stats.avg_score?.toFixed(1) ?? '—'}
                      valueB={comparison.driver_b.stats.avg_score?.toFixed(1) ?? '—'}
                      delta={
                        compStats
                          ? formatDelta(compStats.avgScoreDelta)
                          : null
                      }
                      deltaColorClass={
                        compStats ? deltaColor(compStats.avgScoreDelta) : 'text-steel'
                      }
                    />
                    <CompareRow
                      label="Best Score"
                      valueA={comparison.driver_a.stats.best_score?.toFixed(1) ?? '—'}
                      valueB={comparison.driver_b.stats.best_score?.toFixed(1) ?? '—'}
                      delta={
                        compStats
                          ? formatDelta(compStats.bestScoreDelta)
                          : null
                      }
                      deltaColorClass={
                        compStats ? deltaColor(compStats.bestScoreDelta) : 'text-steel'
                      }
                    />
                    <CompareRow
                      label="Tracks"
                      valueA={String(comparison.driver_a.stats.tracks)}
                      valueB={String(comparison.driver_b.stats.tracks)}
                      delta={
                        compStats
                          ? formatDelta(compStats.tracksDelta, 0)
                          : null
                      }
                      deltaColorClass={
                        compStats ? deltaColor(compStats.tracksDelta) : 'text-steel'
                      }
                    />
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
