export interface PreloaderStage {
  label: string;
  weight: number;
}

export const PRELOADER_STAGES: PreloaderStage[] = [
  { label: 'LOADING CORE', weight: 0.4 },
  { label: 'BUILDING SCENES', weight: 0.4 },
  { label: 'PREPARING', weight: 0.2 },
];

export const PRELOADER_AUTO_UNLOCK_MS = 3000;
export const PRELOADER_BLACK_MS = 300;
export const PRELOADER_WORDMARK_MS = 1400;
