import svgPaths from "../../imports/svg-zpcr1lt0nh";

/* ── Charter palette ── */
const PALETTE = [
  { name: "Asphalt Black", hex: "#000000" },
  { name: "Concrete", hex: "#141414" },
  { name: "Steel", hex: "#949494" },
  { name: "Chalk", hex: "#F0EDE5" },
  { name: "Pit Orange", hex: "#C9A84C" },
  { name: "Safety Red", hex: "#FF2A2A" },
  { name: "Acid Green", hex: "#22C55E" },
  { name: "Marshal Yellow", hex: "#FACC15" },
  { name: "Racing Purple", hex: "#8B5CF6" },
];

/* ── Reusable LAP monogram SVG ── */
function LapSymbol({ size = 56, color = "#F0EDE5" }: { size?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 200 200" fill="none">
      <path d={svgPaths.p26682100} fill={color} />
      <path d={svgPaths.p336367c0} fill={color} />
    </svg>
  );
}

/* ── Section wrapper ── */
function Section({ label, title, children }: { label: string; title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      <div>
        <p
          className="text-[11px] uppercase tracking-[0.12em] text-[#C9A84C] mb-1"
          style={{ fontFamily: "'Space Mono', monospace" }}
        >
          {label}
        </p>
        <h3 className="text-xl font-bold text-[#F0EDE5] uppercase tracking-tight">
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}

export function BrandGuide() {
  return (
    <div className="space-y-16">
      {/* ═══════════════════════════════════
          HERO — Monogram
      ═══════════════════════════════════ */}
      <div className="flex flex-col items-center text-center space-y-8">
        {/* Glow backdrop */}
        <div className="relative">
          <div
            className="absolute inset-0 rounded-full blur-[80px] opacity-10"
            style={{ background: "#C9A84C", width: 300, height: 300, left: -75, top: -75 }}
          />
          <LapSymbol size={150} color="#F0EDE5" />
        </div>
        <div>
          <p
            className="text-[10px] uppercase tracking-[0.35em] text-[#949494] mb-3"
            style={{ fontFamily: "'Roboto Mono', 'Space Mono', monospace" }}
          >
            The Precision Monogram
          </p>
        </div>
      </div>

      {/* ═══════════════════════════════════
          DESIGN PHILOSOPHY
      ═══════════════════════════════════ */}
      <div
        className="rounded-[28px] p-8 border"
        style={{
          background: "#141414",
          borderColor: "rgba(240,237,229,0.06)",
        }}
      >
        <div className="flex flex-col lg:flex-row gap-12 items-start">
          {/* Left: tagline + description */}
          <div className="flex-1 space-y-6">
            <div className="flex items-center gap-4 mb-2">
              <LapSymbol size={40} color="#C9A84C" />
            </div>
            <div>
              <p className="text-3xl font-bold text-[#F0EDE5] tracking-tight">
                Brutalist geometry.
              </p>
              <p className="text-3xl font-bold text-[#949494] tracking-tight">
                Surgical intent.
              </p>
            </div>
            <p className="text-[#949494] text-sm leading-relaxed max-w-lg">
              The monogram reduces a racing corner to its elemental state — a single entry plane,
              a sweeping apex arc, and a clean exit. The large outer radius captures the momentum
              and g-forces of a committed turn; the tight inner cutback encodes precise weight transfer.
            </p>
            <p className="text-[#949494] text-sm leading-relaxed max-w-lg">
              The solitary dot sits at the mathematical apex — the point of absolute commitment
              where data becomes instinct.
            </p>
          </div>

          {/* Right: logo on dark bg */}
          <div className="flex items-center justify-center w-full lg:w-[320px] aspect-square bg-black rounded-2xl border border-[rgba(240,237,229,0.06)]">
            <LapSymbol size={200} color="#F0EDE5" />
          </div>
        </div>
      </div>

      {/* ═══════════════════════════════════
          LOGO VARIATIONS
      ═══════════════════════════════════ */}
      <Section label="Identity" title="Logo variations & lockups">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {/* Symbol only – light on dark */}
          <div className="flex flex-col items-center justify-center aspect-square bg-black rounded-2xl border border-[rgba(240,237,229,0.06)] p-6">
            <LapSymbol size={64} color="#F0EDE5" />
            <p className="text-[8px] text-[#949494] uppercase tracking-[0.2em] mt-4" style={{ fontFamily: "'Space Mono', monospace" }}>
              Symbol — Light
            </p>
          </div>

          {/* Symbol only – dark on light */}
          <div className="flex flex-col items-center justify-center aspect-square bg-[#F0EDE5] rounded-2xl p-6">
            <LapSymbol size={64} color="#000000" />
            <p className="text-[8px] text-[#949494] uppercase tracking-[0.2em] mt-4" style={{ fontFamily: "'Space Mono', monospace" }}>
              Symbol — Dark
            </p>
          </div>

          {/* Symbol + LAP */}
          <div className="flex flex-col items-center justify-center aspect-square bg-black rounded-2xl border border-[rgba(240,237,229,0.06)] p-6 gap-3">
            <div className="flex items-center gap-3">
              <LapSymbol size={32} color="#F0EDE5" />
              <span className="text-[#F0EDE5] text-2xl font-bold uppercase tracking-wider">LAP</span>
            </div>
            <p className="text-[8px] text-[#949494] uppercase tracking-[0.2em] mt-2" style={{ fontFamily: "'Space Mono', monospace" }}>
              Wordmark
            </p>
          </div>

          {/* Full lockup */}
          <div className="flex flex-col items-center justify-center aspect-square bg-black rounded-2xl border border-[rgba(240,237,229,0.06)] p-6 gap-3">
            <div className="flex items-center gap-3">
              <LapSymbol size={28} color="#F0EDE5" />
              <div>
                <span className="text-[#F0EDE5] text-lg font-bold uppercase tracking-wider block leading-none">LAP</span>
                <span className="text-[#949494] text-[10px] uppercase tracking-[0.3em] block">Coach</span>
              </div>
            </div>
            <p className="text-[8px] text-[#949494] uppercase tracking-[0.2em] mt-2" style={{ fontFamily: "'Space Mono', monospace" }}>
              Full Lockup
            </p>
          </div>
        </div>
      </Section>

      {/* ═══════════════════════════════════
          COLOR PALETTE
      ═══════════════════════════════════ */}
      <Section label="Charte Graphique" title="Racing color palette">
        <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-9 gap-3">
          {PALETTE.map((c) => (
            <div key={c.hex} className="space-y-2">
              <div
                className="aspect-square rounded-xl border"
                style={{
                  backgroundColor: c.hex,
                  borderColor: c.hex === "#000000" ? "rgba(240,237,229,0.1)" : "transparent",
                }}
              />
              <div>
                <p className="text-[9px] text-[#F0EDE5] uppercase tracking-wider" style={{ fontFamily: "'Space Mono', monospace" }}>
                  {c.name}
                </p>
                <p className="text-[9px] text-[#949494] uppercase" style={{ fontFamily: "'Space Mono', monospace" }}>
                  {c.hex}
                </p>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* ═══════════════════════════════════
          TYPOGRAPHY
      ═══════════════════════════════════ */}
      <Section label="Type System" title="Racing typography">
        <div
          className="rounded-2xl p-8 border space-y-10"
          style={{
            background: "#141414",
            borderColor: "rgba(240,237,229,0.06)",
          }}
        >
          {/* Display heading */}
          <div className="space-y-1">
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em] mb-2" style={{ fontFamily: "'Space Mono', monospace" }}>
              Display
            </p>
            <p className="text-6xl font-bold text-[#F0EDE5] uppercase tracking-tighter">
              LAP COACH
            </p>
          </div>

          {/* Racing weight comparison */}
          <div className="space-y-1">
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em] mb-2" style={{ fontFamily: "'Space Mono', monospace" }}>
              Weight Contrast
            </p>
            <div className="flex gap-12">
              <p className="text-3xl text-[#F0EDE5] uppercase tracking-wider" style={{ fontWeight: 400 }}>
                RACING
              </p>
              <p className="text-3xl font-bold text-[#F0EDE5] uppercase tracking-wider">
                RACING
              </p>
            </div>
          </div>

          {/* Alphabet */}
          <div className="space-y-3">
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em]" style={{ fontFamily: "'Space Mono', monospace" }}>
              Character Set
            </p>
            <div className="space-y-1">
              <p className="text-lg text-[#F0EDE5] uppercase tracking-[0.3em]">
                A B C D E F G H I J K L M
              </p>
              <p className="text-lg text-[#F0EDE5] uppercase tracking-[0.3em]">
                N O P Q R S T U V W X Y Z
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-lg text-[#C9A84C] uppercase tracking-[0.3em]" style={{ fontFamily: "'Space Mono', monospace" }}>
                0 1 2 3 4 5 6 7 8 9
              </p>
            </div>
          </div>

          {/* Size scale */}
          <div className="space-y-3">
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em]" style={{ fontFamily: "'Space Mono', monospace" }}>
              Scale
            </p>
            <div className="space-y-1">
              {[
                { size: "text-5xl", label: "48px" },
                { size: "text-3xl", label: "30px" },
                { size: "text-xl", label: "20px" },
                { size: "text-sm", label: "14px" },
              ].map((s) => (
                <div key={s.label} className="flex items-baseline gap-4">
                  <p className={`${s.size} font-bold text-[#F0EDE5] uppercase tracking-tight`}>
                    LAP COACH
                  </p>
                  <span className="text-[8px] text-[#949494] uppercase tracking-wider" style={{ fontFamily: "'Space Mono', monospace" }}>
                    {s.label}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* ═══════════════════════════════════
          TELEMETRY / TIMING DISPLAY
      ═══════════════════════════════════ */}
      <Section label="Data Display" title="Leaderboard & timing elements">
        <div
          className="rounded-2xl p-8 border space-y-8"
          style={{
            background: "#141414",
            borderColor: "rgba(240,237,229,0.06)",
          }}
        >
          {/* Leaderboard rows */}
          <div className="space-y-3 max-w-sm">
            {[
              { pos: "P1", name: "BEST LAP RK", time: "1:42.873", color: "#22C55E" },
              { pos: "P2", name: "DANIEL.T06", time: "+0.214", color: "#C9A84C" },
              { pos: "P3", name: "MARC_B", time: "+0.571", color: "#949494" },
            ].map((row) => (
              <div key={row.pos} className="flex items-center gap-4">
                <span
                  className="text-xs font-bold uppercase w-8"
                  style={{ color: row.color, fontFamily: "'Space Mono', monospace" }}
                >
                  {row.pos}
                </span>
                <span className="text-xs text-[#949494] flex-1 uppercase tracking-wider" style={{ fontFamily: "'Space Mono', monospace" }}>
                  {row.name}
                </span>
                <span
                  className="text-sm font-bold"
                  style={{ color: row.color, fontFamily: "'Space Mono', monospace" }}
                >
                  {row.time}
                </span>
              </div>
            ))}
          </div>

          {/* Large time display */}
          <div>
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em] mb-2" style={{ fontFamily: "'Space Mono', monospace" }}>
              Timing Display
            </p>
            <p
              className="text-6xl font-bold text-[#F0EDE5] tracking-tight"
              style={{ fontFamily: "'Space Mono', monospace" }}
            >
              1:42.873
            </p>
          </div>

          {/* Speed badges */}
          <div>
            <p className="text-[9px] text-[#C9A84C] uppercase tracking-[0.2em] mb-3" style={{ fontFamily: "'Space Mono', monospace" }}>
              Status Badges
            </p>
            <div className="flex flex-wrap gap-3">
              {[
                { label: "SPEED", bg: "#22C55E", text: "#000000" },
                { label: "SPEED", bg: "#FACC15", text: "#000000" },
                { label: "SPEED", bg: "#C9A84C", text: "#000000" },
                { label: "SPEED", bg: "#FF2A2A", text: "#F0EDE5" },
                { label: "SPEED", bg: "#8B5CF6", text: "#F0EDE5" },
                { label: "SPEED", bg: "#949494", text: "#000000" },
              ].map((badge, i) => (
                <span
                  key={i}
                  className="px-4 py-1.5 rounded text-xs font-bold uppercase tracking-wider"
                  style={{
                    backgroundColor: badge.bg,
                    color: badge.text,
                    fontFamily: "'Space Mono', monospace",
                  }}
                >
                  {badge.label}
                </span>
              ))}
            </div>
          </div>
        </div>
      </Section>
    </div>
  );
}
