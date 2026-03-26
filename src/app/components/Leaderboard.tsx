import { Card } from "./ui/card";
import { Avatar } from "./ui/avatar";
import { Badge } from "./ui/badge";
import { Trophy, Medal, Award } from "lucide-react";

interface LeaderboardEntry {
  rank: number;
  username: string;
  points: number;
  level: number;
  isCurrentUser?: boolean;
}

interface LeaderboardProps {
  entries: LeaderboardEntry[];
}

export function Leaderboard({ entries }: LeaderboardProps) {
  const getRankIcon = (rank: number) => {
    if (rank === 1) return <Trophy className="h-5 w-5 text-yellow-500" />;
    if (rank === 2) return <Medal className="h-5 w-5 text-gray-400" />;
    if (rank === 3) return <Award className="h-5 w-5 text-orange-600" />;
    return null;
  };

  const getRankColor = (rank: number) => {
    if (rank === 1) return "text-yellow-500";
    if (rank === 2) return "text-gray-400";
    if (rank === 3) return "text-orange-600";
    return "text-muted-foreground";
  };

  return (
    <Card className="p-6">
      <div className="flex items-center gap-2 mb-6">
        <Trophy className="h-6 w-6 text-yellow-500" />
        <h2 className="text-2xl font-bold">Leaderboard</h2>
      </div>

      <div className="space-y-3">
        {entries.map((entry) => (
          <div
            key={entry.rank}
            className={`flex items-center gap-4 p-3 rounded-lg transition-all ${
              entry.isCurrentUser
                ? "bg-gradient-to-r from-purple-500/20 to-blue-500/20 border border-purple-500/30"
                : "bg-gray-500/5 hover:bg-gray-500/10"
            }`}
          >
            <div className={`w-8 font-bold text-center ${getRankColor(entry.rank)}`}>
              {entry.rank <= 3 ? getRankIcon(entry.rank) : `#${entry.rank}`}
            </div>

            <Avatar className="h-10 w-10">
              <div className="w-full h-full bg-gradient-to-br from-purple-500 to-blue-500 flex items-center justify-center text-white">
                {entry.username.charAt(0).toUpperCase()}
              </div>
            </Avatar>

            <div className="flex-1">
              <div className="font-semibold flex items-center gap-2">
                {entry.username}
                {entry.isCurrentUser && (
                  <Badge variant="outline" className="text-xs">
                    You
                  </Badge>
                )}
              </div>
              <div className="text-sm text-muted-foreground">Level {entry.level}</div>
            </div>

            <div className="text-right">
              <div className="font-bold text-lg">{entry.points.toLocaleString()}</div>
              <div className="text-xs text-muted-foreground">points</div>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}
