type EventProps = Record<string, string | number | boolean>;

function track(event: string, props?: EventProps) {
  if (typeof window !== 'undefined' && (window as unknown as Record<string, unknown>).plausible) {
    (window as unknown as Record<string, (event: string, options: { props?: EventProps }) => void>).plausible(event, { props });
  }
}

// ── Engagement ──
export const trackStartGridHold = (durationMs: number) =>
  track('start_grid_hold', { hold_duration_ms: durationMs });
export const trackStartGridComplete = () => track('start_grid_complete');
export const trackS1CornerInteract = (delta: number) =>
  track('s1_corner_interact', { delta_value: delta });
export const trackS1DeepTraceHover = (trace: string) =>
  track('s1_deep_trace_hover', { trace_name: trace });

// ── Education ──
export const trackS2PipelineComplete = () => track('s2_pipeline_complete');

// ── Trust ──
export const trackS2ProofReveal = (plate: string) =>
  track('s2_proof_reveal', { plate_name: plate });
export const trackGaragePanelExpand = (panel: string) =>
  track('garage_panel_expand', { panel_name: panel });

// ── Qualification ──
export const trackS3ModeSelect = (mode: 'b2c' | 'b2b') =>
  track('s3_mode_select', { mode });
export const trackS3ScrubberInteract = (position: number) =>
  track('s3_scrubber_interact', { position });

// ── Intent ──
export const trackPitStopEnter = (fromMode: string) =>
  track('pit_stop_enter', { from_mode: fromMode });
export const trackPricingToggle = (period: string) =>
  track('pricing_toggle', { period });
export const trackPricingPlanHover = (plan: string, durationMs: number) =>
  track('pricing_plan_hover', { plan_name: plan, duration_ms: durationMs });
export const trackAddonExpand = () => track('addon_expand');
export const trackFaqExpand = (questionId: number) =>
  track('faq_expand', { question_id: questionId });

// ── Conversion ──
export const trackCtaClick = (cta: string, location: string, mode: string) =>
  track('cta_click', { cta_name: cta, location, mode });

// ── Navigation ──
export const trackIndexOverlayOpen = (fromSection: string) =>
  track('index_overlay_open', { from_section: fromSection });
export const trackIndexOverlayNav = (toSection: string) =>
  track('index_overlay_nav', { to_section: toSection });

// ── Preference ──
export const trackSoundToggle = (enabled: boolean) =>
  track('sound_toggle', { enabled });
export const trackReducedMotionToggle = (enabled: boolean) =>
  track('reduced_motion_toggle', { enabled });

// ── Completion ──
export const trackPodiumReach = (scrollTimeMs: number, sectionsVisited: number) =>
  track('podium_reach', { total_scroll_time_ms: scrollTimeMs, sections_visited: sectionsVisited });
export const trackRestartLap = () => track('restart_lap');
