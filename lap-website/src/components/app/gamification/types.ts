export interface DriverProgress {
  total_xp: number;
  level: number;
  xp_for_current_level: number;
  xp_for_next_level: number;
  current_streak: number;
  longest_streak: number;
  achievements: Achievement[];
}

export interface Achievement {
  key: string;
  label: string;
  description: string;
  icon: string;
  unlocked: boolean;
  unlocked_at: string | null;
}

export interface GamificationEvent {
  xp_gained: number;
  new_level: number | null;
  new_achievements: string[];
  streak: number;
}

export interface DrillExecution {
  id: number;
  plan_id: number;
  week_number: number;
  drill_index: number;
  session_id: number | null;
  status: 'attempted' | 'completed' | 'skipped';
  notes: string | null;
  created_at: string;
  csv_filename?: string;
  session_date?: string;
}

export interface XpResult {
  execution_id: number;
  status: string;
  xp_result: {
    xp_gained: number;
    old_level: number;
    new_level: number;
    leveled_up: boolean;
  } | null;
}
