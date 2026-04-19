import { Card } from "./ui/card";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { Badge } from "./ui/badge";
import { LucideIcon, Clock, Star } from "lucide-react";

interface ChallengeCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  progress: number;
  maxProgress: number;
  reward: number;
  timeLeft?: string;
  difficulty: "easy" | "medium" | "hard";
  onAction: () => void;
  completed?: boolean;
}

const difficultyColors = {
  easy: "bg-green-500/20 text-green-500",
  medium: "bg-yellow-500/20 text-yellow-500",
  hard: "bg-red-500/20 text-red-500",
};

export function ChallengeCard({
  title,
  description,
  icon: Icon,
  progress,
  maxProgress,
  reward,
  timeLeft,
  difficulty,
  onAction,
  completed = false,
}: ChallengeCardProps) {
  const progressPercentage = (progress / maxProgress) * 100;

  return (
    <Card className="p-5 bg-gradient-to-br from-white/5 to-white/10 border-gray-700/30 hover:border-purple-500/30 transition-all">
      <div className="flex gap-4">
        <div className="p-3 rounded-lg bg-gradient-to-br from-purple-500 to-blue-500 h-fit">
          <Icon className="h-6 w-6 text-white" />
        </div>

        <div className="flex-1 space-y-3">
          <div>
            <div className="flex items-start justify-between gap-2 mb-1">
              <h3 className="font-semibold">{title}</h3>
              <Badge className={difficultyColors[difficulty]} variant="outline">
                {difficulty}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">{description}</p>
          </div>

          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">
                Progress: {progress} / {maxProgress}
              </span>
              <span className="font-semibold">{Math.round(progressPercentage)}%</span>
            </div>
            <Progress value={progressPercentage} className="h-2" />
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-1">
                <Star className="h-4 w-4 text-yellow-500" />
                <span className="font-semibold text-yellow-500">+{reward} pts</span>
              </div>
              {timeLeft && (
                <div className="flex items-center gap-1 text-muted-foreground">
                  <Clock className="h-4 w-4" />
                  <span>{timeLeft}</span>
                </div>
              )}
            </div>

            <Button
              size="sm"
              onClick={onAction}
              disabled={completed}
              className={
                completed
                  ? ""
                  : "bg-gradient-to-r from-purple-500 to-blue-500 hover:from-purple-600 hover:to-blue-600"
              }
            >
              {completed ? "Completed" : "Complete"}
            </Button>
          </div>
        </div>
      </div>
    </Card>
  );
}
