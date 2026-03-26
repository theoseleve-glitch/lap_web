import { motion, AnimatePresence } from "motion/react";

interface AchievementUnlockOverlayProps {
  open: boolean;
  onClose: () => void;
  badgeName: string;
  description: string;
  tier: "bronze" | "silver" | "gold";
}

const tierColors = {
  bronze: "#C9A84C",
  silver: "#949494",
  gold: "#FACC15",
};

const tierLabels = {
  bronze: "Pit Orange Tier",
  silver: "Steel Tier",
  gold: "Marshal Yellow Tier",
};

export function AchievementUnlockOverlay({
  open,
  onClose,
  badgeName,
  description,
  tier,
}: AchievementUnlockOverlayProps) {
  const accent = tierColors[tier];

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

          {/* Scanline grid overlay */}
          <div
            className="absolute inset-0 pointer-events-none opacity-[0.03]"
            style={{
              backgroundImage: `repeating-linear-gradient(0deg, transparent, transparent 3px, ${accent} 3px, ${accent} 4px)`,
            }}
          />

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
            {/* Top accent bar */}
            <div className="h-[2px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }} />

            {/* Corner grid marks */}
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
              {/* Hexagonal badge frame */}
              <motion.div
                initial={{ scale: 0.7, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 200, damping: 18, delay: 0.25 }}
                className="relative w-[140px] h-[156px] mb-8"
              >
                {/* Outer hex glow */}
                <svg
                  viewBox="0 0 140 156"
                  className="absolute inset-0 w-full h-full"
                  style={{ filter: "blur(12px)" }}
                >
                  <path
                    d="M70 6 L130 38 L130 118 L70 150 L10 118 L10 38 Z"
                    fill="none"
                    stroke={accent}
                    strokeWidth="2"
                    opacity="0.4"
                  />
                </svg>

                {/* Dashed hex border */}
                <svg viewBox="0 0 140 156" className="absolute inset-0 w-full h-full">
                  <path
                    d="M70 6 L130 38 L130 118 L70 150 L10 118 L10 38 Z"
                    fill={`${accent}06`}
                    stroke={accent}
                    strokeWidth="1.5"
                    strokeDasharray="10 6"
                    strokeLinejoin="round"
                    opacity="0.6"
                  />
                </svg>

                {/* Inner solid hex */}
                <svg viewBox="0 0 140 156" className="absolute inset-0 w-full h-full">
                  <path
                    d="M70 26 L112 48 L112 108 L70 130 L28 108 L28 48 Z"
                    fill={`${accent}0A`}
                    stroke={accent}
                    strokeWidth="1"
                    opacity="0.3"
                  />
                </svg>

                {/* Trophy icon */}
                <div className="absolute inset-0 flex items-center justify-center">
                  <svg width="44" height="44" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M8 7v5a4 4 0 008 0V7H8z"
                      fill={accent}
                      opacity="0.15"
                    />
                    <path
                      d="M6 2l2 5h8l2-5"
                      stroke={accent}
                      strokeWidth="1.2"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M8 7v5a4 4 0 008 0V7"
                      stroke={accent}
                      strokeWidth="1.2"
                    />
                    <path d="M4 7h4M16 7h4" stroke={accent} strokeWidth="1.2" strokeLinecap="round" />
                    <path d="M4 7c-1 0-2 1-2 3s1 3 2 3" stroke={accent} strokeWidth="1" />
                    <path d="M20 7c1 0 2 1 2 3s-1 3-2 3" stroke={accent} strokeWidth="1" />
                    <path d="M10 17v2h4v-2" stroke={accent} strokeWidth="1.2" />
                    <path d="M8 21h8" stroke={accent} strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                </div>
              </motion.div>

              {/* Micro label */}
              <motion.p
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.35 }}
                className="text-[10px] uppercase tracking-[0.18em] mb-3"
                style={{ color: accent, fontFamily: "'Space Mono', monospace" }}
              >
                Achievement Unlocked
              </motion.p>

              {/* Badge name */}
              <motion.h2
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.4 }}
                className="text-[26px] font-bold text-[#F0EDE5] uppercase tracking-tight mb-2 text-center"
              >
                {badgeName}
              </motion.h2>

              {/* Divider */}
              <motion.div
                initial={{ scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ delay: 0.45, duration: 0.5 }}
                className="w-16 h-[1px] mb-4"
                style={{ background: `linear-gradient(90deg, transparent, ${accent}80, transparent)` }}
              />

              {/* Description */}
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.5 }}
                className="text-[13px] text-[#949494] text-center max-w-[340px] leading-relaxed mb-8"
              >
                {description}
              </motion.p>

              {/* Tier indicator */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: 0.55 }}
                className="flex items-center gap-4 mb-8"
              >
                <div className="h-[1px] w-8" style={{ backgroundColor: `${accent}30` }} />
                <div className="flex items-center gap-2.5">
                  {(["bronze", "silver", "gold"] as const).map((t) => (
                    <div key={t} className="flex flex-col items-center gap-1.5">
                      <div
                        className="w-2 h-2 rounded-full transition-all"
                        style={{
                          backgroundColor: tierColors[t],
                          opacity: t === tier ? 1 : 0.2,
                          boxShadow: t === tier ? `0 0 10px ${tierColors[t]}60` : "none",
                        }}
                      />
                      {t === tier && (
                        <span
                          className="text-[7px] uppercase tracking-[0.1em]"
                          style={{ color: accent, fontFamily: "'Space Mono', monospace" }}
                        >
                          {tierLabels[t]}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
                <div className="h-[1px] w-8" style={{ backgroundColor: `${accent}30` }} />
              </motion.div>

              {/* Continue button */}
              <motion.button
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.6 }}
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

            {/* Bottom accent bar */}
            <div className="h-[1px]" style={{ background: `linear-gradient(90deg, transparent, ${accent}30, transparent)` }} />
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
