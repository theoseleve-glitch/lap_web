import { useState } from "react";
import { DriverProfileCard } from "./components/DriverProfileCard";
import { ShareableCard } from "./components/ShareableCard";
import { RacingBadge } from "./components/RacingBadge";
import { AchievementUnlockOverlay } from "./components/AchievementUnlockOverlay";
import { LevelUpModal } from "./components/LevelUpModal";
import { AchievementToast } from "./components/AchievementToast";
import { BrandGuide } from "./components/BrandGuide";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";
import { Trophy, User, Share2, Sparkles, Palette } from "lucide-react";
import { toast } from "sonner";

export default function App() {
  const [activeTab, setActiveTab] = useState("profile");
  const [showAchievement, setShowAchievement] = useState(false);
  const [showLevelUp, setShowLevelUp] = useState(false);
  const [showToast, setShowToast] = useState(false);

  // Driver data
  const driverData = {
    driverName: "Théo Stipa",
    track: "KCT",
    date: "19 Mar 2026",
    sessionType: "Practice",
    bestLap: "0:32.150",
    score: 43,
    maxScore: 100,
    laps: 20,
    consistency: 33,
    licenseLevel: "Club" as const,
    level: 2,
    currentXP: 225,
    nextLevelXP: 500,
    streak: 3,
    lapsToNextLicense: 182,
    lapsRequiredForNext: 240,
    scoreToNextLicense: 78,
    scoreRequiredForNext: 86,
  };

  // All racing achievements based on the list
  const allBadges = [
    // Progress & Milestones
    { title: "First Lap", description: "Unlocked after completing the first recorded lap", unlocked: true, category: "progress" as const },
    { title: "Session Starter", description: "Unlocked after finishing the first full session", unlocked: true, category: "progress" as const },
    { title: "Data Rookie", description: "Unlocked after uploading the first telemetry file", unlocked: true, category: "progress" as const },
    { title: "Clean Driver", description: "Unlocked after completing a session with no invalid laps", unlocked: false, category: "progress" as const },
    { title: "Consistent One", description: "Unlocked after 5 laps within a tight pace window", unlocked: false, category: "consistency" as const },
    { title: "Hotlap Hunter", description: "Unlocked after setting a personal best lap", unlocked: true, category: "progress" as const },
    { title: "Delta Chaser", description: "Unlocked after improving lap time in 3 consecutive sessions", unlocked: false, category: "progress" as const },
    { title: "Tenths Collector", description: "Unlocked after gaining 0.100s on a previous best", unlocked: true, category: "progress" as const },
    { title: "Half-Second Hero", description: "Unlocked after gaining 0.500s on a previous best", unlocked: false, category: "progress" as const },
    { title: "Second Slayer", description: "Unlocked after gaining 1.000s on a previous best", unlocked: false, category: "progress" as const },
    
    // Technique & Driving Quality
    { title: "Brake Marker", description: "Unlocked after showing stable braking points across a session", unlocked: false, category: "technique" as const },
    { title: "Late Braker", description: "Unlocked after improving braking depth without losing corner exit", unlocked: false, category: "technique" as const },
    { title: "Trail Braker", description: "Unlocked after meeting a trail braking quality threshold", unlocked: false, category: "technique" as const },
    { title: "Smooth Hands", description: "Unlocked after maintaining low steering correction input", unlocked: true, category: "technique" as const },
    { title: "Throttle Artist", description: "Unlocked after showing clean progressive throttle application", unlocked: false, category: "technique" as const },
    { title: "Early On Power", description: "Unlocked after improving average throttle pickup point", unlocked: false, category: "technique" as const },
    { title: "Apex Hunter", description: "Unlocked after repeatedly hitting optimal apex zones", unlocked: false, category: "technique" as const },
    { title: "Exit Maximizer", description: "Unlocked after improving exit speed in key corners", unlocked: false, category: "technique" as const },
    { title: "Minimum Speed Master", description: "Unlocked after improving minimum corner speed without sacrificing exit", unlocked: false, category: "technique" as const },
    { title: "Weight Transfer Wizard", description: "Unlocked after balanced brake-release and rotation metrics", unlocked: false, category: "technique" as const },
    
    // Consistency & Discipline
    { title: "Metronome", description: "Unlocked after 10 laps within a very small time spread", unlocked: false, category: "consistency" as const },
    { title: "No Excuses", description: "Unlocked after reviewing every lap in a session", unlocked: false, category: "consistency" as const },
    { title: "Repeatable Pace", description: "Unlocked after matching best-lap pace over multiple laps", unlocked: false, category: "consistency" as const },
    { title: "Zero Drama", description: "Unlocked after a whole session with no major overdriving events", unlocked: false, category: "consistency" as const },
    { title: "Precision Driver", description: "Unlocked after hitting sector targets in all sectors in one lap", unlocked: false, category: "consistency" as const },
    { title: "Discipline Over Heroics", description: "Unlocked after improving average lap, not just best lap", unlocked: false, category: "consistency" as const },
    { title: "Pressure Proof", description: "Unlocked after maintaining pace in the final third of a session", unlocked: false, category: "consistency" as const },
    { title: "One More Lap", description: "Unlocked after improving on the last lap of a stint", unlocked: false, category: "consistency" as const },
    { title: "Recovery Specialist", description: "Unlocked after bouncing back with a strong lap after a mistake", unlocked: false, category: "consistency" as const },
    { title: "Stable Platform", description: "Unlocked after showing reduced oscillation / instability metrics", unlocked: false, category: "consistency" as const },
    
    // Track Learning & Analysis
    { title: "Track Scout", description: "Unlocked after completing the first session on a new track", unlocked: true, category: "learning" as const },
    { title: "Corner Student", description: "Unlocked after reviewing every corner insight in a track report", unlocked: false, category: "learning" as const },
    { title: "Track Mapper", description: "Unlocked after completing a full reference map for a circuit", unlocked: false, category: "learning" as const },
    { title: "Reference Builder", description: "Unlocked after setting braking, turn-in, apex, and exit markers", unlocked: false, category: "learning" as const },
    { title: "Sector Surgeon", description: "Unlocked after identifying the weakest sector and improving it", unlocked: false, category: "learning" as const },
    { title: "Line Detective", description: "Unlocked after improving a corner through line adjustment", unlocked: false, category: "learning" as const },
    { title: "Telemetry Explorer", description: "Unlocked after opening telemetry overlays 10 times", unlocked: false, category: "learning" as const },
    { title: "Compare Mode", description: "Unlocked after comparing two laps for the first time", unlocked: false, category: "learning" as const },
    { title: "Theory to Track", description: "Unlocked after applying a coaching recommendation successfully", unlocked: false, category: "learning" as const },
    { title: "Lesson Locked In", description: "Unlocked after repeating an improved technique across sessions", unlocked: false, category: "learning" as const },
    
    // Endurance & Racecraft
    { title: "Stint Manager", description: "Unlocked after completing a long run with pace control", unlocked: false, category: "endurance" as const },
    { title: "Endurance Mindset", description: "Unlocked after finishing a session above a set duration threshold", unlocked: false, category: "endurance" as const },
    { title: "Tire Whisperer", description: "Unlocked after maintaining pace with low degradation", unlocked: false, category: "endurance" as const },
    { title: "Fuel Saver", description: "Unlocked after meeting a lift-and-coast or fuel target", unlocked: false, category: "endurance" as const },
    { title: "Traffic Navigator", description: "Unlocked after strong lap execution in traffic conditions", unlocked: false, category: "endurance" as const },
    { title: "Racecraft Ready", description: "Unlocked after completing a race simulation session", unlocked: false, category: "endurance" as const },
    { title: "Closer", description: "Unlocked after delivering the fastest lap in the final phase of a stint", unlocked: false, category: "endurance" as const },
    { title: "Iron Focus", description: "Unlocked after completing a long session with minimal consistency drop", unlocked: false, category: "endurance" as const },
    { title: "Team Player", description: "Unlocked after sharing session data with a coach or teammate", unlocked: false, category: "endurance" as const },
    { title: "Lap Coach Certified", description: "Unlocked after completing a full progression path in the app", unlocked: false, category: "endurance" as const },
  ];

  const earnedBadges = allBadges.filter(b => b.unlocked);

  const handleDownload = () => {
    toast.success("Session card downloaded successfully!");
  };

  const handleShare = () => {
    toast.success("Share link copied to clipboard!");
  };

  return (
    <div className="min-h-screen bg-[#000000] text-[#F0EDE5]">
      {/* Header */}
      <div className="border-b border-[rgba(240,237,229,0.08)]">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
          <div className="flex items-center gap-4 mb-6">
            {/* LAP Logo placeholder */}
            <div className="text-4xl font-bold tracking-tight">
              <span className="text-[#F0EDE5]">LAP</span>
              <span className="text-[#949494] ml-1 text-2xl">COACH</span>
            </div>
          </div>
          
          <div className="text-sm text-[#949494] uppercase tracking-[0.2em]">
            Driver Achievement System
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="max-w-7xl mx-auto px-4 md:px-8 py-12">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-8">
          <TabsList className="grid w-full grid-cols-5 max-w-3xl mx-auto bg-[#141414] border border-[rgba(240,237,229,0.08)]">
            <TabsTrigger 
              value="profile"
              className="data-[state=active]:bg-[#C9A84C] data-[state=active]:text-[#000000] uppercase tracking-wider text-xs"
            >
              <User className="h-4 w-4 mr-2" />
              Profile
            </TabsTrigger>
            <TabsTrigger 
              value="badges"
              className="data-[state=active]:bg-[#C9A84C] data-[state=active]:text-[#000000] uppercase tracking-wider text-xs"
            >
              <Trophy className="h-4 w-4 mr-2" />
              Badges
            </TabsTrigger>
            <TabsTrigger 
              value="share"
              className="data-[state=active]:bg-[#C9A84C] data-[state=active]:text-[#000000] uppercase tracking-wider text-xs"
            >
              <Share2 className="h-4 w-4 mr-2" />
              Share
            </TabsTrigger>
            <TabsTrigger 
              value="rewards"
              className="data-[state=active]:bg-[#C9A84C] data-[state=active]:text-[#000000] uppercase tracking-wider text-xs"
            >
              <Sparkles className="h-4 w-4 mr-2" />
              Rewards
            </TabsTrigger>
            <TabsTrigger 
              value="brand"
              className="data-[state=active]:bg-[#C9A84C] data-[state=active]:text-[#000000] uppercase tracking-wider text-xs"
            >
              <Palette className="h-4 w-4 mr-2" />
              Brand
            </TabsTrigger>
          </TabsList>

          {/* Profile Tab */}
          <TabsContent value="profile" className="space-y-6">
            <div className="text-center space-y-2 mb-8">
              <h2 className="text-3xl font-bold text-[#F0EDE5]">Driver Profile</h2>
              <p className="text-[#949494]">
                Session performance and achievements
              </p>
            </div>

            <div className="max-w-5xl mx-auto">
              <DriverProfileCard {...driverData} badges={earnedBadges} />
            </div>
          </TabsContent>

          {/* Badges Tab */}
          <TabsContent value="badges" className="space-y-6">
            <div className="text-center space-y-2 mb-8">
              <h2 className="text-3xl font-bold text-[#F0EDE5]">Achievement Badges</h2>
              <p className="text-[#949494]">
                {earnedBadges.length} / {allBadges.length} unlocked
              </p>
              
              {/* Progress bar */}
              <div className="max-w-md mx-auto mt-4">
                <div className="h-2 bg-[#141414] rounded-full overflow-hidden border border-[rgba(240,237,229,0.08)]">
                  <div 
                    className="h-full bg-gradient-to-r from-[#C9A84C] to-[#22C55E] transition-all duration-500"
                    style={{ width: `${(earnedBadges.length / allBadges.length) * 100}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Badge categories */}
            <div className="space-y-10">
              {["progress", "technique", "consistency", "learning", "endurance"].map((category) => {
                const categoryBadges = allBadges.filter(b => b.category === category);
                const categoryNames = {
                  progress: "Progress & Milestones",
                  technique: "Technique & Driving Quality",
                  consistency: "Consistency & Discipline",
                  learning: "Track Learning & Analysis",
                  endurance: "Endurance & Racecraft"
                };

                return (
                  <div key={category}>
                    <h3 className="text-xl font-bold text-[#F0EDE5] mb-6 uppercase tracking-wide">
                      {categoryNames[category as keyof typeof categoryNames]}
                    </h3>
                    <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-6">
                      {categoryBadges.map((badge, index) => (
                        <RacingBadge key={index} {...badge} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </TabsContent>

          {/* Share Tab */}
          <TabsContent value="share" className="space-y-6">
            <div className="text-center space-y-2 mb-8">
              <h2 className="text-3xl font-bold text-[#F0EDE5]">Share Your Session</h2>
              <p className="text-[#949494]">
                Download or share your performance card
              </p>
            </div>

            <div className="flex justify-center">
              <ShareableCard
                {...driverData}
                badges={earnedBadges}
                onDownload={handleDownload}
                onShare={handleShare}
              />
            </div>
          </TabsContent>

          {/* Rewards Tab */}
          <TabsContent value="rewards" className="space-y-6">
            <div className="text-center space-y-2 mb-10">
              <p
                className="text-[10px] uppercase tracking-[0.18em] text-[#C9A84C] mb-2"
                style={{ fontFamily: "'Space Mono', monospace" }}
              >
                Reward System
              </p>
              <h2 className="text-3xl font-bold text-[#F0EDE5] uppercase tracking-tight">Reward States</h2>
              <p className="text-sm text-[#949494] max-w-md mx-auto">
                Interactive previews of achievement overlays, level-up transitions, and toast notifications
              </p>
            </div>

            <div className="max-w-3xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-5">
              {/* Achievement Unlock Card */}
              {([
                {
                  accent: "#C9A84C",
                  label: "Achievement Unlock",
                  title: "Full-Screen Overlay",
                  desc: "Gold-tier badge reveal with dashed hexagonal frame and animated entry",
                  onClick: () => setShowAchievement(true),
                  icon: (
                    <svg viewBox="0 0 40 44" className="w-full h-full">
                      <path d="M20 2 L37 11 L37 33 L20 42 L3 33 L3 11 Z" fill="#C9A84C08" stroke="#C9A84C" strokeWidth="1" strokeDasharray="6 4" opacity="0.5" />
                      <g transform="translate(12, 13)" opacity="0.8">
                        <path d="M4 3.5v2.5a2 2 0 004 0V3.5H4z" fill="#C9A84C" opacity="0.2" />
                        <path d="M3 1l1 2.5h4l1-2.5" stroke="#C9A84C" strokeWidth="0.8" fill="none" strokeLinejoin="round" />
                        <path d="M4 3.5v2.5a2 2 0 004 0V3.5" stroke="#C9A84C" strokeWidth="0.8" fill="none" />
                        <path d="M5 8.5v1h2v-1" stroke="#C9A84C" strokeWidth="0.8" fill="none" />
                        <path d="M4 10.5h4" stroke="#C9A84C" strokeWidth="0.8" strokeLinecap="round" fill="none" />
                      </g>
                    </svg>
                  ),
                },
                {
                  accent: "#22C55E",
                  label: "Level-Up Modal",
                  title: "Level Transition",
                  desc: "Circular gauge arc with animated level 5 → 6 and telemetry stats row",
                  onClick: () => setShowLevelUp(true),
                  icon: (
                    <svg viewBox="0 0 40 44" className="w-full h-full">
                      <circle cx="20" cy="22" r="16" fill="none" stroke="#22C55E" strokeWidth="1" strokeDasharray="5 3" opacity="0.4" />
                      <circle cx="20" cy="22" r="11" fill="#22C55E08" stroke="#22C55E" strokeWidth="0.8" opacity="0.3" />
                      <path d="M16 22L19 25L25 19" stroke="#22C55E" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.8" fill="none" />
                    </svg>
                  ),
                },
                {
                  accent: "#C9A84C",
                  label: "Achievement Toast",
                  title: "Corner Notification",
                  desc: "Slide-in toast with Pit Orange accent bar and hexagonal mini badge",
                  onClick: () => setShowToast(true),
                  icon: (
                    <svg viewBox="0 0 40 44" className="w-full h-full">
                      <rect x="4" y="8" width="32" height="28" rx="4" fill="#C9A84C06" stroke="#C9A84C" strokeWidth="0.8" strokeDasharray="5 3" opacity="0.4" />
                      <line x1="4" y1="12" x2="36" y2="12" stroke="#C9A84C" strokeWidth="1" opacity="0.5" />
                      <rect x="8" y="16" width="16" height="2" rx="1" fill="#C9A84C" opacity="0.25" />
                      <rect x="8" y="21" width="24" height="1.5" rx="0.75" fill="#C9A84C" opacity="0.12" />
                      <rect x="8" y="25" width="20" height="1.5" rx="0.75" fill="#C9A84C" opacity="0.08" />
                    </svg>
                  ),
                },
              ] as const).map((card) => (
                <button
                  key={card.label}
                  onClick={card.onClick}
                  className="group relative rounded-[22px] p-6 text-left cursor-pointer transition-all duration-200 hover:translate-y-[-2px]"
                  style={{
                    background: "#141414",
                    border: "1px solid rgba(240,237,229,0.06)",
                  }}
                >
                  {/* Top accent line */}
                  <div
                    className="absolute top-0 left-6 right-6 h-[1px] rounded-full"
                    style={{ background: `linear-gradient(90deg, transparent, ${card.accent}40, transparent)` }}
                  />

                  {/* Corner dots */}
                  <div className="absolute top-3 right-4 flex gap-[2px] opacity-15">
                    {[...Array(3)].map((_, i) => (
                      <div key={i} className="w-[2px] h-[2px] rounded-[0.5px]" style={{ backgroundColor: card.accent }} />
                    ))}
                  </div>

                  {/* Icon */}
                  <div className="w-10 h-11 mb-5 transition-transform duration-200 group-hover:scale-110">
                    {card.icon}
                  </div>

                  {/* Label */}
                  <p
                    className="text-[9px] uppercase tracking-[0.15em] mb-1.5"
                    style={{ color: card.accent, fontFamily: "'Space Mono', monospace" }}
                  >
                    {card.label}
                  </p>

                  {/* Title */}
                  <p className="text-[15px] font-bold text-[#F0EDE5] uppercase tracking-tight mb-2">
                    {card.title}
                  </p>

                  {/* Description */}
                  <p className="text-[11px] text-[#949494] leading-relaxed">
                    {card.desc}
                  </p>

                  {/* Bottom trigger hint */}
                  <div className="mt-4 flex items-center gap-2">
                    <div className="h-[1px] flex-1" style={{ background: `linear-gradient(90deg, ${card.accent}15, transparent)` }} />
                    <span
                      className="text-[7px] uppercase tracking-[0.2em] opacity-30 group-hover:opacity-60 transition-opacity"
                      style={{ color: card.accent, fontFamily: "'Space Mono', monospace" }}
                    >
                      Click to preview
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </TabsContent>

          {/* Brand Tab */}
          <TabsContent value="brand" className="space-y-6">
            <BrandGuide />
          </TabsContent>
        </Tabs>
      </div>

      {/* Reward State Overlays */}
      <AchievementUnlockOverlay
        open={showAchievement}
        onClose={() => setShowAchievement(false)}
        badgeName="Telemetry Prodigy"
        description="Unlock after stacking pace, consistency, and execution gains in one session."
        tier="gold"
      />

      <LevelUpModal
        open={showLevelUp}
        onClose={() => setShowLevelUp(false)}
        previousLevel={5}
        newLevel={6}
        totalXP={1640}
      />

      <AchievementToast
        open={showToast}
        onClose={() => setShowToast(false)}
        badgeName="Precision Attack"
        description="Three execution gains in a row without a single invalid lap."
      />

      {/* Footer */}
      <div className="border-t border-[rgba(240,237,229,0.08)] mt-20">
        <div className="max-w-7xl mx-auto px-4 md:px-8 py-8">
          <div className="text-center text-[#949494] text-sm tracking-[0.2em] uppercase">
            LAP Coach Racing • Achievement System
          </div>
        </div>
      </div>
    </div>
  );
}