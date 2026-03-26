import { Card } from "./ui/card";
import { Badge } from "./ui/badge";
import { Progress } from "./ui/progress";
import { 
  GitBranch, 
  GitCommit, 
  GitPullRequest, 
  Star, 
  Code2, 
  Activity,
  Calendar,
  TrendingUp
} from "lucide-react";
import { motion } from "motion/react";

interface GitHubProfileCardProps {
  username: string;
  avatar: string;
  bio?: string;
  publicRepos: number;
  followers: number;
  following: number;
  totalStars: number;
  totalCommits: number;
  activeDays: number;
  memberSince: string;
  topLanguages: { name: string; percentage: number; color: string }[];
  contributionLevel: "beginner" | "intermediate" | "advanced" | "elite";
}

const levelConfig = {
  beginner: { color: "from-green-500 to-emerald-500", label: "Beginner" },
  intermediate: { color: "from-blue-500 to-cyan-500", label: "Intermediate" },
  advanced: { color: "from-purple-500 to-pink-500", label: "Advanced" },
  elite: { color: "from-yellow-400 to-orange-500", label: "Elite" },
};

export function GitHubProfileCard({
  username,
  avatar,
  bio,
  publicRepos,
  followers,
  following,
  totalStars,
  totalCommits,
  activeDays,
  memberSince,
  topLanguages,
  contributionLevel,
}: GitHubProfileCardProps) {
  const level = levelConfig[contributionLevel];

  return (
    <Card className="relative overflow-hidden bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 border-cyan-500/30 shadow-[0_0_50px_rgba(34,211,238,0.2)]">
      {/* Racing grid background */}
      <div className="absolute inset-0 opacity-5">
        <div
          className="w-full h-full"
          style={{
            backgroundImage: `linear-gradient(rgba(34,211,238,0.5) 1px, transparent 1px),
                             linear-gradient(90deg, rgba(34,211,238,0.5) 1px, transparent 1px)`,
            backgroundSize: "30px 30px",
          }}
        />
      </div>

      {/* Top accent line */}
      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-transparent via-cyan-500 to-transparent" />

      <div className="relative p-8 space-y-6">
        {/* Header Section */}
        <div className="flex items-start gap-6">
          {/* Avatar with glow effect */}
          <motion.div
            whileHover={{ scale: 1.05 }}
            className="relative"
          >
            <div className="absolute inset-0 bg-gradient-to-br from-cyan-500 to-blue-500 rounded-2xl blur-xl opacity-50" />
            <img
              src={avatar}
              alt={username}
              className="relative w-24 h-24 rounded-2xl border-2 border-cyan-500/50 shadow-[0_0_30px_rgba(34,211,238,0.4)]"
            />
            {/* Corner accents */}
            <div className="absolute -top-1 -right-1 w-3 h-3 bg-cyan-400 rounded-full shadow-[0_0_10px_rgba(34,211,238,0.8)]" />
            <div className="absolute -bottom-1 -left-1 w-3 h-3 bg-blue-400 rounded-full shadow-[0_0_10px_rgba(59,130,246,0.8)]" />
          </motion.div>

          {/* User info */}
          <div className="flex-1 space-y-3">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h2 className="text-3xl font-bold text-white">{username}</h2>
                <Badge
                  className={`bg-gradient-to-r ${level.color} text-white border-0 px-3 py-1 shadow-lg uppercase tracking-wider text-xs`}
                >
                  {level.label}
                </Badge>
              </div>
              
              {bio && (
                <p className="text-slate-400 text-sm max-w-md">{bio}</p>
              )}
            </div>

            {/* Member since */}
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Calendar className="h-4 w-4" />
              <span>Member since {memberSince}</span>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-3 gap-4">
          {[
            { icon: Code2, label: "Repositories", value: publicRepos, color: "cyan" },
            { icon: Star, label: "Total Stars", value: totalStars, color: "yellow" },
            { icon: GitCommit, label: "Commits", value: totalCommits, color: "green" },
          ].map((stat, index) => (
            <motion.div
              key={stat.label}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
              className="relative group"
            >
              <div className="p-4 rounded-xl bg-slate-900/50 border border-slate-800/50 hover:border-cyan-500/30 transition-all duration-300 hover:shadow-[0_0_20px_rgba(34,211,238,0.15)]">
                <div className="flex items-center gap-3">
                  <div className={`p-2 rounded-lg bg-${stat.color}-500/10`}>
                    <stat.icon className={`h-5 w-5 text-${stat.color}-500`} />
                  </div>
                  <div>
                    <div className="text-2xl font-bold text-white">{stat.value}</div>
                    <div className="text-xs text-slate-500 uppercase tracking-wide">
                      {stat.label}
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          ))}
        </div>

        {/* Activity Section */}
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 rounded-xl bg-gradient-to-br from-cyan-500/5 to-blue-500/5 border border-cyan-500/20">
            <div className="flex items-center gap-2 mb-2">
              <Activity className="h-4 w-4 text-cyan-400" />
              <span className="text-sm text-slate-400 uppercase tracking-wide">
                Network
              </span>
            </div>
            <div className="flex items-baseline gap-3">
              <div>
                <div className="text-xl font-bold text-white">{followers}</div>
                <div className="text-xs text-slate-500">Followers</div>
              </div>
              <div className="text-slate-600">•</div>
              <div>
                <div className="text-xl font-bold text-white">{following}</div>
                <div className="text-xs text-slate-500">Following</div>
              </div>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-gradient-to-br from-purple-500/5 to-pink-500/5 border border-purple-500/20">
            <div className="flex items-center gap-2 mb-2">
              <TrendingUp className="h-4 w-4 text-purple-400" />
              <span className="text-sm text-slate-400 uppercase tracking-wide">
                Active Days
              </span>
            </div>
            <div className="text-2xl font-bold text-white">{activeDays}</div>
            <div className="text-xs text-slate-500">This year</div>
          </div>
        </div>

        {/* Language distribution */}
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm text-slate-400 uppercase tracking-wide">
            <Code2 className="h-4 w-4" />
            <span>Top Languages</span>
          </div>
          
          <div className="space-y-2">
            {topLanguages.map((lang) => (
              <div key={lang.name} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-300">{lang.name}</span>
                  <span className="text-slate-500 font-mono">{lang.percentage}%</span>
                </div>
                <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${lang.percentage}%` }}
                    transition={{ duration: 1, delay: 0.2 }}
                    className="h-full rounded-full"
                    style={{ backgroundColor: lang.color }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom accent line */}
        <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-gradient-to-r from-transparent via-cyan-500/50 to-transparent" />
      </div>

      {/* Corner decorations */}
      <div className="absolute top-4 right-4 w-20 h-20 border-t-2 border-r-2 border-cyan-500/20 rounded-tr-2xl" />
      <div className="absolute bottom-4 left-4 w-20 h-20 border-b-2 border-l-2 border-cyan-500/20 rounded-bl-2xl" />
    </Card>
  );
}
