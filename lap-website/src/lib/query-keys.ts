/**
 * Centralized React Query key factory.
 *
 * Pattern: each domain has a root key and nested factories for scoped
 * invalidation. Use `queryKeys.sessions.all` to invalidate all session
 * queries, or `queryKeys.sessions.detail(id)` for a specific one.
 *
 * @example
 *   queryKey: queryKeys.sessions.detail(sessionId)
 *   queryClient.invalidateQueries({ queryKey: queryKeys.sessions.all })
 */

export const queryKeys = {
  // ── Sessions ──────────────────────────────────
  sessions: {
    all: ['sessions'] as const,
    list: (params?: Record<string, unknown>) => ['sessions', 'list', params] as const,
    detail: (id: string) => ['sessions', 'detail', id] as const,
    laps: (id: string) => ['sessions', 'laps', id] as const,
    corners: (id: string) => ['sessions', 'corners', id] as const,
    scores: (id: string) => ['sessions', 'scores', id] as const,
    speedTrace: (id: string) => ['sessions', 'speed-trace', id] as const,
    gpsTrace: (id: string) => ['sessions', 'gps-trace', id] as const,
    ggData: (id: string) => ['sessions', 'gg-data', id] as const,
  },

  // ── Drivers ────────────────────────────────────
  drivers: {
    all: ['drivers'] as const,
    detail: (id: number) => ['drivers', 'detail', id] as const,
    progression: (id: number) => ['drivers', 'progression', id] as const,
    styleHistory: (id: number) => ['drivers', 'style-history', id] as const,
    badges: (id: number) => ['drivers', 'badges', id] as const,
    bestEver: (id: number) => ['drivers', 'best-ever', id] as const,
    sessions: (id: number) => ['drivers', 'sessions', id] as const,
    gamification: (id: number) => ['drivers', 'gamification', id] as const,
  },

  // ── Tracks ────────────────────────────────────
  tracks: {
    all: ['tracks'] as const,
    detail: (id: string) => ['tracks', 'detail', id] as const,
  },

  // ── Karts ─────────────────────────────────────
  karts: {
    all: ['karts'] as const,
    detail: (id: string) => ['kart', id] as const,
  },

  // ── Weekends ──────────────────────────────────
  weekends: {
    all: ['weekends'] as const,
    detail: (id: string) => ['weekend', id] as const,
  },

  // ── Billing ───────────────────────────────────
  billing: {
    all: ['billing'] as const,
    usage: ['billing', 'usage'] as const,
    subscription: ['billing', 'subscription'] as const,
  },

  // ── Leaderboard ───────────────────────────────
  leaderboard: {
    all: ['leaderboard'] as const,
    list: (params: Record<string, unknown>) => ['leaderboard', params] as const,
    tracks: ['leaderboard-tracks'] as const,
    drivers: ['leaderboard-drivers'] as const,
  },

  // ── Jobs ──────────────────────────────────────
  jobs: {
    all: ['jobs'] as const,
    list: (limit?: number) => ['jobs', limit] as const,
  },

  // ── Charts / Analysis ─────────────────────────
  cornerReplay: (sessionId: string, cornerIds?: string) =>
    ['corner-replay', sessionId, cornerIds ?? 'all'] as const,
  cornerPositions: (sessionId: string) =>
    ['corner-positions', sessionId] as const,
  drivingAnalyzer: (sessionId: string, cornerFilter?: string) =>
    ['driving-analyzer', sessionId, cornerFilter ?? 'all'] as const,

  // ── Setup Tracker ─────────────────────────────
  setup: {
    status: ['setup', 'status'] as const,
  },

  // ── Exports ───────────────────────────────────
  exports: {
    all: ['exports'] as const,
  },
} as const;
