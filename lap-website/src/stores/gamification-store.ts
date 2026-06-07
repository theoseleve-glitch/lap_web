/**
 * gamification-store.ts — global gamification event queue.
 *
 * Any component in the app can fire an achievement unlock, level-up, or
 * XP gain. The global AppShell renders the corresponding overlay/toast.
 *
 * Usage:
 *   import { useGamificationStore } from '@/stores/gamification-store';
 *
 *   // Fire an achievement toast from any component:
 *   useGamificationStore.getState().showAchievement({ key: '...', label: '...', ... });
 *
 *   // Fire a level-up from any component:
 *   useGamificationStore.getState().showLevelUp({ oldLevel: 3, newLevel: 4, totalXp: 450 });
 */

import { create } from 'zustand';
import type { Achievement } from '@/components/app/gamification/types';

interface AchievementData {
  key: string;
  title: string;
  description: string;
  tier: 'bronze' | 'silver' | 'gold';
  icon?: string;
}

interface LevelUpData {
  oldLevel: number;
  newLevel: number;
  totalXp: number;
  sessionXp?: number;
}

interface GamificationState {
  // Current events to display
  achievementToast: Achievement | null;
  achievementOverlay: AchievementData | null;
  levelUp: LevelUpData | null;
  floatingPoints: Array<{ id: string; points: number; x: number; y: number }>;

  // Actions
  showAchievementToast: (achievement: Achievement) => void;
  dismissAchievementToast: () => void;
  showAchievementOverlay: (data: AchievementData) => void;
  dismissAchievementOverlay: () => void;
  showLevelUp: (data: LevelUpData) => void;
  dismissLevelUp: () => void;
  pushPoints: (points: number) => void;

  // Process a GamificationEvent from the backend (fires all relevant overlays)
  processEvent: (event: {
    xp_gained: number;
    new_level: number | null;
    old_level?: number;
    new_achievements: Achievement[];
    streak: number;
  }) => void;
}

export const useGamificationStore = create<GamificationState>((set, get) => ({
  achievementToast: null,
  achievementOverlay: null,
  levelUp: null,
  floatingPoints: [],

  showAchievementToast: (achievement) => set({ achievementToast: achievement }),
  dismissAchievementToast: () => set({ achievementToast: null }),

  showAchievementOverlay: (data) => set({ achievementOverlay: data }),
  dismissAchievementOverlay: () => set({ achievementOverlay: null }),

  showLevelUp: (data) => set({ levelUp: data }),
  dismissLevelUp: () => set({ levelUp: null }),

  pushPoints: (points) => {
    if (points <= 0) return;
    const id = `fp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    // Anchor near the sidebar XP bar (bottom-left); PointsAnimation floats it up.
    const x = 120;
    const y = typeof window !== 'undefined' ? window.innerHeight - 140 : 600;
    set({ floatingPoints: [...get().floatingPoints, { id, points, x, y }] });
    setTimeout(() => {
      set({ floatingPoints: get().floatingPoints.filter((p) => p.id !== id) });
    }, 1600);
  },

  processEvent: (event) => {
    if (event.xp_gained > 0) get().pushPoints(event.xp_gained);

    // Level up takes priority (shown as modal)
    if (event.new_level != null && event.old_level != null && event.new_level > event.old_level) {
      set({
        levelUp: {
          oldLevel: event.old_level,
          newLevel: event.new_level,
          totalXp: event.xp_gained,
          sessionXp: event.xp_gained,
        },
      });
    }

    // Queue achievement toasts (show first one; subsequent ones queue)
    if (event.new_achievements.length > 0) {
      const first = event.new_achievements[0];
      set({ achievementToast: first });

      // If there are more, schedule them after the first dismisses
      if (event.new_achievements.length > 1) {
        const remaining = event.new_achievements.slice(1);
        let idx = 0;
        const showNext = () => {
          if (idx < remaining.length) {
            setTimeout(() => {
              set({ achievementToast: remaining[idx] });
              idx++;
              showNext();
            }, 5500); // toast auto-dismisses after 5s + 300ms fade
          }
        };
        showNext();
      }
    }
  },
}));
