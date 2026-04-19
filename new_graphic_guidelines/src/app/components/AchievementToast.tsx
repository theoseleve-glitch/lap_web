import { motion, AnimatePresence } from "motion/react";
import { X } from "lucide-react";

interface AchievementToastProps {
  open: boolean;
  onClose: () => void;
  badgeName: string;
  description: string;
}

export function AchievementToast({
  open,
  onClose,
  badgeName,
  description,
}: AchievementToastProps) {
  const accent = "#C9A84C";

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0, x: 60, y: -10 }}
          animate={{ opacity: 1, x: 0, y: 0 }}
          exit={{ opacity: 0, x: 60 }}
          transition={{ type: "spring", stiffness: 320, damping: 28 }}
          className="fixed top-6 right-6 z-[60] w-[380px] max-w-[92vw] rounded-[20px] overflow-hidden"
          style={{
            background: "#141414",
            border: "1px solid rgba(240,237,229,0.06)",
            boxShadow: `0 20px 60px rgba(0,0,0,0.6), 0 0 40px ${accent}10`,
          }}
        >
          {/* Top accent line */}
          <div
            className="h-[2px]"
            style={{ background: `linear-gradient(90deg, ${accent}, ${accent}60, transparent)` }}
          />

          <div className="flex gap-4 items-start p-5">
            {/* Hexagonal mini badge */}
            <div className="shrink-0 relative w-10 h-11">
              <svg viewBox="0 0 40 44" className="w-full h-full">
                <path
                  d="M20 2 L37 11 L37 33 L20 42 L3 33 L3 11 Z"
                  fill={`${accent}0A`}
                  stroke={accent}
                  strokeWidth="1"
                  strokeDasharray="6 4"
                  opacity="0.6"
                />
                {/* Small trophy */}
                <g transform="translate(12, 13)" opacity="0.9">
                  <path
                    d="M4 3.5v2.5a2 2 0 004 0V3.5H4z"
                    fill={accent}
                    opacity="0.2"
                  />
                  <path
                    d="M3 1l1 2.5h4l1-2.5"
                    stroke={accent}
                    strokeWidth="0.8"
                    fill="none"
                    strokeLinejoin="round"
                  />
                  <path
                    d="M4 3.5v2.5a2 2 0 004 0V3.5"
                    stroke={accent}
                    strokeWidth="0.8"
                    fill="none"
                  />
                  <path d="M5 8.5v1h2v-1" stroke={accent} strokeWidth="0.8" fill="none" />
                  <path d="M4 10.5h4" stroke={accent} strokeWidth="0.8" strokeLinecap="round" fill="none" />
                </g>
              </svg>
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <p
                className="text-[9px] uppercase tracking-[0.15em] mb-1"
                style={{ color: accent, fontFamily: "'Space Mono', monospace" }}
              >
                Achievement Unlocked
              </p>
              <p className="text-[15px] font-bold text-[#F0EDE5] uppercase tracking-tight mb-1.5">
                {badgeName}
              </p>
              <p className="text-[12px] text-[#949494] leading-relaxed">
                {description}
              </p>
            </div>

            {/* Close button */}
            <button
              onClick={onClose}
              className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center text-[#949494] hover:text-[#F0EDE5] transition-colors cursor-pointer"
              style={{
                backgroundColor: "rgba(240,237,229,0.04)",
                border: "1px solid rgba(240,237,229,0.06)",
              }}
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Bottom micro detail */}
          <div className="px-5 pb-3 flex items-center gap-2">
            <div className="h-[1px] flex-1" style={{ background: `linear-gradient(90deg, ${accent}20, transparent)` }} />
            <span
              className="text-[7px] uppercase tracking-[0.2em] text-[#949494] opacity-40"
              style={{ fontFamily: "'Space Mono', monospace" }}
            >
              +50 XP
            </span>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
