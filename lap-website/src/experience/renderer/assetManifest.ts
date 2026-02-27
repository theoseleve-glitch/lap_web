export interface AssetEntry {
  id: string;
  path: string;
  progress: number;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: number;
  chapterRange: [number, number];
}

export const ASSET_MANIFEST: readonly AssetEntry[] = [
  {
    id: 'helmet',
    path: '/models/helmet.glb',
    progress: 0.0,
    position: [3, 0.5, -2],
    rotation: [0, -0.3, 0],
    scale: 0.8,
    chapterRange: [0, 2],
  },
  {
    id: 'halo',
    path: '/models/halo.glb',
    progress: 0.45,
    position: [-3, 0.3, -1.5],
    rotation: [0.1, 0.5, 0],
    scale: 0.6,
    chapterRange: [4, 6],
  },
  {
    id: 'steering-wheel',
    path: '/models/steering-wheel.glb',
    progress: 0.55,
    position: [2.5, 0, -1],
    rotation: [0.3, -0.2, 0.1],
    scale: 0.5,
    chapterRange: [5, 7],
  },
  {
    id: 'pit-wall',
    path: '/models/pit-wall.glb',
    progress: 0.75,
    position: [-2, -0.5, -2],
    rotation: [0, 0.4, 0],
    scale: 0.4,
    chapterRange: [7, 9],
  },
  {
    id: 'tire',
    path: '/models/tire.glb',
    progress: 0.78,
    position: [2, -0.3, -1.5],
    rotation: [0, 0, 0],
    scale: 0.7,
    chapterRange: [8, 9],
  },
] as const;
