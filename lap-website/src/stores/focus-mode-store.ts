import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ToolId } from '@/components/app/focus-mode/ToolDock';

interface FocusModeState {
  isOpen: boolean;
  dockVisible: boolean;
  activeTools: Record<string, ToolId[]>;
  splitSizes: Record<string, number>;
  open: (tab?: string, primaryTool?: ToolId) => void;
  close: () => void;
  toggleDock: () => void;
  setActiveTools: (tab: string, tools: ToolId[]) => void;
  setSplitSize: (tab: string, leftPercent: number) => void;
  resetLayout: (tab: string) => void;
}

const TAB_DEFAULTS: Record<string, ToolId[]> = {
  overview: ['track-map', 'speed-trace', 'gg-diagram'],
  corners: ['track-map', 'speed-trace', 'gg-diagram'],
  analytics: ['track-map', 'speed-trace', 'gg-diagram'],
  laps: ['track-map', 'speed-trace', 'gg-diagram'],
  timeline: ['track-map', 'speed-trace', 'gg-diagram'],
};

export const useFocusModeStore = create<FocusModeState>()(
  persist(
    (set) => ({
      isOpen: false,
      dockVisible: true,
      activeTools: {},
      splitSizes: {},
      open: (tab = 'overview', primaryTool?: ToolId) =>
        set((state) => {
          const defaults = TAB_DEFAULTS[tab] ?? ['speed-trace', 'track-map'];
          const tools: ToolId[] = primaryTool
            ? [primaryTool, ...(defaults.filter((t) => t !== primaryTool) as ToolId[])]
            : state.activeTools[tab] ?? defaults;
          return { isOpen: true, activeTools: { ...state.activeTools, [tab]: tools } };
        }),
      close: () => set({ isOpen: false }),
      toggleDock: () => set((state) => ({ dockVisible: !state.dockVisible })),
      setActiveTools: (tab, tools) =>
        set((state) => ({ activeTools: { ...state.activeTools, [tab]: tools } })),
      setSplitSize: (tab, leftPercent) =>
        set((state) => ({ splitSizes: { ...state.splitSizes, [tab]: leftPercent } })),
      resetLayout: (tab) =>
        set((state) => ({
          activeTools: {
            ...state.activeTools,
            [tab]: TAB_DEFAULTS[tab] ?? (['speed-trace', 'track-map'] as ToolId[]),
          },
          splitSizes: { ...state.splitSizes, [tab]: 60 },
        })),
    }),
    {
      name: 'focus-mode-layout',
      partialize: (state) => ({
        activeTools: state.activeTools,
        splitSizes: state.splitSizes,
        dockVisible: state.dockVisible,
      }),
    }
  )
);
