import { RacingBadge } from "./RacingBadge";
import { Button } from "./ui/button";
import { Download, Share2 } from "lucide-react";

interface Badge {
  title: string;
  description: string;
  unlocked: boolean;
  category?: "progress" | "technique" | "consistency" | "learning" | "endurance";
}

interface ShareableCardProps {
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
  licenseLevel: "N" | "D" | "C" | "B" | "A" | "S";
  onDownload?: () => void;
  onShare?: () => void;
}

const licenseLevelColors = {
  N: "#22C55E",
  D: "#C9A84C",
  C: "#FACC15",
  B: "#8B5CF6",
  A: "#FF2A2A",
  S: "#F0EDE5",
};

export function ShareableCard({
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
  onDownload,
  onShare,
}: ShareableCardProps) {
  const licenseColor = licenseLevelColors[licenseLevel];

  return (
    <div className="space-y-4">
      {/* Main Card - Optimized for social sharing */}
      <div 
        className="relative bg-gradient-to-br from-[#0a0a0a] via-[#1a1a1a] to-[#000000] rounded-3xl overflow-hidden"
        style={{ 
          width: "1200px", 
          maxWidth: "100%",
          aspectRatio: "1200/630",
          boxShadow: "0 8px 60px rgba(0,0,0,0.7)"
        }}
      >
        {/* Grid pattern background */}
        <div 
          className="absolute inset-0 opacity-5"
          style={{
            backgroundImage: `
              linear-gradient(rgba(240,237,229,0.5) 1px, transparent 1px),
              linear-gradient(90deg, rgba(240,237,229,0.5) 1px, transparent 1px)
            `,
            backgroundSize: "40px 40px"
          }}
        />

        {/* Gradient overlay */}
        <div 
          className="absolute inset-0 opacity-20"
          style={{
            background: `radial-gradient(circle at top right, ${licenseColor}40, transparent 50%)`
          }}
        />

        <div className="relative h-full p-12 flex flex-col">
          {/* Header */}
          <div className="flex items-start justify-between mb-8">
            <div className="flex-1">
              <div className="flex items-center gap-3 mb-2">
                <div className="text-sm text-[#949494] uppercase tracking-[0.2em]">LAP COACH</div>
                <div className="h-4 w-px bg-[#949494]" />
                <div className="text-sm text-[#949494] uppercase tracking-wider">{sessionType}</div>
              </div>
              <h2 className="text-5xl font-bold text-[#F0EDE5] mb-3">{driverName}</h2>
              <div className="text-lg text-[#949494]">
                <span className="uppercase tracking-wide">{track}</span>
                <span className="mx-3">•</span>
                <span>{date}</span>
              </div>
            </div>

            {/* License badge - larger for sharing */}
            <div 
              className="w-24 h-24 rounded-2xl flex items-center justify-center border-2 text-5xl font-bold shrink-0"
              style={{ 
                borderColor: licenseColor,
                backgroundColor: `${licenseColor}15`,
                color: licenseColor,
                boxShadow: `0 0 30px ${licenseColor}40`
              }}
            >
              {licenseLevel}
            </div>
          </div>

          {/* Stats - Prominent display */}
          <div className="grid grid-cols-4 gap-6 mb-10">
            {/* Best Lap - Hero stat */}
            <div className="col-span-1 relative">
              <div className="text-sm text-[#949494] uppercase tracking-wider mb-3">Best Lap</div>
              <div 
                className="text-6xl font-bold tracking-tight"
                style={{ 
                  color: "#22C55E",
                  textShadow: "0 0 30px rgba(34,197,94,0.5)"
                }}
              >
                {bestLap}
              </div>
            </div>

            {/* Score */}
            <div className="relative">
              <div className="text-sm text-[#949494] uppercase tracking-wider mb-3">Score</div>
              <div className="text-5xl font-bold text-[#F0EDE5]">
                {score}
                <span className="text-2xl text-[#949494]">/{maxScore}</span>
              </div>
            </div>

            {/* Laps */}
            <div className="relative">
              <div className="text-sm text-[#949494] uppercase tracking-wider mb-3">Laps</div>
              <div className="text-5xl font-bold text-[#F0EDE5]">{laps}</div>
            </div>

            {/* Consistency */}
            <div className="relative">
              <div className="text-sm text-[#949494] uppercase tracking-wider mb-3">Consistency</div>
              <div 
                className="text-5xl font-bold"
                style={{ 
                  color: "#22C55E",
                  textShadow: "0 0 20px rgba(34,197,94,0.3)"
                }}
              >
                {consistency}%
              </div>
            </div>
          </div>

          {/* Badges showcase */}
          <div className="mt-auto">
            <div className="text-sm text-[#949494] uppercase tracking-wider mb-4">Achievement Highlights</div>
            <div className="flex gap-6">
              {badges.filter(b => b.unlocked).slice(0, 5).map((badge, index) => (
                <RacingBadge key={index} {...badge} />
              ))}
            </div>
          </div>

          {/* Footer branding */}
          <div className="absolute bottom-8 right-12 text-sm text-[#949494] tracking-[0.3em] uppercase">
            lap-coach.racing
          </div>
        </div>

        {/* Accent lines */}
        <div 
          className="absolute top-0 left-0 right-0 h-1"
          style={{ 
            background: `linear-gradient(90deg, transparent, ${licenseColor}, transparent)`
          }}
        />
        <div 
          className="absolute bottom-0 left-0 right-0 h-1"
          style={{ 
            background: `linear-gradient(90deg, transparent, ${licenseColor}, transparent)`
          }}
        />
      </div>

      {/* Action buttons */}
      <div className="flex gap-3 max-w-md">
        <Button
          onClick={onDownload}
          className="flex-1 bg-[#C9A84C] hover:bg-[#b89840] text-[#000000] font-semibold h-12"
          style={{ boxShadow: "0 0 20px rgba(201,168,76,0.3)" }}
        >
          <Download className="h-4 w-4 mr-2" />
          Download Card
        </Button>
        
        <Button
          onClick={onShare}
          className="flex-1 bg-[#22C55E] hover:bg-[#1ea54e] text-[#000000] font-semibold h-12"
          style={{ boxShadow: "0 0 20px rgba(34,197,94,0.3)" }}
        >
          <Share2 className="h-4 w-4 mr-2" />
          Share
        </Button>
      </div>
    </div>
  );
}
