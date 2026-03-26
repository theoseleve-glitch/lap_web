import { motion, AnimatePresence } from "motion/react";

interface LevelUpModalProps {
  open: boolean;
  onClose: () => void;
  previousLevel: number;
  newLevel: number;
  totalXP: number;
}

export function LevelUpModal({
  open,
  onClose,
  previousLevel,
  newLevel,
  totalXP,
}: LevelUpModalProps) {
  const accent = "#22C55E";

  // Arc path for the circular gauge (270° arc)
  const radius = 62;
  const cx = 70;
  const cy = 70;
  const startAngle = 135;
  const endAngle = 405;
  const arcLength = endAngle - startAngle;

  function polarToCartesian(cxP: number, cyP: number, r: number, angleDeg: number) {
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cxP + r * Math.cos(rad), y: cyP + r * Math.sin(rad) };
  }

  function describeArc(startA: number, endA: number, r: number) {
    const start = polarToCartesian(cx, cy, r, endA);
    const end = polarToCartesian(cx, cy, r, startA);
    const largeArc = endA - startA <= 180 ? 0 : 1;
    return `M ${start.x} ${start.y} A ${r} ${r} 0 ${largeArc} 0 ${end.x} ${end.y}`;
  }

  const bgArc = describeArc(startAngle, endAngle, radius);
  const fillEndAngle = startAngle + arcLength;
  const fillArc = describeArc(startAngle, fillEndAngle, radius);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          className="fixed inset-0 z-50 flex items-center justify-center"
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-[rgba(0,0,0,0.92)]" onClick={onClose} />

          {/* Radial glow */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `radial-gradient(ellipse 500px 400px at 50% 42%, ${accent}0D 0%, transparent 70%)`,
            }}
          />

          {/* Card */}
          <motion.div
            initial={{ scale: 0.92, opacity: 0, y: 20 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.95, opacity: 0, y: 10 }}
            transition={{ type: "spring", stiffness: 260, damping: 24, delay: 0.1 }}
            className="relative w-[480px] max-w-[92vw] rounded-[28px] overflow-hidden"
            style={{
              background: "#141414",
              border: "1px solid rgba(240,237,229,0.06)",
            }}
          >
            {/* Top accent */}
            <div className="h-[2px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} />

            {/* Corner dots */}
            <div className="absolute top-4 left-5 flex gap-[3px] opacity-20">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
              ))}
            </div>
            <div className="absolute top-4 right-5 flex gap-[3px] opacity-20">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="w-[3px] h-[3px] rounded-[0.5px]" style={{ backgroundColor: accent }} />
              ))}
            </div>

            <div className="flex flex-col items-center px-10 pt-12 pb-10">
              {/* Micro label */}
              <motion.p
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className="text-[10px] uppercase tracking-[0.18em] mb-8"
                style={{ color: accent, fontFamily: "'Space Mono', monospace" }}
              >
                Driver Level Up
              </motion.p>

              {/* Circular gauge with level transition */}
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 200, damping: 18, delay: 0.25 }}
                className="relative w-[140px] h-[140px] mb-8"
              >
                <svg viewBox="0 0 140 140" className="w-full h-full">
                  {/* Background arc */}
                  <path
                    d={bgArc}
                    fill="none"
                    stroke="rgba(240,237,229,0.06)"
                    strokeWidth="4"
                    strokeLinecap="round"
                  />

                  {/* Dashed progress arc */}
                  <motion.path
                    d={fillArc}
                    fill="none"
                    stroke={accent}
                    strokeWidth="4"
                    strokeLinecap="round"
                    strokeDasharray="6 4"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 0.7 }}
                    transition={{ delay: 0.5, duration: 0.6 }}
                  />

                  {/* Solid progress arc (animated) */}
                  <motion.path
                    d={fillArc}
                    fill="none"
                    stroke={accent}
                    strokeWidth="4"
                    strokeLinecap="round"
                    initial={{ pathLength: 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{ delay: 0.4, duration: 1.2, ease: "easeOut" }}
                    style={{ filter: `drop-shadow(0 0 6px ${accent}40)` }}
                  />

                  {/* Tick marks around the arc */}
                  {[...Array(12)].map((_, i) => {
                    const angle = startAngle + (arcLength / 11) * i;
                    const inner = polarToCartesian(cx, cy, radius - 8, angle);
                    const outer = polarToCartesian(cx, cy, radius - 4, angle);
                    return (
                      <line
                        key={i}
                        x1={inner.x}
                        y1={inner.y}
                        x2={outer.x}
                        y2={outer.y}
                        stroke="rgba(240,237,229,0.1)"
                        strokeWidth="1"
                      />
                    );
                  })}
                </svg>

                {/* Level numbers in the center */}
                <div className="absolute inset-0 flex flex-col items-center justify-center">
                  <div className="flex items-center gap-3">
                    <motion.span
                      initial={{ opacity: 1 }}
                      animate={{ opacity: 0.3 }}
                      transition={{ delay: 0.6, duration: 0.4 }}
                      className="text-2xl font-bold text-[#949494]"
                    >
                      {previousLevel}
                    </motion.span>

                    {/* Animated arrow */}
                    <motion.svg
                      width="20"
                      height="12"
                      viewBox="0 0 20 12"
                      initial={{ opacity: 0, x: -4 }}
                      animate={{ opacity: 0.5, x: 0 }}
                      transition={{ delay: 0.5 }}
                    >
                      <path
                        d="M0 6H16M12 1L18 6L12 11"
                        stroke="#949494"
                        strokeWidth="1.5"
                        fill="none"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </motion.svg>

                    <motion.span
                      initial={{ opacity: 0, scale: 0.5 }}
                      animate={{ opacity: 1, scale: 1 }}
                      transition={{ type: "spring", stiffness: 300, damping: 20, delay: 0.7 }}
                      className="text-3xl font-bold"
                      style={{ color: accent, filter: `drop-shadow(0 0 8px ${accent}40)` }}
                    >
                      {newLevel}
                    </motion.span>
                  </div>
                </div>
              </motion.div>

              {/* Stats row */}
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6 }}
                className="flex items-center gap-6 mb-8 px-6 py-3 rounded-[14px]"
                style={{
                  background: "rgba(240,237,229,0.02)",
                  border: "1px solid rgba(240,237,229,0.04)",
                }}
              >
                <div className="text-center">
                  <p
                    className="text-[8px] uppercase tracking-[0.15em] text-[#949494] mb-1"
                    style={{ fontFamily: "'Space Mono', monospace" }}
                  >
                    Total XP
                  </p>
                  <p
                    className="text-lg font-bold text-[#F0EDE5]"
                    style={{ fontFamily: "'Space Mono', monospace" }}
                  >
                    {totalXP.toLocaleString()}
                  </p>
                </div>

                <div className="w-[1px] h-8" style={{ backgroundColor: "rgba(240,237,229,0.06)" }} />

                <div className="text-center">
                  <p
                    className="text-[8px] uppercase tracking-[0.15em] text-[#949494] mb-1"
                    style={{ fontFamily: "'Space Mono', monospace" }}
                  >
                    New Level
                  </p>
                  <p
                    className="text-lg font-bold"
                    style={{ color: accent, fontFamily: "'Space Mono', monospace" }}
                  >
                    LV.{String(newLevel).padStart(2, "0")}
                  </p>
                </div>

                <div className="w-[1px] h-8" style={{ backgroundColor: "rgba(240,237,229,0.06)" }} />

                <div className="text-center">
                  <p
                    className="text-[8px] uppercase tracking-[0.15em] text-[#949494] mb-1"
                    style={{ fontFamily: "'Space Mono', monospace" }}
                  >
                    Session
                  </p>
                  <p
                    className="text-lg font-bold text-[#C9A84C]"
                    style={{ fontFamily: "'Space Mono', monospace" }}
                  >
                    +340
                  </p>
                </div>
              </motion.div>

              {/* Continue */}
              <motion.button
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.7 }}
                onClick={onClose}
                className="px-10 py-3 rounded-[14px] text-[10px] uppercase tracking-[0.15em] cursor-pointer transition-all hover:brightness-110"
                style={{
                  color: "#000000",
                  backgroundColor: accent,
                  fontFamily: "'Space Mono', monospace",
                }}
              >
                Continue
              </motion.button>
            </div>

            {/* Bottom accent */}
            <div className="h-[1px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}30, transparent)` }} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
