'use client';

import type { ReactNode } from 'react';
import { InputManager } from './input/InputManager';
import { QualityManager } from './quality/QualityManager';
import { DebugHUD } from './quality/DebugHUD';
import { MotionOrchestrator } from './motion/MotionOrchestrator';
import { SectorGateController } from './narrative/SectorGateController';
import { DrsController } from './narrative/DrsController';
import { DeltaTickController } from './narrative/DeltaTickController';
import { chapters } from './state/chapters';
import { registerChapter } from './renderer/SceneManager';
import { EXPERIENCE_V2 } from '@/lib/feature-flags';

// Register all chapters on module load
chapters.forEach(registerChapter);

interface ExperienceKernelProps {
  children: ReactNode;
}

export function ExperienceKernel({ children }: ExperienceKernelProps) {
  return (
    <>
      <QualityManager />
      <InputManager />
      <MotionOrchestrator />
      {EXPERIENCE_V2 && <SectorGateController />}
      {EXPERIENCE_V2 && <DrsController />}
      {EXPERIENCE_V2 && <DeltaTickController />}
      <DebugHUD />
      {children}
    </>
  );
}
