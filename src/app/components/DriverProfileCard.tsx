import { useState } from "react";
import { RacingBadge } from "./RacingBadge";
import { Pencil, Flame } from "lucide-react";

interface Badge {
  title: string;
  description: string;
  unlocked: boolean;
  category?: "progress" | "technique" | "consistency" | "learning" | "endurance";
}

interface DriverProfileCardProps {
  driverName: string;
  track: string;
  date: string;
  sessionType: string;
  bestLap: string;
  score: number;
  maxScore: number;
  laps: number;
  consistency: number;
  badges: Badge[];
  licenseLevel: "Rookie" | "Club" | "National" | "Pro" | "Elite" | "Legend";
  level: number;
  currentXP: number;
  nextLevelXP: number;
  streak: number;
  lapsToNextLicense?: number;
  lapsRequiredForNext?: number;
  scoreToNextLicense?: number;
  scoreRequiredForNext?: number;
}

const licenseOrder: DriverProfileCardProps["licenseLevel"][] = [
  "Rookie", "Club", "National", "Pro", "Elite", "Legend"
];

const licenseLetters: Record<string, string> = {
  Rookie: "R",
  Club: "C",
  National: "N",
  Pro: "P",
  Elite: "E",
  Legend: "L",
};

// Charter colors only
const licenseColors: Record<string, string> = {
  Rookie: "#949494",   // Steel
  Club: "#22C55E",     // Acid Green
  National: "#C9A84C", // Pit Orange
  Pro: "#8B5CF6",      // Racing Purple
  Elite: "#FACC15",    // Marshal Yellow
  Legend: "#FF2A2A",   // Safety Red
};

export function DriverProfileCard({
  driverName,
  track,
  date,
  sessionType,
  bestLap,
  score,
  maxScore,
  laps,
  consistency,
  badges,
  licenseLevel,
  level,
  currentXP,
  nextLevelXP,
  streak,
  lapsToNextLicense = 182,
  lapsRequiredForNext = 240,
  scoreToNextLicense = 78,
  scoreRequiredForNext = 86,
}: DriverProfileCardProps) {
  const [notes, setNotes] = useState("");
  const [editingNotes, setEditingNotes] = useState(false);
  const xpPercent = (currentXP / nextLevelXP) * 100;
  const currentLicenseIdx = licenseOrder.indexOf(licenseLevel);
  const nextLicense = currentLicenseIdx < licenseOrder.length - 1 ? licenseOrder[currentLicenseIdx + 1] : null;
  const color = licenseColors[licenseLevel];
  const nextColor = nextLicense ? licenseColors[nextLicense] : color;
  const lapsPercent = (lapsToNextLicense / lapsRequiredForNext) * 100;
  const scorePercent = (scoreToNextLicense / scoreRequiredForNext) * 100;

  return (
    <div className="space-y-6">
      {/* === TOP SECTION: Name + Notes === */}
      <div>
        <div className="flex items-center gap-3 mb-1">
          <h2 className="text-4xl font-bold italic text-[#F0EDE5] uppercase tracking-tight">
            {driverName}
          </h2>
          <Pencil className="w-4 h-4 text-[#949494] cursor-pointer hover:text-[#F0EDE5] transition-colors" />
        </div>
        {editingNotes ? (
          <input
            autoFocus
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => setEditingNotes(false)}
            onKeyDown={(e) => e.key === "Enter" && setEditingNotes(false)}
            placeholder="Add notes..."
            className="bg-transparent text-sm italic text-[#949494] border-b border-[#949494]/30 outline-none w-64 pb-0.5"
          />
        ) : (
          <button
            onClick={() => setEditingNotes(true)}
            className="flex items-center gap-2 text-sm italic text-[#949494] hover:text-[#F0EDE5] transition-colors cursor-pointer"
          >
            {notes || "ADD NOTES..."}
            <Pencil className="w-3 h-3" />
          </button>
        )}
      </div>

      {/* === LEVEL + XP BAR + STREAK (inside bordered pill) === */}
      <div
        className="flex items-center gap-4 px-5 py-3 rounded-[22px] border"
        style={{ borderColor: "rgba(148,148,148,0.2)" }}
      >
        {/* Level circle */}
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center border-2 shrink-0"
          style={{
            borderColor: "#22C55E",
            backgroundColor: "rgba(34,197,94,0.1)",
          }}
        >
          <span className="text-[#22C55E] text-lg font-bold">{level}</span>
        </div>

        {/* XP bar */}
        <div className="flex-1 min-w-0">
          <div className="text-[11px] text-[#F0EDE5] uppercase tracking-[0.1em] mb-1" style={{ fontFamily: "'Space Mono', monospace" }}>
            Level {level} — {currentXP} / {nextLevelXP} XP
          </div>
          <div className="h-3 bg-[#141414] rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700"
              style={{
                width: `${xpPercent}%`,
                backgroundColor: "#22C55E",
              }}
            />
          </div>
        </div>

        {/* Streak pill */}
        <div
          className="flex items-center gap-2 px-3 py-2 rounded-full border shrink-0"
          style={{
            borderColor: "rgba(201,168,76,0.4)",
            backgroundColor: "rgba(201,168,76,0.15)",
          }}
        >
          <Flame className="w-4 h-4 text-[#C9A84C]" />
          <span
            className="text-[11px] text-[#C9A84C] uppercase tracking-[0.1em] font-bold"
            style={{ fontFamily: "'Space Mono', monospace" }}
          >
            {streak} Day Streak
          </span>
        </div>
      </div>

      {/* === LICENCE CARD === */}
      <div
        className="relative rounded-lg overflow-hidden"
        style={{
          background: `linear-gradient(160deg, ${color}14 0%, #141414 60%)`,
        }}
      >
        {/* Left accent border */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1 rounded-l-lg"
          style={{ backgroundColor: color }}
        />

        <div className="pl-5 pr-5 pt-4 pb-4 space-y-4">
          {/* Header: label + name + badge */}
          <div className="flex items-start justify-between">
            <div>
              <div
                className="text-[10px] uppercase tracking-[0.1em] mb-1"
                style={{ color, fontFamily: "'Consolas', 'Courier New', monospace" }}
              >
                Current Licence
              </div>
              <div className="text-2xl font-black text-white capitalize">
                {licenseLevel.toLowerCase()}
              </div>
            </div>

            {/* Licence letter badge */}
            <div
              className="w-14 h-14 rounded-lg flex items-center justify-center text-2xl font-black text-white"
              style={{
                background: `linear-gradient(135deg, ${color} 0%, ${color}cc 100%)`,
              }}
            >
              {licenseLetters[licenseLevel]}
            </div>
          </div>

          {/* Progress to next tier */}
          {nextLicense && (
            <div className="space-y-2">
              <div
                className="text-[10px] uppercase tracking-[0.05em]"
                style={{ fontFamily: "'Consolas', 'Courier New', monospace", color: "#F0EDE5" }}
              >
                Progress to{" "}
                <span style={{ color: nextColor }} className="capitalize">
                  {nextLicense.toLowerCase()}
                </span>
              </div>

              {/* Laps progress */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span
                    className="text-[10px] uppercase text-[#F0EDE5]"
                    style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
                  >
                    Laps
                  </span>
                  <span
                    className="text-[10px] text-[#F0EDE5]"
                    style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
                  >
                    {lapsToNextLicense} / {lapsRequiredForNext} laps
                  </span>
                </div>
                <div className="h-1.5 bg-[rgba(255,255,255,0.05)] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${lapsPercent}%`,
                      background: `linear-gradient(90deg, ${color}, ${nextColor})`,
                    }}
                  />
                </div>
              </div>

              {/* Score progress */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span
                    className="text-[10px] uppercase text-[#F0EDE5]"
                    style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
                  >
                    Score
                  </span>
                  <span
                    className="text-[10px] text-[#F0EDE5]"
                    style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
                  >
                    {scoreToNextLicense} / {scoreRequiredForNext} needed
                  </span>
                </div>
                <div className="h-1.5 bg-[rgba(255,255,255,0.05)] rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${scorePercent}%`,
                      background: `linear-gradient(90deg, ${color}, ${nextColor})`,
                    }}
                  />
                </div>
              </div>
            </div>
          )}

          {/* Tier progression bar (bottom-border style like Figma) */}
          <div className="flex gap-1">
            {licenseOrder.map((tier, idx) => {
              const isActive = idx === currentLicenseIdx;
              const isPast = idx < currentLicenseIdx;
              const tierColor = licenseColors[tier];

              return (
                <div key={tier} className="flex-1 flex flex-col items-center">
                  {/* Bottom-border segment */}
                  <div
                    className="w-full pt-1 pb-0.5 border-b-2 rounded-sm"
                    style={{
                      borderColor: tierColor,
                      backgroundColor: isActive ? `${tierColor}15` : "transparent",
                      opacity: isPast || isActive ? 1 : 0.3,
                    }}
                  >
                    <p
                      className="text-[8px] text-center capitalize"
                      style={{
                        fontFamily: "'Consolas', 'Courier New', monospace",
                        color: isActive ? tierColor : isPast ? "#949494" : "rgba(160,160,180,0.6)",
                        fontWeight: isActive ? "bold" : "normal",
                      }}
                    >
                      {tier.toLowerCase()}
                    </p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* === SESSION STATS === */}
      <div
        className="rounded-xl p-6 border border-[rgba(240,237,229,0.08)]"
        style={{ background: "linear-gradient(135deg, #0a0a0a 0%, #141414 100%)" }}
      >
        <div
          className="text-[10px] text-[#949494] uppercase tracking-[0.2em] mb-4"
          style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
        >
          Last Session — {track} • {date} • {sessionType}
        </div>
        <div className="grid grid-cols-4 gap-6">
          <div>
            <div
              className="text-[10px] text-[#949494] uppercase tracking-wider mb-1"
              style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
            >
              Best Lap
            </div>
            <div className="text-3xl font-bold text-[#22C55E]" style={{ fontFamily: "'Space Mono', monospace" }}>
              {bestLap}
            </div>
          </div>
          <div>
            <div
              className="text-[10px] text-[#949494] uppercase tracking-wider mb-1"
              style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
            >
              Score
            </div>
            <div className="text-3xl font-bold text-[#F0EDE5]" style={{ fontFamily: "'Space Mono', monospace" }}>
              {score}<span className="text-lg text-[#949494]">/{maxScore}</span>
            </div>
          </div>
          <div>
            <div
              className="text-[10px] text-[#949494] uppercase tracking-wider mb-1"
              style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
            >
              Laps
            </div>
            <div className="text-3xl font-bold text-[#F0EDE5]" style={{ fontFamily: "'Space Mono', monospace" }}>
              {laps}
            </div>
          </div>
          <div>
            <div
              className="text-[10px] text-[#949494] uppercase tracking-wider mb-1"
              style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
            >
              Consistency
            </div>
            <div className="text-3xl font-bold text-[#22C55E]" style={{ fontFamily: "'Space Mono', monospace" }}>
              {consistency}%
            </div>
          </div>
        </div>
      </div>

      {/* === BADGES EARNED === */}
      <div>
        <div
          className="text-[10px] text-[#949494] uppercase tracking-[0.2em] mb-4"
          style={{ fontFamily: "'Consolas', 'Courier New', monospace" }}
        >
          Badges Earned
        </div>
        <div className="flex gap-4 flex-wrap">
          {badges.slice(0, 6).map((badge, index) => (
            <RacingBadge key={index} {...badge} />
          ))}
        </div>
      </div>
    </div>
  );
}
