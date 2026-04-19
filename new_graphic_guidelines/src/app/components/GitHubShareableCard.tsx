import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { 
  Trophy, 
  Download, 
  Share2,
  Sparkles,
  TrendingUp,
  Code2
} from "lucide-react";
import { motion } from "motion/react";

interface Achievement {
  icon: string;
  label: string;
}

interface GitHubShareableCardProps {
  username: string;
  avatar: string;
  year: number;
  totalContributions: number;
  longestStreak: number;
  topLanguage: string;
  reposCreated: number;
  achievements: Achievement[];
  rank: string;
  onDownload?: () => void;
  onShare?: () => void;
}

export function GitHubShareableCard({
  username,
  avatar,
  year,
  totalContributions,
  longestStreak,
  topLanguage,
  reposCreated,
  achievements,
  rank,
  onDownload,
  onShare,
}: GitHubShareableCardProps) {
  return (
    <div className="space-y-4">
      {/* Main shareable card */}
      <Card className="relative overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-black border-none shadow-[0_0_80px_rgba(34,211,238,0.3)]">
        {/* Animated background grid */}
        <div className="absolute inset-0 opacity-10">
          <motion.div
            className="w-full h-full"
            style={{
              backgroundImage: `linear-gradient(rgba(34,211,238,0.8) 1px, transparent 1px),
                               linear-gradient(90deg, rgba(34,211,238,0.8) 1px, transparent 1px)`,
              backgroundSize: "40px 40px",
            }}
            animate={{
              backgroundPosition: ["0px 0px", "40px 40px"],
            }}
            transition={{
              duration: 20,
              repeat: Infinity,
              ease: "linear",
            }}
          />
        </div>

        {/* Gradient overlays */}
        <div className="absolute inset-0 bg-gradient-to-br from-cyan-500/10 via-transparent to-blue-500/10" />
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-500" />

        <div className="relative p-10 space-y-8">
          {/* Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-cyan-400 to-blue-500 rounded-2xl blur-2xl opacity-60" />
                <img
                  src={avatar}
                  alt={username}
                  className="relative w-20 h-20 rounded-2xl border-2 border-cyan-400/50 shadow-[0_0_40px_rgba(34,211,238,0.5)]"
                />
              </div>
              
              <div>
                <h2 className="text-3xl font-bold text-white mb-1">{username}</h2>
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-cyan-400" />
                  <span className="text-cyan-400 font-semibold">{year} Year in Review</span>
                </div>
              </div>
            </div>

            <Badge className="bg-gradient-to-r from-yellow-400 to-orange-500 text-slate-950 border-0 px-4 py-2 text-base shadow-[0_0_20px_rgba(251,191,36,0.4)]">
              <Trophy className="h-4 w-4 mr-1" />
              {rank}
            </Badge>
          </div>

          {/* Stats showcase */}
          <div className="grid grid-cols-2 gap-6">
            {/* Main stat - Contributions */}
            <div className="col-span-2 p-6 rounded-2xl bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 shadow-[0_0_30px_rgba(34,211,238,0.1)]">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm text-cyan-400 uppercase tracking-wider mb-2 flex items-center gap-2">
                    <TrendingUp className="h-4 w-4" />
                    Total Contributions
                  </div>
                  <div className="text-6xl font-bold text-white mb-1">
                    {totalContributions.toLocaleString()}
                  </div>
                  <div className="text-slate-400">commits, PRs, and issues</div>
                </div>
                
                {/* Decorative chart visualization */}
                <div className="flex items-end gap-1 h-24">
                  {[65, 80, 45, 90, 70, 95, 85, 75, 100, 88, 92, 78].map((height, i) => (
                    <motion.div
                      key={i}
                      initial={{ height: 0 }}
                      animate={{ height: `${height}%` }}
                      transition={{ delay: i * 0.05, duration: 0.5 }}
                      className="w-2 bg-gradient-to-t from-cyan-500 to-blue-400 rounded-t"
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Streak */}
            <div className="p-5 rounded-xl bg-gradient-to-br from-orange-500/10 to-red-500/10 border border-orange-500/30">
              <div className="text-xs text-orange-400 uppercase tracking-wider mb-2">
                Longest Streak
              </div>
              <div className="text-4xl font-bold text-white mb-1">{longestStreak}</div>
              <div className="text-sm text-slate-400">consecutive days</div>
            </div>

            {/* Repos created */}
            <div className="p-5 rounded-xl bg-gradient-to-br from-purple-500/10 to-pink-500/10 border border-purple-500/30">
              <div className="text-xs text-purple-400 uppercase tracking-wider mb-2 flex items-center gap-1">
                <Code2 className="h-3 w-3" />
                Repos Created
              </div>
              <div className="text-4xl font-bold text-white mb-1">{reposCreated}</div>
              <div className="text-sm text-slate-400">new projects</div>
            </div>
          </div>

          {/* Top language */}
          <div className="p-5 rounded-xl bg-gradient-to-r from-green-500/10 to-emerald-500/10 border border-green-500/30">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-xs text-green-400 uppercase tracking-wider mb-1">
                  Top Language
                </div>
                <div className="text-2xl font-bold text-white">{topLanguage}</div>
              </div>
              <div className="p-3 rounded-lg bg-green-500/20">
                <Code2 className="h-6 w-6 text-green-400" />
              </div>
            </div>
          </div>

          {/* Achievements */}
          <div className="space-y-3">
            <div className="text-sm text-slate-400 uppercase tracking-wider">
              Achievements Unlocked
            </div>
            <div className="flex gap-3 flex-wrap">
              {achievements.map((achievement, index) => (
                <motion.div
                  key={index}
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ delay: index * 0.1, type: "spring" }}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-slate-800/50 to-slate-700/50 border border-slate-600/30"
                >
                  <span className="text-2xl">{achievement.icon}</span>
                  <span className="text-sm text-slate-300">{achievement.label}</span>
                </motion.div>
              ))}
            </div>
          </div>

          {/* Footer branding */}
          <div className="flex items-center justify-between pt-4 border-t border-slate-800/50">
            <div className="text-sm text-slate-500">
              github.com/{username}
            </div>
            <div className="flex items-center gap-2 text-slate-500 text-xs">
              <div className="w-6 h-6 rounded-full bg-slate-800 flex items-center justify-center">
                <svg className="w-4 h-4 fill-current" viewBox="0 0 16 16">
                  <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
                </svg>
              </div>
              <span className="uppercase tracking-wider">GitHub Year in Review</span>
            </div>
          </div>
        </div>

        {/* Corner accents */}
        <div className="absolute top-0 right-0 w-32 h-32 border-t-2 border-r-2 border-cyan-500/20" />
        <div className="absolute bottom-0 left-0 w-32 h-32 border-b-2 border-l-2 border-cyan-500/20" />
      </Card>

      {/* Action buttons */}
      <div className="flex gap-3">
        <Button
          onClick={onDownload}
          className="flex-1 bg-gradient-to-r from-cyan-500 to-blue-500 hover:from-cyan-600 hover:to-blue-600 text-white shadow-[0_0_20px_rgba(34,211,238,0.3)] hover:shadow-[0_0_30px_rgba(34,211,238,0.5)] transition-all"
        >
          <Download className="h-4 w-4 mr-2" />
          Download Card
        </Button>
        
        <Button
          onClick={onShare}
          className="flex-1 bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white shadow-[0_0_20px_rgba(168,85,247,0.3)] hover:shadow-[0_0_30px_rgba(168,85,247,0.5)] transition-all"
        >
          <Share2 className="h-4 w-4 mr-2" />
          Share
        </Button>
      </div>
    </div>
  );
}
