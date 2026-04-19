import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { LucideIcon } from "lucide-react";
import { motion } from "motion/react";

interface GitHubBadgeProps {
  title: string;
  description: string;
  icon: LucideIcon;
  unlocked: boolean;
  progress?: number;
  maxProgress?: number;
  tier: "bronze" | "silver" | "gold" | "platinum";
  date?: string;
}

const tierColors = {
  bronze: {
    gradient: "from-amber-700 via-orange-600 to-amber-800",
    glow: "shadow-[0_0_20px_rgba(217,119,6,0.5)]",
    border: "border-amber-600/50",
    bg: "bg-amber-900/20",
  },
  silver: {
    gradient: "from-slate-400 via-gray-300 to-slate-500",
    glow: "shadow-[0_0_20px_rgba(148,163,184,0.5)]",
    border: "border-slate-400/50",
    bg: "bg-slate-800/20",
  },
  gold: {
    gradient: "from-yellow-400 via-amber-300 to-yellow-500",
    glow: "shadow-[0_0_20px_rgba(251,191,36,0.6)]",
    border: "border-yellow-400/50",
    bg: "bg-yellow-900/20",
  },
  platinum: {
    gradient: "from-cyan-400 via-blue-400 to-cyan-500",
    glow: "shadow-[0_0_25px_rgba(34,211,238,0.7)]",
    border: "border-cyan-400/60",
    bg: "bg-cyan-900/20",
  },
};

export function GitHubBadge({
  title,
  description,
  icon: Icon,
  unlocked,
  progress,
  maxProgress,
  tier,
  date,
}: GitHubBadgeProps) {
  const colors = tierColors[tier];

  return (
    <motion.div
      whileHover={unlocked ? { scale: 1.05, y: -5 } : {}}
      transition={{ type: "spring", stiffness: 300, damping: 20 }}
    >
      <Card
        className={`relative p-5 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 ${
          unlocked ? colors.border : "border-slate-800/30"
        } ${unlocked ? colors.glow : ""} overflow-hidden transition-all duration-300`}
      >
        {/* Background grid pattern */}
        <div className="absolute inset-0 opacity-5">
          <div
            className="w-full h-full"
            style={{
              backgroundImage: `linear-gradient(rgba(34,211,238,0.3) 1px, transparent 1px),
                               linear-gradient(90deg, rgba(34,211,238,0.3) 1px, transparent 1px)`,
              backgroundSize: "20px 20px",
            }}
          />
        </div>

        <div className="relative flex flex-col items-center text-center space-y-4">
          {/* Icon container */}
          <div className="relative">
            <div
              className={`p-5 rounded-xl ${
                unlocked
                  ? `bg-gradient-to-br ${colors.gradient} ${colors.glow}`
                  : "bg-slate-800/30 border border-slate-700/30"
              } ${unlocked ? "" : "opacity-40 grayscale"} transition-all duration-300`}
            >
              <Icon className="h-10 w-10 text-slate-950" strokeWidth={2.5} />
            </div>
            
            {/* Glowing corner accents */}
            {unlocked && (
              <>
                <div className={`absolute -top-1 -right-1 w-3 h-3 bg-gradient-to-br ${colors.gradient} rounded-full blur-sm`} />
                <div className={`absolute -bottom-1 -left-1 w-3 h-3 bg-gradient-to-br ${colors.gradient} rounded-full blur-sm`} />
              </>
            )}
          </div>

          {/* Content */}
          <div className="space-y-2">
            <div className="flex items-center justify-center gap-2">
              <h3
                className={`font-bold text-base ${
                  unlocked ? "text-white" : "text-slate-500"
                }`}
              >
                {title}
              </h3>
            </div>
            
            <p
              className={`text-sm ${
                unlocked ? "text-slate-400" : "text-slate-600"
              } min-h-[40px]`}
            >
              {description}
            </p>
          </div>

          {/* Progress bar for locked badges */}
          {progress !== undefined && maxProgress !== undefined && !unlocked && (
            <div className="w-full space-y-1">
              <div className="flex justify-between text-xs text-slate-500">
                <span>{progress} / {maxProgress}</span>
                <span>{Math.round((progress / maxProgress) * 100)}%</span>
              </div>
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${(progress / maxProgress) * 100}%` }}
                  transition={{ duration: 1, ease: "easeOut" }}
                  className="h-full bg-gradient-to-r from-cyan-500 to-blue-500"
                />
              </div>
            </div>
          )}

          {/* Tier badge and date */}
          <div className="flex items-center gap-2 w-full justify-between text-xs">
            <Badge
              variant={unlocked ? "default" : "outline"}
              className={
                unlocked
                  ? `bg-gradient-to-r ${colors.gradient} text-slate-950 border-0 font-semibold uppercase tracking-wider`
                  : "border-slate-700 text-slate-600"
              }
            >
              {tier}
            </Badge>
            
            {unlocked && date && (
              <span className="text-slate-500 font-mono">{date}</span>
            )}
          </div>
        </div>

        {/* Locked overlay */}
        {!unlocked && (
          <div className="absolute inset-0 bg-gradient-to-t from-slate-950/80 to-transparent pointer-events-none" />
        )}
      </Card>
    </motion.div>
  );
}
