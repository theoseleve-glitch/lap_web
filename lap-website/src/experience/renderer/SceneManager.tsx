'use client';

import { useMemo } from 'react';
import { useKernelStore } from '@/experience/state/store';
import type { ChapterConfig, ChapterSceneProps } from '@/experience/state/types';

// Chapter configs will be registered here
const chapterRegistry: ChapterConfig[] = [];

export function registerChapter(config: ChapterConfig) {
  const existing = chapterRegistry.findIndex((c) => c.id === config.id);
  if (existing >= 0) {
    chapterRegistry[existing] = config;
  } else {
    chapterRegistry.push(config);
    chapterRegistry.sort((a, b) => a.index - b.index);
  }
}

export function getChapterConfigs(): readonly ChapterConfig[] {
  return chapterRegistry;
}

export function SceneManager() {
  const currentChapter = useKernelStore((s) => s.currentChapter);
  const chapterProgress = useKernelStore((s) => s.chapterProgress);
  const scrollVelocity = useKernelStore((s) => s.scrollVelocity);
  const pointerX = useKernelStore((s) => s.pointerX);
  const pointerY = useKernelStore((s) => s.pointerY);
  const qualityTier = useKernelStore((s) => s.qualityTier);

  // Render current + adjacent scenes for transition readiness
  const visibleIndices = useMemo(() => {
    const indices = new Set<number>();
    indices.add(currentChapter);
    if (currentChapter > 0) indices.add(currentChapter - 1);
    if (currentChapter < chapterRegistry.length - 1) indices.add(currentChapter + 1);
    return indices;
  }, [currentChapter]);

  const sceneProps: Omit<ChapterSceneProps, 'active'> = {
    progress: chapterProgress,
    scrollVelocity,
    pointerX,
    pointerY,
    qualityTier,
  };

  return (
    <group>
      {chapterRegistry.map((config) => {
        if (!config.scene) return null;
        const isVisible = visibleIndices.has(config.index);
        if (!isVisible) return null;

        const Scene = config.scene;
        return (
          <Scene
            key={config.id}
            {...sceneProps}
            active={config.index === currentChapter}
          />
        );
      })}
    </group>
  );
}
