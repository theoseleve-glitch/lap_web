'use client';

import type { ReactNode } from 'react';
import { InputManager } from './input/InputManager';
import { QualityManager } from './quality/QualityManager';
import { DebugHUD } from './quality/DebugHUD';
import { MotionOrchestrator } from './motion/MotionOrchestrator';
import { SectorGateController } from './narrative/SectorGateController';
import { DrsController } from './narrative/DrsController';
import { chapters } from './state/chapters';
import { registerChapter } from './renderer/SceneManager';

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
      <SectorGateController />
      <DrsController />
      <DebugHUD />
      {children}
    </>
  );
}
