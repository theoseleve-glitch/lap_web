import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { LucideIcon } from "lucide-react";
import { motion } from "motion/react";

interface AchievementCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  unlocked: boolean;
  progress?: number;
  maxProgress?: number;
  points: number;
  rarity: "common" | "rare" | "epic" | "legendary";
}

const rarityColors = {
  common: "from-gray-500 to-gray-600",
  rare: "from-blue-500 to-blue-600",
  epic: "from-purple-500 to-purple-600",
  legendary: "from-yellow-500 to-orange-500",
};

const rarityBorders = {
  common: "border-gray-500/30",
  rare: "border-blue-500/30",
  epic: "border-purple-500/30",
  legendary: "border-yellow-500/30",
};

export function AchievementCard({
  title,
  description,
  icon: Icon,
  unlocked,
  progress,
  maxProgress,
  points,
  rarity,
}: AchievementCardProps) {
  return (
    <motion.div
      whileHover={unlocked ? { scale: 1.05, y: -5 } : {}}
      transition={{ type: "spring", stiffness: 300 }}
    >
      <Card
        className={`p-4 ${unlocked ? rarityBorders[rarity] : "border-gray-700/30"} ${
          unlocked ? "bg-gradient-to-br from-white/5 to-white/10" : "bg-gray-900/20"
        } transition-all duration-300`}
      >
        <div className="flex flex-col items-center text-center space-y-3">
          <div
            className={`p-4 rounded-full ${
              unlocked
                ? `bg-gradient-to-br ${rarityColors[rarity]}`
                : "bg-gray-700/30"
            } ${unlocked ? "" : "opacity-30"}`}
          >
            <Icon className="h-8 w-8 text-white" />
          </div>
          
          <div className="space-y-1">
            <h3 className={`font-semibold ${unlocked ? "" : "opacity-50"}`}>
              {title}
            </h3>
            <p className={`text-sm text-muted-foreground ${unlocked ? "" : "opacity-50"}`}>
              {description}
            </p>
          </div>

          {progress !== undefined && maxProgress !== undefined && !unlocked && (
            <div className="w-full">
              <div className="text-xs text-muted-foreground mb-1">
                {progress} / {maxProgress}
              </div>
              <div className="w-full h-2 bg-gray-700/30 rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300"
                  style={{ width: `${(progress / maxProgress) * 100}%` }}
                />
              </div>
            </div>
          )}

          <Badge
            variant={unlocked ? "default" : "outline"}
            className={
              unlocked
                ? `bg-gradient-to-r ${rarityColors[rarity]} text-white border-0`
                : "opacity-50"
            }
          >
            {points} pts
          </Badge>
        </div>
      </Card>
    </motion.div>
  );
}
