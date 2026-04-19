import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { Avatar } from "./ui/avatar";
import { Trophy, Star, Zap, Target } from "lucide-react";

interface UserProfileProps {
  username: string;
  level: number;
  currentXP: number;
  xpToNextLevel: number;
  totalPoints: number;
  achievements: number;
  streak: number;
}

export function UserProfile({
  username,
  level,
  currentXP,
  xpToNextLevel,
  totalPoints,
  achievements,
  streak,
}: UserProfileProps) {
  const xpPercentage = (currentXP / xpToNextLevel) * 100;

  return (
    <Card className="p-6 bg-gradient-to-br from-purple-500/10 to-blue-500/10 border-purple-500/20">
      <div className="flex items-start gap-4">
        <Avatar className="h-20 w-20 border-4 border-purple-500/30">
          <div className="w-full h-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-white text-2xl">
            {username.charAt(0).toUpperCase()}
          </div>
        </Avatar>
        
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h2 className="text-2xl font-bold">{username}</h2>
            <Badge className="bg-gradient-to-r from-purple-500 to-blue-500 text-white border-0">
              Level {level}
            </Badge>
          </div>
          
          <div className="space-y-2">
            <div className="flex justify-between text-sm text-muted-foreground">
              <span>XP: {currentXP} / {xpToNextLevel}</span>
              <span>{Math.round(xpPercentage)}%</span>
            </div>
            <Progress value={xpPercentage} className="h-3" />
          </div>

          <div className="grid grid-cols-3 gap-4 mt-4">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-yellow-500/20">
                <Star className="h-5 w-5 text-yellow-500" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Points</div>
                <div className="font-semibold">{totalPoints.toLocaleString()}</div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-purple-500/20">
                <Trophy className="h-5 w-5 text-purple-500" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Achievements</div>
                <div className="font-semibold">{achievements}</div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-orange-500/20">
                <Zap className="h-5 w-5 text-orange-500" />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Streak</div>
                <div className="font-semibold">{streak} days</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Card>
  );
}
