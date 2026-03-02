'use client';

import { useRef, useEffect, useCallback } from 'react';

/** Design-token hex colors */
const COLORS = {
  asphalt: '#000000',
  concrete: '#141414',
  chalk: '#F0EDE5',
  steel: '#888888',
  acidGreen: '#F0EDE5',
  safetyRed: '#FF2A2A',
  marshalYellow: '#F0EDE5',
  pitOrange: '#C9A84C',
};

export interface CockpitFrame {
  speed: number; // km/h
  throttle?: number; // 0..1, optional
  brake?: number; // 0..1, optional
  steeringAngle?: number; // degrees, negative = left, positive = right, optional
  gLat: number; // lateral G
  gLon: number; // longitudinal G
}

interface CornerReplayCockpitProps {
  frame: CockpitFrame;
  hasPedalData: boolean;
  hasSteeringData: boolean;
}

function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

function drawCockpit(
  ctx: CanvasRenderingContext2D,
  w: number,
  h: number,
  frame: CockpitFrame,
  showPedals: boolean,
  showSteering: boolean,
) {
  ctx.clearRect(0, 0, w, h);

  // Background
  ctx.fillStyle = COLORS.concrete;
  ctx.fillRect(0, 0, w, h);

  const speed = clamp(frame.speed, 0, 200);
  const gLat = clamp(frame.gLat, -3, 3);
  const gLon = clamp(frame.gLon, -3, 3);

  // --- Layout adapts based on available data ---
  // When both pedals and steering are hidden, speedo and g-ball center and grow.
  // When only one is hidden, the remaining elements shift to use the extra space.
  const hasBottom = showPedals || showSteering;
  const midY = hasBottom ? h * 0.45 : h * 0.5;

  // Speedo and G-ball horizontal positions shift when bottom row is sparse
  const speedCX = showPedals && showSteering ? w * 0.3
    : !showPedals && !showSteering ? w * 0.3
    : w * 0.3;
  const gCX = showPedals && showSteering ? w * 0.72
    : !showPedals && !showSteering ? w * 0.72
    : w * 0.72;

  // Scale up speedo and g-ball when bottom row is hidden
  const sizeBoost = hasBottom ? 1.0 : 1.15;

  // === SPEEDOMETER (circular gauge) ===
  const speedCY = midY;
  const speedR = Math.max(20, Math.min(w * 0.22, h * 0.32) * sizeBoost);

  // Outer ring
  ctx.beginPath();
  ctx.arc(speedCX, speedCY, speedR, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
  ctx.lineWidth = 2;
  ctx.stroke();

  // Speed arc background (210 degrees, from 150 to 390 i.e. -210 to +30)
  const arcStart = (150 * Math.PI) / 180;
  const arcEnd = (390 * Math.PI) / 180;
  const arcRange = arcEnd - arcStart;

  // Tick marks
  const tickR = Math.max(0, speedR - 4);
  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(8, speedR * 0.14)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let spd = 0; spd <= 200; spd += 20) {
    const frac = spd / 200;
    const angle = arcStart + frac * arcRange;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const isMajor = spd % 40 === 0;
    const innerR = Math.max(0, isMajor ? tickR - 8 : tickR - 4);

    ctx.beginPath();
    ctx.moveTo(speedCX + innerR * cos, speedCY + innerR * sin);
    ctx.lineTo(speedCX + tickR * cos, speedCY + tickR * sin);
    ctx.strokeStyle = isMajor ? COLORS.steel : 'rgba(138, 143, 152, 0.3)';
    ctx.lineWidth = isMajor ? 1.5 : 0.5;
    ctx.stroke();

    if (isMajor) {
      const labelR = Math.max(0, innerR - 10);
      ctx.fillStyle = COLORS.steel;
      ctx.fillText(`${spd}`, speedCX + labelR * cos, speedCY + labelR * sin);
    }
  }

  // Speed arc (filled portion)
  const speedFrac = speed / 200;
  const speedAngle = arcStart + speedFrac * arcRange;

  ctx.beginPath();
  ctx.arc(speedCX, speedCY, Math.max(0, speedR - 10), arcStart, speedAngle);
  ctx.strokeStyle = COLORS.chalk;
  ctx.lineWidth = 4;
  ctx.lineCap = 'round';
  ctx.stroke();
  ctx.lineCap = 'butt';

  // Needle
  const needleLen = Math.max(0, speedR - 16);
  const needleAngle = arcStart + speedFrac * arcRange;
  ctx.beginPath();
  ctx.moveTo(speedCX, speedCY);
  ctx.lineTo(
    speedCX + needleLen * Math.cos(needleAngle),
    speedCY + needleLen * Math.sin(needleAngle),
  );
  ctx.strokeStyle = COLORS.chalk;
  ctx.lineWidth = 2;
  ctx.stroke();

  // Center dot
  ctx.beginPath();
  ctx.arc(speedCX, speedCY, 4, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.chalk;
  ctx.fill();

  // Speed readout
  ctx.fillStyle = COLORS.chalk;
  ctx.font = `bold ${Math.max(14, speedR * 0.3)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(`${Math.round(speed)}`, speedCX, speedCY + speedR * 0.5);

  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(8, speedR * 0.12)}px "Space Mono", monospace`;
  ctx.fillText('km/h', speedCX, speedCY + speedR * 0.65);

  // === G-FORCE DIAMOND ===
  const gCY = midY;
  const gR = Math.max(1, Math.min(w * 0.18, h * 0.28) * sizeBoost);
  const maxG = 2.0;

  // Diamond outline
  ctx.beginPath();
  ctx.moveTo(gCX, gCY - gR);
  ctx.lineTo(gCX + gR, gCY);
  ctx.lineTo(gCX, gCY + gR);
  ctx.lineTo(gCX - gR, gCY);
  ctx.closePath();
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Inner diamond (half size)
  ctx.beginPath();
  const halfR = gR * 0.5;
  ctx.moveTo(gCX, gCY - halfR);
  ctx.lineTo(gCX + halfR, gCY);
  ctx.lineTo(gCX, gCY + halfR);
  ctx.lineTo(gCX - halfR, gCY);
  ctx.closePath();
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.1)';
  ctx.stroke();

  // Crosshairs
  ctx.beginPath();
  ctx.moveTo(gCX - gR, gCY);
  ctx.lineTo(gCX + gR, gCY);
  ctx.moveTo(gCX, gCY - gR);
  ctx.lineTo(gCX, gCY + gR);
  ctx.strokeStyle = 'rgba(138, 143, 152, 0.15)';
  ctx.lineWidth = 0.5;
  ctx.stroke();

  // G-force dot
  const gDotX = gCX + (gLat / maxG) * gR;
  const gDotY = gCY - (gLon / maxG) * gR;

  // Trail glow
  const gGlow = ctx.createRadialGradient(gDotX, gDotY, 0, gDotX, gDotY, 10);
  gGlow.addColorStop(0, COLORS.pitOrange + '55');
  gGlow.addColorStop(1, COLORS.pitOrange + '00');
  ctx.fillStyle = gGlow;
  ctx.beginPath();
  ctx.arc(gDotX, gDotY, 10, 0, Math.PI * 2);
  ctx.fill();

  // Dot
  ctx.beginPath();
  ctx.arc(gDotX, gDotY, 5, 0, Math.PI * 2);
  ctx.fillStyle = COLORS.pitOrange;
  ctx.fill();

  // G labels
  ctx.fillStyle = COLORS.steel;
  ctx.font = `${Math.max(8, gR * 0.14)}px "Space Mono", monospace`;
  ctx.textAlign = 'center';
  ctx.fillText('G-Force', gCX, gCY - gR - 6);
  ctx.fillText(`${(gLat ?? 0).toFixed(2)}G lat`, gCX, gCY + gR + 14);
  ctx.fillText(`${(gLon ?? 0).toFixed(2)}G lon`, gCX, gCY + gR + 26);

  // === BRAKE / THROTTLE BARS (horizontal) ===
  if (showPedals) {
    const throttle = clamp(frame.throttle ?? 0, 0, 1);
    const brake = clamp(frame.brake ?? 0, 0, 1);

    const barY = h * 0.78;
    const barH = Math.max(12, h * 0.06);
    const barX = w * 0.06;
    const barW = showSteering ? w * 0.38 : w * 0.88;

    // Throttle bar
    const thrLabel = 'THR';
    ctx.fillStyle = COLORS.steel;
    ctx.font = `${Math.max(8, barH * 0.7)}px "Space Mono", monospace`;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(thrLabel, barX, barY - barH - 6);

    // Throttle background
    ctx.fillStyle = 'rgba(138, 143, 152, 0.1)';
    ctx.beginPath();
    ctx.roundRect(barX, barY - barH * 2 - 2, barW, barH, 3);
    ctx.fill();

    // Throttle fill
    ctx.fillStyle = COLORS.acidGreen;
    if (throttle > 0.01) {
      ctx.beginPath();
      ctx.roundRect(barX, barY - barH * 2 - 2, barW * throttle, barH, 3);
      ctx.fill();
    }

    // Brake bar
    const brkLabel = 'BRK';
    ctx.fillStyle = COLORS.steel;
    ctx.fillText(brkLabel, barX, barY + 6);

    // Brake background
    ctx.fillStyle = 'rgba(138, 143, 152, 0.1)';
    ctx.beginPath();
    ctx.roundRect(barX, barY, barW, barH, 3);
    ctx.fill();

    // Brake fill
    ctx.fillStyle = COLORS.safetyRed;
    if (brake > 0.01) {
      ctx.beginPath();
      ctx.roundRect(barX, barY, barW * brake, barH, 3);
      ctx.fill();
    }
  }

  // === STEERING ARC ===
  if (showSteering) {
    const steer = clamp(frame.steeringAngle ?? 0, -180, 180);

    const steerCX = showPedals ? w * 0.72 : w * 0.5;
    const steerCY = h * 0.82;
    const steerR = Math.max(1, Math.min(w * 0.14, h * 0.12));

    // Arc background
    const steerArcStart = Math.PI;
    const steerArcEnd = Math.PI * 2;
    ctx.beginPath();
    ctx.arc(steerCX, steerCY, steerR, steerArcStart, steerArcEnd);
    ctx.strokeStyle = 'rgba(138, 143, 152, 0.2)';
    ctx.lineWidth = 4;
    ctx.stroke();

    // Steering indicator (maps -180..+180 to the arc)
    const steerFrac = (steer + 180) / 360;
    const steerAngle = steerArcStart + steerFrac * (steerArcEnd - steerArcStart);

    // Filled arc from center to current position
    const steerCenter = steerArcStart + 0.5 * (steerArcEnd - steerArcStart);
    const steerFrom = Math.min(steerCenter, steerAngle);
    const steerTo = Math.max(steerCenter, steerAngle);
    ctx.beginPath();
    ctx.arc(steerCX, steerCY, steerR, steerFrom, steerTo);
    ctx.strokeStyle = COLORS.marshalYellow;
    ctx.lineWidth = 4;
    ctx.stroke();

    // Steering needle indicator
    const needleX = steerCX + steerR * Math.cos(steerAngle);
    const needleY = steerCY + steerR * Math.sin(steerAngle);
    ctx.beginPath();
    ctx.arc(needleX, needleY, 4, 0, Math.PI * 2);
    ctx.fillStyle = COLORS.marshalYellow;
    ctx.fill();

    // Steering label
    ctx.fillStyle = COLORS.steel;
    ctx.font = `${Math.max(8, steerR * 0.3)}px "Space Mono", monospace`;
    ctx.textAlign = 'center';
    ctx.fillText('STEER', steerCX, steerCY + 14);
    ctx.fillStyle = COLORS.marshalYellow;
    ctx.fillText(`${steer >= 0 ? '+' : ''}${Math.round(steer)}°`, steerCX, steerCY + 26);
  }
}

export function CornerReplayCockpit({ frame, hasPedalData, hasSteeringData }: CornerReplayCockpitProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
    drawCockpit(ctx, rect.width, rect.height, frame, hasPedalData, hasSteeringData);
  }, [frame, hasPedalData, hasSteeringData]);

  useEffect(() => {
    render();
  }, [render]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const observer = new ResizeObserver(() => render());
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [render]);

  return (
    <div className="relative w-full h-full min-h-[200px] bg-concrete rounded-lg border border-steel/20 overflow-hidden">
      <div className="absolute top-3 left-3 z-10">
        <span className="text-steel font-telemetry text-[10px] uppercase tracking-wider">
          Cockpit
        </span>
      </div>
      <canvas ref={canvasRef} className="w-full h-full" />
    </div>
  );
}
