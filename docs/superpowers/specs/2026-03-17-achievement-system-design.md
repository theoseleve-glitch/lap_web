# Achievement System — Design Spec

## Visual Direction
Hybrid Racing Game + Telemetry Precision. Hexagonal SVG badges with tier-colored gradients (gold/silver/bronze), particle bursts on unlock, glow pulses, elastic bounce animations. Dark theme matching existing palette (asphalt/concrete/chalk/acid-green/pit-orange).

## Surfaces

### 1. Badge Unlock Popup
- Full-screen overlay with dark backdrop (88% opacity)
- Particle burst: 30 colored dots explode from center
- Hex badge: stroke-dasharray draw animation → badge scales in with elastic bounce
- Ring expand: 3 concentric rings pulse outward behind badge
- Glow pulse: radial gradient behind badge, pulses 2s infinite
- Text reveals: staggered — "Achievement Unlocked" → title → description → tier dots → progress bar
- Tier dots: bronze/silver/gold with active glow on current
- Dismiss: click backdrop or "Continue" button

### 2. Trophy Cabinet (Driver Profile → Achievements Tab)
- Stats bar: Earned count (acid-green), Gold count (gold), Locked count (grey)
- Badge grid: responsive, each cell has hex SVG + name + tier label
- Earned badges: full color with tier border glow on hover (scale 1.08)
- Locked badges: greyed out, lock icon, "???" name, 35% opacity
- Click earned badge → shows detail card (criteria, date earned, session link)

### 3. Shareable Session Card (1200x630 OG ratio)
- Canvas-rendered PNG, downloadable
- Dark gradient background with corner accent glow
- Top: branding ("Lap Coach Racing") + session title + track + date
- Top-right: grade badge (B/A/A+ etc)
- Middle: key stats — best lap, score/100, laps, CV%
- Bottom: mini hex badges earned this session + "lap-coach.racing" branding
- Generated server-side or client-side via canvas toBlob

### 4. Licence Progression (Career Ladder)
- 6 tiers: Rookie → Club → National → Pro → Elite → Legend
- Each has unique color: grey → acid-green → cyan → purple → gold → red
- Current licence card: gradient border matching tier color, large letter badge
- Progress bar to next tier with dual criteria (laps + score)
- Ladder strip: all 6 tiers, current highlighted, locked ones dimmed

### 5. Level-Up Animation
- Licence card 3D flip (rotateY 180° → 0°) with shimmer sweep
- Large tier name with counter-scale animation
- XP progress bar fills
- Streak flames (fire emoji with flicker animation)
- New achievements list below
- Particle burst in tier color

## Badge Definitions

### Session Badges (per-session, can upgrade tier)
| ID | Name | Icon | Criteria |
|----|------|------|----------|
| pace_master | Pace Master | Racing helmet | Pace score ≥ 60/75/90% of max |
| consistency_champion | Consistency Champion | Stopwatch | Consistency score ≥ 60/75/90% |
| execution_expert | Execution Expert | Steering wheel | Execution score ≥ 60/75/90% |
| endurance_warrior | Endurance Warrior | Shield+checkered | Robustness score ≥ 60/75/90% |
| adaptor | Adaptor | Weather vane | Adaptation score ≥ 60/75/90% |
| flow_state | Flow State | Trophy cup | Total score ≥ 60/75/90% |

### Career Achievements (milestone, earned once)
| ID | Name | Description | Threshold |
|----|------|-------------|-----------|
| laps_10 | First Steps | Complete 10 laps | 10 laps |
| laps_100 | Century Club | Complete 100 laps | 100 laps |
| laps_1000 | Lap Legend | Complete 1,000 laps | 1000 laps |
| sessions_5 | Regular Driver | Complete 5 sessions | 5 sessions |
| sessions_100 | Track Addict | Complete 100 sessions | 100 sessions |
| score_80 | High Performer | Score 80+ in a session | 80 score |
| score_90 | Elite Driver | Score 90+ in a session | 90 score |
| consistency_5 | Iron Consistency | 5 sessions in a row score 60+ | 5 streak |
| tracks_5 | Globetrotter | Drive at 5 different tracks | 5 tracks |
| pb_beat_5 | Relentless | Beat PB 5 times at one track | 5 PBs |

### Hidden Achievements (surprise, revealed on earn)
| ID | Name | Description |
|----|------|-------------|
| the_machine | The Machine | 10 consecutive laps within 0.3% CV |
| rain_master | Rain Master | Score 75+ in wet conditions |
| zero_traffic | Zero Traffic | Endurance stint with 0 traffic incidents |
| perfect_pit | Perfect Pit | Pit stop within threshold time |

## Licence Tiers

| Tier | Color | Requirements | Unlocks |
|------|-------|-------------|---------|
| Rookie | #888 | 0 laps | Basic reports |
| Club | #B6FF2E | 50 laps + score 50+ | Session comparison |
| National | #00d4ff | 200 laps + score 65+ at 2 tracks | Focus mode, endurance |
| Pro | #D946EF | 500 laps + score 75+ + beat PB 3x | Coaching V3, trends |
| Elite | #FFD400 | 1000 laps + score 85+ + CV < 1.5% | Advanced analytics |
| Legend | #FF3B6B | 2000 laps + score 90+ + 5-session 80+ streak | Full access + badge |

## Data Model

### New columns on `driver_profiles` table:
- `licence_tier TEXT DEFAULT 'rookie'`
- `total_xp INTEGER DEFAULT 0`
- `current_streak INTEGER DEFAULT 0`
- `best_streak INTEGER DEFAULT 0`

### New table `driver_badges`:
```sql
CREATE TABLE driver_badges (
    id SERIAL PRIMARY KEY,
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    badge_id TEXT NOT NULL,
    tier TEXT NOT NULL,  -- bronze/silver/gold
    earned_at TIMESTAMP DEFAULT NOW(),
    session_id TEXT,     -- session that triggered it
    workspace_id INTEGER
);
CREATE UNIQUE INDEX idx_driver_badge ON driver_badges(driver_id, badge_id);
```

### New table `driver_achievements`:
```sql
CREATE TABLE driver_achievements (
    id SERIAL PRIMARY KEY,
    driver_id INTEGER NOT NULL REFERENCES drivers(driver_id),
    achievement_id TEXT NOT NULL,
    earned_at TIMESTAMP DEFAULT NOW(),
    session_id TEXT,
    workspace_id INTEGER
);
CREATE UNIQUE INDEX idx_driver_achievement ON driver_achievements(driver_id, achievement_id);
```

## API Endpoints

- `GET /api/v1/drivers/:id/achievements` — badges + achievements + licence + XP
- `GET /api/v1/drivers/:id/share-card/:session_id` — PNG share card
- `POST /api/v1/sessions/:id/claim-badges` — evaluate and persist new badges after analysis

## Frontend Components

- `AchievementUnlockOverlay.tsx` — full-screen unlock animation (reusable)
- `LevelUpOverlay.tsx` — licence upgrade animation (already exists, enhance)
- `TrophyCabinet.tsx` — badge grid for driver profile
- `LicenceCard.tsx` — current tier + progress bar
- `ShareCardCanvas.tsx` — canvas-based PNG generator
- `BadgeHex.tsx` — reusable hex SVG badge component with tier variants

## Animation Sequence (unlock)
1. 0ms: backdrop fades in
2. 300ms: card scales in with elastic bounce + slight rotation
3. 400ms: hex stroke draws itself (stroke-dasharray)
4. 500ms: badge icon pops in (scale 0→1 elastic)
5. 500-900ms: 3 ring bursts expand outward
6. 600ms: glow fades in, begins pulse loop
7. 300ms: 30 particles burst from center
8. 1000ms: "Achievement Unlocked" label slides up
9. 1100ms: title slides up
10. 1200ms: description slides up
11. 1300ms: tier dots appear
12. 1500ms: progress bar fills
13. 1500ms: dismiss button fades in

## Mockup Reference
`docs/achievement-mockup.html` — interactive prototype with all animations
