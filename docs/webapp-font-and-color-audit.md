# Webapp Font And Color Audit

## Scope

This audit covers the active web frontend in `lap-website`.

Included:
- `lap-website/src`
- `lap-website/tailwind.config.ts`
- active legacy canvas/chart modules in `lap-website/public/js` referenced by `useVanillaChart`
- `lap-website/public/icon.svg`

Excluded:
- tests
- generated build output

Note:
- `lap-website/src/app/fonts/GeistVF.woff` and `GeistMonoVF.woff` exist, but I found no runtime references to them.

## Fonts

### Primary loaded web fonts

These are the only external web fonts explicitly loaded in the root layout:

| Role | Family | Weights | Source |
| --- | --- | --- | --- |
| Display | `Space Grotesk` | `600`, `700` | `src/app/layout.tsx` |
| Body | `Inter` | `400`, `500` | `src/app/layout.tsx` |
| Mono / telemetry | `Space Mono` | `400` | `src/app/layout.tsx` |

### Canonical font stacks

Defined in `src/styles/tokens.css`, mirrored in `src/lib/tokens.ts`, `src/tokens/typography.ts`, and exposed through Tailwind:

| Token | Exact stack |
| --- | --- |
| `--font-display` | `"Space Grotesk", "Arial Black", sans-serif` |
| `--font-body` | `"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` |
| `--font-mono` | `"Space Mono", "Fira Code", "Courier New", monospace` |

Tailwind aliases:
- `font-monument` -> `var(--font-display)`
- `font-body` -> `var(--font-body)`
- `font-telemetry` -> `var(--font-mono)`

### Additional runtime font families referenced in code

These appear in canvas drawing code, SVG assets, or legacy public JS:

| Family | Where it appears |
| --- | --- |
| `Arial Black` | display fallback, `public/icon.svg` |
| `IBM Plex Mono` | compare tools and some chart canvases |
| `JetBrains Mono` | several custom chart canvases |
| `Monument Extended` | `src/components/shared/charts/GGExplorer.tsx` |
| `Segoe UI` | share card canvas and body fallback stack |
| `-apple-system` | multiple chart canvases and public JS modules |
| `BlinkMacSystemFont` | body fallback stack and legacy canvas code |
| `system-ui` | public JS chart modules and share card canvas |
| `Fira Code` | mono fallback stack |
| `Courier New` | mono fallback stack |

### Exact unique font family names found

Static named font families/fallback families referenced in the runtime code:

- `Space Grotesk`
- `Space Mono`
- `Inter`
- `Arial Black`
- `IBM Plex Mono`
- `JetBrains Mono`
- `Monument Extended`
- `Segoe UI`
- `Fira Code`
- `Courier New`
- `-apple-system`
- `BlinkMacSystemFont`
- `system-ui`
- generic `sans-serif`
- generic `monospace`

## Colors

This frontend currently has three overlapping color systems:

1. Core CSS/Tailwind design tokens in `src/styles/tokens.css`
2. JS token mirrors and accessibility palettes in `src/lib`
3. Legacy chart/theme palettes in `public/js`

### Core design tokens

These are the canonical named color tokens used by the main Next.js UI:

| Token | Exact value | Notes |
| --- | --- | --- |
| `--asphalt` | `#000000` | primary background |
| `--concrete` | `#141414` | secondary surface |
| `--chalk` | `#F0EDE5` | primary light text |
| `--steel` | `#949494` | secondary text / borders in CSS |
| `--text-muted` | `#9CA3AF` | muted copy |
| `--acid-green` | `#22C55E` | success / positive accent |
| `--safety-red` | `#FF2A2A` | destructive / error |
| `--marshal-yellow` | `#FACC15` | warning / caution |
| `--pit-orange` | `#C9A84C` | brand / premium accent |
| `--racing-purple` | `#8B5CF6` | informational accent |

Semantic aliases:

| Alias | Exact value |
| --- | --- |
| `--color-success` | `var(--acid-green)` |
| `--color-warning` | `var(--marshal-yellow)` |
| `--color-error` | `var(--safety-red)` |
| `--color-info` | `var(--racing-purple)` |
| `--color-brand` | `var(--pit-orange)` |

Chart palette tokens:

| Token | Exact value |
| --- | --- |
| `--chart-series-1` | `#22C55E` |
| `--chart-series-2` | `#3B82F6` |
| `--chart-series-3` | `#F59E0B` |
| `--chart-series-4` | `#EF4444` |
| `--chart-series-5` | `#A78BFA` |
| `--chart-series-6` | `#EC4899` |
| `--chart-reference` | `rgba(240, 237, 229, 0.3)` |

Tailwind color aliases:
- `asphalt`, `concrete`, `chalk`, `steel`
- `acid-green`, `safety-red`, `marshal-yellow`, `pit-orange`, `racing-purple`
- `gold` -> `var(--pit-orange)`
- `success`, `warning`, `error`, `info`, `brand`

### Important discrepancy

There is a real token mismatch in the repo:

- CSS token `--steel` is `#949494` in `src/styles/tokens.css`
- JS token `colors.steel` is `#888888` in `src/lib/tokens.ts`
- OG templates also use `#888888` for subtitle text in `src/lib/og-templates.ts`

If you want one exact "steel" value across the app, this needs cleanup.

### High-contrast overrides

Defined both in `@media (prefers-contrast: more)` and `.high-contrast`:

| Token | Exact value |
| --- | --- |
| `--asphalt` | `#000000` |
| `--concrete` | `#0A0A0A` |
| `--chalk` | `#FFFFFF` |
| `--steel` | `#D4D4D4` |
| `--text-muted` | `#BBBBBB` |
| `--acid-green` | `#00FF66` |
| `--safety-red` | `#FF3333` |
| `--marshal-yellow` | `#FFE033` |
| `--border-color-default` | `rgba(255, 255, 255, 0.4)` |
| `--border-color-muted` | `rgba(255, 255, 255, 0.25)` |
| `--chart-reference` | `rgba(255, 255, 255, 0.5)` |

### Print-only overrides

Defined in `src/app/globals.css`:

| Use | Exact value |
| --- | --- |
| page background | `#fff` |
| page text | `#000` |
| card background | `#fafafa` |
| print border | `#ddd` |
| muted print text | `#555` |
| success print text | `#16a34a` |
| error print text | `#dc2626` |
| brand print text | `#a3660a` |
| asphalt print background | `#eee` |

### Accessibility / alternate palettes

Color-blind palette in `src/lib/color-semantics.ts`:

| Semantic role | Exact value |
| --- | --- |
| success | `#2563EB` |
| warning | `#F59E0B` |
| error | `#DC2626` |
| info | `#7C3AED` |
| brand | `#C9A84C` |

Color-blind chart palette:
- `#2563EB`
- `#F59E0B`
- `#7C3AED`
- `#DC2626`
- `#06B6D4`
- `#EC4899`

### Legacy public chart theme defaults

`public/js/theme.js` still defines a separate palette used by legacy canvas modules:

| Group | Exact values |
| --- | --- |
| backgrounds | `#0d1117`, `#161b22`, `#1c2333`, `#1a1f2e`, `#21273a` |
| text | `#e6edf3`, `#9CA3AF`, `#6B7280` |
| accent | `#ff6b35`, `#cc5529` |
| status | `#3fb950`, `#238636`, `#d29922`, `#f85149`, `#58a6ff`, `#bc8cff` |
| borders | `#30363d`, `#21262d` |

That same file also ships multiple chart theme presets:
- `default`
- `neon`
- `pastel`
- `highContrast`
- `colorblind`

Those presets introduce many extra runtime colors beyond the core token system.

### Additional hard-coded colors actually used in app features

These are not the canonical tokens, but they are referenced directly in runtime components:

Session / analytics accents:
- `#B6FF2E`
- `#FFD400`
- `#00d4ff`
- `#D946EF`
- `#FF6A00`
- `#3ddc84`
- `#ff8c00`
- `#a3e635`

Chart neutrals and surfaces:
- `#0B0C0F`
- `#0f1117`
- `#1a1a2e`
- `#1a1f2e`
- `#30363d`
- `#8b949e`
- `#e6edf3`
- `#e0e0e0`
- `#F3F0E8`
- `#c4c4c4`
- `#6e7681`
- `#555`
- `#333`
- `#444`

Common chart/data-series colors:
- `#3b82f6`
- `#22d3ee`
- `#f97316`
- `#ef4444`
- `#10b981`
- `#a78bfa`
- `#ec4899`
- `#58a6ff`
- `#d29922`
- `#9ca3af`
- `#4488ff`
- `#44ddff`
- `#44ff88`
- `#ff8844`
- `#ff44ff`
- `#ffff44`

Brand / badge / auth / third-party:
- `#C9A84C`
- `#D4B35A`
- `#4285F4`
- `#34A853`
- `#FBBC05`
- `#EA4335`

Metal / achievement / misc:
- `#C0C0C0`
- `#CD7F32`
- `#231f20`

### Dynamic/generated colors

These are computed at runtime rather than stored as one fixed literal list:

- `hsl(${hue}, 70%, 40%)` in `src/components/shared/charts/SectorPanel.tsx`
- `rgba(240, 237, 229, ${gridAlpha})` in `src/components/shared/charts/TrackMap.tsx`
- `heatColor(t)` in `public/js/theme.js` interpolates from green to yellow to red
- `speedColor(t)` in `public/js/theme.js` interpolates from blue to green to orange

## Exact unique static values found

This section lists the exact named/static values found in the runtime source. It is intentionally raw.

### Exact unique font-family names found

```text
-apple-system
Arial Black
BlinkMacSystemFont
Courier New
Fira Code
IBM Plex Mono
Inter
JetBrains Mono
Monument Extended
Segoe UI
Space Grotesk
Space Mono
system-ui
```

### Exact representative static color literals found

Core token and app-level literals:

```text
#000000
#141414
#F0EDE5
#949494
#9CA3AF
#22C55E
#FF2A2A
#FACC15
#C9A84C
#8B5CF6
#3B82F6
#F59E0B
#EF4444
#A78BFA
#EC4899
#0A0A0A
#FFFFFF
#D4D4D4
#BBBBBB
#00FF66
#FF3333
#FFE033
```

Legacy/public theme literals:

```text
#0d1117
#161b22
#1c2333
#1a1f2e
#21273a
#e6edf3
#6B7280
#ff6b35
#cc5529
#3fb950
#238636
#f85149
#58a6ff
#bc8cff
#30363d
#21262d
```

Frequently repeated extra feature/chart literals:

```text
#B6FF2E
#FFD400
#00d4ff
#D946EF
#FF6A00
#3ddc84
#ff8c00
#a3e635
#0B0C0F
#0f1117
#1a1a2e
#8b949e
#e0e0e0
#F3F0E8
#c4c4c4
#6e7681
#555
#333
#444
#22d3ee
#10b981
#f97316
#9ca3af
#4488ff
#44ddff
#44ff88
#ff8844
#ff44ff
#ffff44
#4285F4
#34A853
#FBBC05
#EA4335
#C0C0C0
#CD7F32
#231f20
```

Representative RGBA literals:

```text
rgba(240, 237, 229, 0.3)
rgba(255, 255, 255, 0.4)
rgba(255, 255, 255, 0.25)
rgba(255, 255, 255, 0.5)
rgba(201, 168, 76, 0.04)
rgba(201, 168, 76, 0.6)
rgba(201, 168, 76, 0.8)
rgba(136, 136, 136, 0.1)
rgba(136, 136, 136, 0.2)
rgba(255,255,255,0.06)
rgba(255,255,255,0.08)
rgba(255,255,255,0.15)
rgba(255,255,255,0.3)
rgba(255,255,255,0.4)
rgba(255,255,255,0.5)
rgba(255,255,255,0.6)
rgba(255,255,255,0.7)
rgba(239,68,68,0.08)
rgba(239,68,68,0.4)
rgba(239,68,68,0.5)
rgba(16, 185, 129, 0.25)
rgba(61,220,132,0.3)
rgba(255,140,0,0.6)
rgba(255,214,0,0.4)
rgba(0,0,0,0.85)
rgba(0, 0, 0, 0.96)
```

## Files used for this audit

- `lap-website/src/app/layout.tsx`
- `lap-website/src/app/globals.css`
- `lap-website/src/styles/tokens.css`
- `lap-website/tailwind.config.ts`
- `lap-website/src/lib/tokens.ts`
- `lap-website/src/lib/color-semantics.ts`
- `lap-website/src/lib/og-templates.ts`
- `lap-website/src/tokens/typography.ts`
- `lap-website/public/js/theme.js`
- `lap-website/public/icon.svg`
- selected runtime chart/canvas files in `lap-website/src/components/**` and `lap-website/public/js/**`
