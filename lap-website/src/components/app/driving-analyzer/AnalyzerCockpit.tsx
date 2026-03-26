'use client';

import { useRef, useEffect, useCallback } from 'react';

interface AnalyzerCockpitProps {
  speed: number;         // km/h
  gLat: number;          // lateral G
  gLon: number;          // longitudinal G
  brake: number;         // 0..1
  throttle: number;      // 0..1
  steering: number;      // degrees
  hasPedalData: boolean;
  hasSteeringData: boolean;
}

const COLORS = {
  concrete: '#141414',
  chalk: '#F0EDE5',
  steel: '#949494',
  acidGreen: '#22C55E',
  safetyRed: '#FF2A2A',
  marshalYellow: '#FACC15',
  pitOrange: '#C9A84C',
};

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function drawCockpit(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  speed: number,
  gLat: number,
  gLon: number,
  brake: number,
  throttle: number,
  steeringDeg: number,
  showPedals: boolean,
  showSteering: boolean,
) {
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = COLORS.concrete;
  ctx.fillRect(0, 0, w, h);

  const spd = clamp(speed, 0, 200);
  const gL = clamp(gLat, -3, 3);
  const gN = clamp(gLon, -3, 3);

  const hasBottom = showPedals || showSteering;
  const midY = hasBottom ? h * 0.42 : h * 0.5;
  const sizeBoost = hasBottom ? 1.0 : 1.15;

  // === SPEEDOMETER ===
  const speedCX = w * 0.3;
  const speedCY = midY;
  const speedR = Math.max(18, Math.min(w * 0.20, h * 0.30) * sizeBoost);

  // Outer ring
  ctx.beginPath();
  ctx.arc(speedCX, speedCY, speedR, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(138,143,152,0.2)';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Arc range 210 degrees
  const arcStart = (150 * Math.PI) / 180;
  const arcEnd = (390 * Math.PI) / 180;
  const arcRange = arcEnd - arcStart;

  // Tick marks
  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(7, speedR * 0.12)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let s = 0; s <= 200; s += 40) {
    const frac = s / 200;
    const angle = arcStart + frac * arcRange;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const innerR = Math.max(0, speedR - 8);
    ctx.beginPath();
    ctx.moveTo(speedCX + innerR * cos, speedCY + innerR * sin);
    ctx.lineTo(speedCX + (speedR - 4) * cos, speedCY + (speedR - 4) * sin);
    ctx.strokeStyle = COLORS.steel;
    ctx.lineWidth = 1;
    ctx.stroke();
    const labelR = Math.max(0, innerR - 9);
    ctx.fillText(`${s}`, speedCX + labelR * cos, speedCY + labelR * sin);
  }

  // Speed arc fill
  const speedFrac = spd / 200;
  ctx.beginPath();
  ctx.arc(speedCX, speedCY, Math.max(0, speedR - 10), arcStart, arcStart + speedFrac * arcRange);
  ctx.strokeStyle = COLORS.chalk;
  ctx.lineWidth = 3;
  ctx.lineCap = 'round';
  ctx.stroke();
  ctx.lineCap = 'butt';

  // Center dot
  ctx.beginPath();
  ctx.arc(speedCX, speedCY, 3, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.chalk;
  ctx.fill();

  // Speed readout
  ctx.fillStyle = COLORS.chalk;
  ctx.font = `bold ${Math.max(12, speedR * 0.28)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.fillText(`${Math.round(spd)}`, speedCX, speedCY + speedR * 0.45);
  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(7, speedR * 0.11)}px "Space Mono", monospace`;
  ctx.fillText('km/h', speedCX, speedCY + speedR * 0.60);

  // === G-FORCE DIAMOND ===
  const gCX = w * 0.72;
  const gCY = midY;
  const gR = Math.max(1, Math.min(w * 0.16, h * 0.25) * sizeBoost);
  const maxG = 2.0;

  // Diamond outline
  ctx.beginPath();
  ctx.moveTo(gCX, gCY - gR); ctx.lineTo(gCX + gR, gCY);
  ctx.lineTo(gCX, gCY + gR); ctx.lineTo(gCX - gR, gCY);
  ctx.closePath();
  ctx.strokeStyle = 'rgba(138,143,152,0.2)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Inner diamond
  const halfR = gR * 0.5;
  ctx.beginPath();
  ctx.moveTo(gCX, gCY - halfR); ctx.lineTo(gCX + halfR, gCY);
  ctx.lineTo(gCX, gCY + halfR); ctx.lineTo(gCX - halfR, gCY);
  ctx.closePath();
  ctx.strokeStyle = 'rgba(138,143,152,0.1)';
  ctx.stroke();

  // Crosshairs
  ctx.beginPath();
  ctx.moveTo(gCX - gR, gCY); ctx.lineTo(gCX + gR, gCY);
  ctx.moveTo(gCX, gCY - gR); ctx.lineTo(gCX, gCY + gR);
  ctx.strokeStyle = 'rgba(138,143,152,0.15)';
  ctx.lineWidth = 0.5;
  ctx.stroke();

  // G-dot
  const gDotX = gCX + (gL / maxG) * gR;
  const gDotY = gCY - (gN / maxG) * gR;
  const gGlow = ctx.createRadialGradient(gDotX, gDotY, 0, gDotX, gDotY, 8);
  gGlow.addColorStop(0, COLORS.pitOrange + '55');
  gGlow.addColorStop(1, COLORS.pitOrange + '00');
  ctx.fillStyle = gGlow;
  ctx.beginPath();
  ctx.arc(gDotX, gDotY, 8, 0, Math.PI * 2);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(gDotX, gDotY, 4, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.pitOrange;
  ctx.fill();

  // G labels
  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(7, gR * 0.13)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.fillText('G-Force', gCX, gCY - gR - 5);
  ctx.fillText(`${(gL ?? 0).toFixed(2)}G lat`, gCX, gCY + gR + 11);

  // === PEDAL BARS ===
  if (showPedals) {
    const thr = clamp(throttle, 0, 1);
    const brk = clamp(brake, 0, 1);
    const barY = h * 0.78;
    const barH = Math.max(10, h * 0.055);
    const barX = w * 0.06;
    const barW = showSteering ? w * 0.38 : w * 0.88;

    ctx.fillStyle = COLORS.steel;
    ctx.font = `${Math.max(7, barH * 0.65)}px "Space Mono", monospace`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText('THR', barX, barY - barH - 5);

    ctx.fillStyle = 'rgba(138,143,152,0.1)';
    ctx.beginPath(); ctx.roundRect(barX, barY - barH * 2 - 2, barW, barH, 3); ctx.fill();
    if (thr > 0.01) {
      ctx.fillStyle = COLORS.acidGreen;
      ctx.beginPath(); ctx.roundRect(barX, barY - barH * 2 - 2, barW * thr, barH, 3); ctx.fill();
    }

    ctx.fillStyle = COLORS.steel;
    ctx.fillText('BRK', barX, barY + 5);
    ctx.fillStyle = 'rgba(138,143,152,0.1)';
    ctx.beginPath(); ctx.roundRect(barX, barY, barW, barH, 3); ctx.fill();
    if (brk > 0.01) {
      ctx.fillStyle = COLORS.safetyRed;
      ctx.beginPath(); ctx.roundRect(barX, barY, barW * brk, barH, 3); ctx.fill();
    }
  }

  // === STEERING ARC ===
  if (showSteering) {
    const steer = clamp(steeringDeg, -180, 180);
    const steerCX = showPedals ? w * 0.72 : w * 0.5;
    const steerCY = h * 0.82;
    const steerR = Math.max(1, Math.min(w * 0.12, h * 0.10));

    ctx.beginPath();
    ctx.arc(steerCX, steerCY, steerR, Math.PI, Math.PI * 2);
    ctx.strokeStyle = 'rgba(138,143,152,0.2)';
    ctx.lineWidth = 3;
    ctx.stroke();

    const steerFrac = (steer + 180) / 360;
    const steerAngle = Math.PI + steerFrac * Math.PI;
    const steerCenter = Math.PI * 1.5;
    const from = Math.min(steerCenter, steerAngle);
    const to = Math.max(steerCenter, steerAngle);
    ctx.beginPath();
    ctx.arc(steerCX, steerCY, steerR, from, to);
    ctx.strokeStyle = COLORS.marshalYellow;
    ctx.lineWidth = 3;
    ctx.stroke();

    const nx = steerCX + steerR * Math.cos(steerAngle);
    const ny = steerCY + steerR * Math.sin(steerAngle);
    ctx.beginPath();
    ctx.arc(nx, ny, 3, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.marshalYellow;
    ctx.fill();

    ctx.fillStyle = COLORS.steel;
    ctx.font = `${Math.max(7, steerR * 0.25)}px "Space Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.fillText(`${steer >= 0 ? '+' : ''}${Math.round(steer)}°`, steerCX, steerCY + 12);
  }
}

export function AnalyzerCockpit({
  speed, gLat, gLon, brake, throttle, steering, hasPedalData, hasSteeringData,
}: AnalyzerCockpitProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawCockpit(ctx, rect.width, rect.height, speed, gLat, gLon, brake, throttle, steering, hasPedalData, hasSteeringData);
  }, [speed, gLat, gLon, brake, throttle, steering, hasPedalData, hasSteeringData]);

  // Stable ref for ResizeObserver — avoids re-attaching 60x/sec during playback
  const renderRef = useRef(render);
  renderRef.current = render;

  useEffect(() => { render(); }, [render]);

  // Resize observer — attached once, always calls latest render via ref
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ro = new ResizeObserver(() => renderRef.current());
    ro.observe(canvas);
    return () => ro.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="relative w-full h-full bg-concrete overflow-hidden">
      <div className="absolute top-2 left-3 z-10">
        <span className="text-steel/50 font-telemetry text-[9px] uppercase tracking-wider">Cockpit</span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  );
}
