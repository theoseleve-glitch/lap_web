import type { ChapterConfig } from './types';
import { StartGridScene } from '@/experience/renderer/scenes/StartGridScene';
import { S1Scene } from '@/experience/renderer/scenes/S1Scene';
import { S2Scene } from '@/experience/renderer/scenes/S2Scene';
import { S3Scene } from '@/experience/renderer/scenes/S3Scene';
import { S4Scene } from '@/experience/renderer/scenes/S4Scene';
import { S5Scene } from '@/experience/renderer/scenes/S5Scene';
import { PitStopScene } from '@/experience/renderer/scenes/PitStopScene';
import { GarageScene } from '@/experience/renderer/scenes/GarageScene';
import { PodiumScene } from '@/experience/renderer/scenes/PodiumScene';

export const chapters: ChapterConfig[] = [
  {
    id: 'start-grid',
    index: 0,
    scene: StartGridScene,
    transition: { enter: 'preloader-unlock', exit: 'refraction' },
    snapWeight: 1.0,
    accentColor: 'none',
  },
  {
    id: 's1-pain',
    index: 1,
    scene: S1Scene,
    transition: { enter: 'refraction', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's1-deep',
    index: 2,
    scene: S1Scene,
    transition: { enter: 'crossfade-blur', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's2-pipeline',
    index: 3,
    scene: S2Scene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's2-proof',
    index: 4,
    scene: S2Scene,
    transition: { enter: 'crossfade-blur', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's3-product',
    index: 5,
    scene: S3Scene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'green',
  },
  {
    id: 's4-workflows',
    index: 6,
    scene: S4Scene,
    transition: { enter: 'crossfade-blur', exit: 'velocity-warp' },
    snapWeight: 1.0,
    accentColor: 'yellow',
  },
  {
    id: 's5-personas',
    index: 7,
    scene: S5Scene,
    transition: { enter: 'velocity-warp', exit: 'mask-wipe' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
  {
    id: 'pit-stop',
    index: 8,
    scene: PitStopScene,
    transition: { enter: 'mask-wipe', exit: 'crossfade-blur' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
  {
    id: 'garage',
    index: 9,
    scene: GarageScene,
    transition: { enter: 'crossfade-blur', exit: 'refraction' },
    snapWeight: 1.0,
    accentColor: 'none',
  },
  {
    id: 'podium',
    index: 10,
    scene: PodiumScene,
    transition: { enter: 'refraction', exit: 'none' },
    snapWeight: 1.0,
    accentColor: 'orange',
  },
];
