// Track path spline data — defines the "virtual track" the user drives through
// as they scroll the landing page. Corners modulate background behavior.

export type ChapterPathType = 'straight' | 'corner-r' | 'corner-l' | 'pit-lane';

export interface ChapterPathConfig {
  chapter: number;
  heading: number;       // degrees, cumulative track direction
  type: ChapterPathType;
  label: string;
}

export const TRACK_PATH: readonly ChapterPathConfig[] = [
  { chapter: 0,  heading: 0,    type: 'straight',  label: 'Start Grid' },
  { chapter: 1,  heading: 35,   type: 'corner-r',  label: 'S1 Pain' },
  { chapter: 2,  heading: 35,   type: 'straight',  label: 'S1 Deep' },
  { chapter: 3,  heading: -20,  type: 'corner-l',  label: 'S2 Pipeline' },
  { chapter: 4,  heading: -20,  type: 'straight',  label: 'S2 Proof' },
  { chapter: 5,  heading: 25,   type: 'corner-r',  label: 'S3 Product' },
  { chapter: 6,  heading: 25,   type: 'straight',  label: 'S4 Workflows' },
  { chapter: 7,  heading: 40,   type: 'corner-r',  label: 'S5 Personas' },
  { chapter: 8,  heading: 0,    type: 'pit-lane',  label: 'Pit Stop' },
  { chapter: 9,  heading: 0,    type: 'straight',  label: 'Garage' },
  { chapter: 10, heading: 0,    type: 'straight',  label: 'Podium' },
] as const;

export function getChapterPath(chapter: number): ChapterPathConfig {
  const clamped = Math.max(0, Math.min(TRACK_PATH.length - 1, chapter));
  return TRACK_PATH[clamped];
}

export function getHeadingDelta(chapter: number): number {
  if (chapter <= 0) return 0;
  const clamped = Math.max(0, Math.min(TRACK_PATH.length - 1, chapter));
  const prev = TRACK_PATH[clamped - 1];
  const curr = TRACK_PATH[clamped];
  return curr.heading - prev.heading;
}

export function isCornerChapter(chapter: number): boolean {
  const path = getChapterPath(chapter);
  return path.type === 'corner-r' || path.type === 'corner-l';
}
