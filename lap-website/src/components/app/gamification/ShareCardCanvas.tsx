'use client';

import { useRef, useEffect, useCallback } from 'react';

interface ShareCardCanvasProps {
  sessionData: {
    trackName?: string;
    driverName?: string;
    sessionDate?: string;
    sessionType?: string;
    bestLapTime?: number | null;
    totalScore?: number | null;
    grade?: string | null;
    nLaps?: number | null;
    cvPct?: number | null;
    badges?: { id: string; tier: string }[];
  };
  className?: string;
}

const CANVAS_W = 1200;
const CANVAS_H = 630;

const GRADE_COLORS: Record<string, string> = {
  'A+': '#B6FF2E',
  A: '#B6FF2E',
  B: '#00d4ff',
  C: '#FFD400',
  D: '#FF6A00',
  F: '#FF3B6B',
};

function gradeColor(grade: string | null | undefined): string {
  if (!grade) return '#555';
  return GRADE_COLORS[grade.toUpperCase()] ?? '#555';
}

function formatLapTime(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return '--:--.---';
  const mins = Math.floor(seconds / 60);
  const secs = seconds - mins * 60;
  const wholeS = Math.floor(secs);
  const ms = Math.round((secs - wholeS) * 1000);
  return `${mins}:${String(wholeS).padStart(2, '0')}.${String(ms).padStart(3, '0')}`;
}

const TIER_HEX_COLORS: Record<string, [string, string]> = {
  gold: ['#FFD700', '#FFA500'],
  silver: ['#E0E0E0', '#A0A0A0'],
  bronze: ['#CD7F32', '#8B4513'],
};

const BADGE_LABELS: Record<string, string> = {
  pace_master: 'Pace',
  consistency_champion: 'Consistency',
  execution_expert: 'Execution',
  endurance_warrior: 'Endurance',
  adaptor: 'Adaptation',
  flow_state: 'Flow State',
};

function drawHexBadge(ctx: CanvasRenderingContext2D, cx: number, cy: number, size: number, tier: string) {
  const [c1, c2] = TIER_HEX_COLORS[tier] || TIER_HEX_COLORS.bronze;
  const r = size / 2;
  const pts: [number, number][] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    pts.push([cx + r * Math.cos(angle), cy + r * Math.sin(angle)]);
  }
  // Outer hex (gradient stroke)
  const grad = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
  grad.addColorStop(0, c1);
  grad.addColorStop(1, c2);
  ctx.beginPath();
  pts.forEach(([x, y], i) => i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y));
  ctx.closePath();
  ctx.strokeStyle = grad;
  ctx.lineWidth = 3;
  ctx.stroke();
  // Inner fill
  const ir = r * 0.85;
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 2;
    const px = cx + ir * Math.cos(angle);
    const py = cy + ir * Math.sin(angle);
    i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
  }
  ctx.closePath();
  ctx.fillStyle = '#000000';
  ctx.fill();
  // Star inside
  ctx.font = `${Math.round(size * 0.35)}px sans-serif`;
  ctx.fillStyle = c1;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('\u2605', cx, cy + 1);
}

function drawCard(
  ctx: CanvasRenderingContext2D,
  data: ShareCardCanvasProps['sessionData'],
) {
  const w = CANVAS_W;
  const h = CANVAS_H;
  const pad = 48;
  const cornerR = 32;

  // -- Clip to rounded rect --
  ctx.save();
  ctx.beginPath();
  ctx.roundRect(0, 0, w, h, cornerR);
  ctx.clip();

  // -- Background: metallic gradient --
  const bg = ctx.createLinearGradient(0, 0, w, h);
  bg.addColorStop(0, '#0D0E12');
  bg.addColorStop(0.3, '#14161E');
  bg.addColorStop(0.5, '#1A1C28');
  bg.addColorStop(0.7, '#14161E');
  bg.addColorStop(1, '#0D0E12');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  // -- Metallic shimmer (diagonal light streak) --
  const shimmer = ctx.createLinearGradient(0, 0, w * 0.8, h * 0.5);
  shimmer.addColorStop(0, 'rgba(255,255,255,0)');
  shimmer.addColorStop(0.4, 'rgba(255,255,255,0.015)');
  shimmer.addColorStop(0.5, 'rgba(255,255,255,0.04)');
  shimmer.addColorStop(0.6, 'rgba(255,255,255,0.015)');
  shimmer.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = shimmer;
  ctx.fillRect(0, 0, w, h);

  // -- Corner glow (top-right, acid green) --
  const glow = ctx.createRadialGradient(w - 100, 100, 0, w - 100, 100, 500);
  glow.addColorStop(0, 'rgba(182, 255, 46, 0.05)');
  glow.addColorStop(1, 'rgba(182, 255, 46, 0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);

  // -- Bottom-left warm glow --
  const glow2 = ctx.createRadialGradient(100, h - 80, 0, 100, h - 80, 400);
  glow2.addColorStop(0, 'rgba(255, 165, 0, 0.03)');
  glow2.addColorStop(1, 'rgba(255, 165, 0, 0)');
  ctx.fillStyle = glow2;
  ctx.fillRect(0, 0, w, h);

  // -- Subtle border (metallic edge) --
  ctx.beginPath();
  ctx.roundRect(1, 1, w - 2, h - 2, cornerR);
  const borderGrad = ctx.createLinearGradient(0, 0, w, h);
  borderGrad.addColorStop(0, 'rgba(182, 255, 46, 0.15)');
  borderGrad.addColorStop(0.5, 'rgba(255, 255, 255, 0.08)');
  borderGrad.addColorStop(1, 'rgba(182, 255, 46, 0.1)');
  ctx.strokeStyle = borderGrad;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // -- Top-left: branding --
  ctx.font = '600 16px "Inter", "Segoe UI", sans-serif';
  ctx.fillStyle = '#B6FF2E';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText('LAP COACH', pad, pad);

  // -- Session title --
  const driver = data.driverName || 'Driver';
  const typeCap = (data.sessionType || 'practice').charAt(0).toUpperCase() + (data.sessionType || 'practice').slice(1);
  ctx.font = '800 36px "Inter", "Segoe UI", sans-serif';
  ctx.fillStyle = '#F0EDE5';
  ctx.fillText(`${driver}`, pad, pad + 36);

  // -- Track / date --
  const track = data.trackName || 'Unknown Track';
  const rawDate = data.sessionDate || '';
  let displayDate = rawDate;
  try {
    if (rawDate) {
      const d = new Date(rawDate);
      displayDate = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
    }
  } catch { /* keep raw */ }
  ctx.font = '500 18px "Inter", "Segoe UI", sans-serif';
  ctx.fillStyle = '#949494';
  ctx.fillText(`${track}  \u00B7  ${displayDate}  \u00B7  ${typeCap}`, pad, pad + 82);

  // -- Grade badge (top-right) --
  const grade = data.grade ?? null;
  const gc = gradeColor(grade);
  const bx = w - pad - 80;
  const by = pad;
  const bSize = 80;
  ctx.beginPath();
  ctx.roundRect(bx, by, bSize, bSize, 16);
  const gradeFill = ctx.createLinearGradient(bx, by, bx + bSize, by + bSize);
  gradeFill.addColorStop(0, gc + '18');
  gradeFill.addColorStop(1, gc + '08');
  ctx.fillStyle = gradeFill;
  ctx.fill();
  ctx.strokeStyle = gc + '60';
  ctx.lineWidth = 2;
  ctx.stroke();
  if (grade) {
    ctx.font = '900 42px "Inter", "Segoe UI", sans-serif';
    ctx.fillStyle = gc;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(grade.toUpperCase(), bx + bSize / 2, by + bSize / 2 + 2);
  }

  // -- Stats row --
  const statY = 220;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';

  const stats = [
    { label: 'Best Lap', value: formatLapTime(data.bestLapTime), color: '#B6FF2E' },
    { label: 'Score', value: data.totalScore != null ? String(Math.round(data.totalScore)) : '--', color: '#F0EDE5', suffix: '/100', suffixColor: '#555' },
    { label: 'Laps', value: data.nLaps != null ? String(data.nLaps) : '--', color: '#F0EDE5' },
    { label: 'Consistency', value: data.cvPct != null ? `${Math.round(data.cvPct)}%` : '--', color: '#00d4ff' },
  ];

  const statSpacing = (w - pad * 2) / stats.length;
  for (let i = 0; i < stats.length; i++) {
    const sx = pad + i * statSpacing;
    const s = stats[i];
    ctx.font = '500 14px "Inter", "Segoe UI", sans-serif';
    ctx.fillStyle = '#666';
    ctx.fillText(s.label, sx, statY);
    ctx.font = '800 38px "Inter", "Segoe UI", sans-serif';
    ctx.fillStyle = s.color;
    ctx.fillText(s.value, sx, statY + 26);
    if (s.suffix) {
      const valW = ctx.measureText(s.value).width;
      ctx.font = '500 22px "Inter", "Segoe UI", sans-serif';
      ctx.fillStyle = s.suffixColor ?? '#555';
      ctx.fillText(s.suffix, sx + valW + 4, statY + 36);
    }
  }

  // -- Separator --
  ctx.strokeStyle = 'rgba(255,255,255,0.04)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, statY + 100);
  ctx.lineTo(w - pad, statY + 100);
  ctx.stroke();

  // -- Badges row --
  const badges = data.badges || [];
  const badgeY = statY + 130;
  if (badges.length > 0) {
    ctx.font = '600 14px "Inter", "Segoe UI", sans-serif';
    ctx.fillStyle = '#666';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Badges Earned', pad, badgeY);

    const hexSize = 72;
    const hexGap = 100;
    for (let i = 0; i < badges.length; i++) {
      const bCx = pad + 40 + i * hexGap;
      const bCy = badgeY + 60;
      drawHexBadge(ctx, bCx, bCy, hexSize, badges[i].tier || 'bronze');
      // Label below hex
      ctx.font = '600 13px "Inter", "Segoe UI", sans-serif';
      ctx.fillStyle = (TIER_HEX_COLORS[badges[i].tier] || TIER_HEX_COLORS.bronze)[0];
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      ctx.fillText(BADGE_LABELS[badges[i].id] || '', bCx, bCy + hexSize / 2 + 10);
    }
  } else {
    ctx.font = '500 14px "Inter", "Segoe UI", sans-serif';
    ctx.fillStyle = '#444';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText('Keep pushing to earn badges', pad, badgeY + 10);
  }

  // -- Bottom-right: URL --
  ctx.textAlign = 'right';
  ctx.textBaseline = 'bottom';
  ctx.font = '600 15px "Inter", "Segoe UI", sans-serif';
  ctx.fillStyle = '#B6FF2E';
  ctx.fillText('lap-coach.racing', w - pad, h - pad + 4);

  // -- Bottom-left: thin tagline --
  ctx.textAlign = 'left';
  ctx.font = '400 12px "Inter", "Segoe UI", sans-serif';
  ctx.fillStyle = '#444';
  ctx.fillText('Motorsport Telemetry Analysis', pad, h - pad + 4);

  ctx.restore();
}

export function ShareCardCanvas({ sessionData, className }: ShareCardCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    drawCard(ctx, sessionData);
  }, [sessionData]);

  const handleDownload = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      const driver = sessionData.driverName?.replace(/\s+/g, '-') || 'session';
      a.download = `lap-coach-${driver}.png`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 'image/png');
  }, [sessionData.driverName]);

  return (
    <div className={className}>
      {/* Full-res canvas scaled down via CSS for preview, full 1200x630 for download */}
      <canvas
        ref={canvasRef}
        width={CANVAS_W}
        height={CANVAS_H}
        className="w-full max-w-lg rounded-lg border border-white/10"
      />

      <button
        type="button"
        onClick={handleDownload}
        className="mt-3 inline-flex items-center gap-2 rounded-md bg-[#B6FF2E] px-4 py-2 text-sm font-semibold text-black transition-colors hover:bg-[#a3e629]"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
          <polyline points="7 10 12 15 17 10" />
          <line x1="12" y1="15" x2="12" y2="3" />
        </svg>
        Download Card
      </button>
    </div>
  );
}
