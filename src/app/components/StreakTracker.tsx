import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Flame, Calendar } from "lucide-react";

interface StreakTrackerProps {
  currentStreak: number;
  longestStreak: number;
  daysActive: boolean[];
}

export function StreakTracker({
  currentStreak,
  longestStreak,
  daysActive,
}: StreakTrackerProps) {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  return (
    <Card className="p-6 bg-gradient-to-br from-orange-500/10 to-red-500/10 border-orange-500/20">
      <div className="flex items-center gap-2 mb-4">
        <Flame className="h-6 w-6 text-orange-500" />
        <h2 className="text-2xl font-bold">Daily Streak</h2>
      </div>

      <div className="grid grid-cols-2 gap-4 mb-6">
        <div className="text-center p-4 rounded-lg bg-orange-500/20">
          <div className="text-4xl font-bold text-orange-500">{currentStreak}</div>
          <div className="text-sm text-muted-foreground mt-1">Current Streak</div>
        </div>
        <div className="text-center p-4 rounded-lg bg-red-500/20">
          <div className="text-4xl font-bold text-red-500">{longestStreak}</div>
          <div className="text-sm text-muted-foreground mt-1">Best Streak</div>
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Calendar className="h-4 w-4" />
          <span>This Week</span>
        </div>
        <div className="grid grid-cols-7 gap-2">
          {days.map((day, index) => (
            <div key={day} className="text-center">
              <div className="text-xs text-muted-foreground mb-1">{day}</div>
              <div
                className={`h-10 rounded-lg flex items-center justify-center transition-all ${
                  daysActive[index]
                    ? "bg-gradient-to-br from-orange-500 to-red-500 text-white"
                    : "bg-gray-700/30"
                }`}
              >
                {daysActive[index] && <Flame className="h-5 w-5" />}
              </div>
            </div>
          ))}
        </div>
      </div>

      {currentStreak >= 7 && (
        <Badge className="w-full mt-4 bg-gradient-to-r from-orange-500 to-red-500 text-white border-0 justify-center py-2">
          🔥 You're on fire! Keep it up!
        </Badge>
      )}
    </Card>
  );
}
