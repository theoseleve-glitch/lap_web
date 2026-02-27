'use client';
import { useKernelStore } from '@/experience/state/store';
import { rooms } from '@/lib/tokens';

export function useChapter() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const chapterProgress = useKernelStore((s) => s.chapterProgress);
  const room = rooms[currentChapter] ?? rooms[0];

  return {
    index: currentChapter,
    id: room.id,
    label: room.label,
    sector: room.sector,
    progress: chapterProgress,
  };
}
