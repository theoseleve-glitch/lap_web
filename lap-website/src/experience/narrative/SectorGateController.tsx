'use client';

import { useEffect, useRef } from 'react';
import { useKernelStore } from '@/experience/state/store';
import { sectorGates } from '@/lib/tokens';
import { getChapterPath, getHeadingDelta, isCornerChapter } from './TrackPath';

// Map sector gate chapter → tower sector index
const GATE_TO_TOWER_INDEX: Record<number, number> = {
  1: 0,   // S1
  3: 1,   // S2
  5: 2,   // S3
  8: 5,   // PIT (skipping S4=3, S5=4 which don't have gates)
};

export function getSectorIndexForGate(chapter: number): number | null {
  if (chapter === 10) return null; // FINISH is handled separately
  return GATE_TO_TOWER_INDEX[chapter] ?? null;
}

export function shouldTriggerGate(chapter: number, triggered: Set<number>): boolean {
  if (!sectorGates[chapter]) return false;
  return !triggered.has(chapter);
}

export function SectorGateController() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const completeSector = useKernelStore((s) => s.completeSector);
  const activateDrs = useKernelStore((s) => s.activateDrs);
  const setTrackPath = useKernelStore((s) => s.setTrackPath);
  const setPitMode = useKernelStore((s) => s.setPitMode);
  const crossFinishLine = useKernelStore((s) => s.crossFinishLine);
  const triggeredRef = useRef<Set<number>>(new Set());
  const prevChapterRef = useRef(currentChapter);

  // Update track path on every chapter change
  useEffect(() => {
    const path = getChapterPath(currentChapter);
    const headingDelta = getHeadingDelta(currentChapter);
    const isCorner = isCornerChapter(currentChapter);

    setTrackPath({ heading: path.heading, headingDelta, isCorner });

    // Pit mode
    if (path.type === 'pit-lane') {
      setPitMode(true);
    } else if (getChapterPath(prevChapterRef.current).type === 'pit-lane') {
      // Exiting pit-lane — path.type is already not 'pit-lane' in this branch
      setPitMode(false);
    }

    // Sector gate check
    if (shouldTriggerGate(currentChapter, triggeredRef.current)) {
      triggeredRef.current.add(currentChapter);

      const towerIndex = getSectorIndexForGate(currentChapter);
      if (towerIndex !== null) {
        completeSector(towerIndex);
        activateDrs('sector-gate');
      }
    }

    // Finish line
    if (currentChapter === 10 && !triggeredRef.current.has(10)) {
      triggeredRef.current.add(10);
      // Complete all remaining sectors
      const state = useKernelStore.getState();
      state.hudTower.sectors.forEach((s, i) => {
        if (s.status !== 'completed') completeSector(i);
      });
      crossFinishLine();
    }

    prevChapterRef.current = currentChapter;
  }, [currentChapter, completeSector, activateDrs, setTrackPath, setPitMode, crossFinishLine]);

  return null;
}
