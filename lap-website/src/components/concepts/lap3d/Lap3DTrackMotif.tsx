import styles from './Lap3DConcept.module.css';

interface Lap3DTrackMotifProps {
  className?: string;
  variant?: 'hero' | 'problem' | 'pipeline' | 'cta';
}

const PATHS = {
  hero: 'M52 446C176 372 214 170 344 138c132-32 212 88 302 88 104 0 140-124 250-160',
  problem: 'M78 470c84-98 150-172 278-196 118-22 186 36 260 36 112 0 172-126 302-222',
  pipeline: 'M72 410c122-12 206-12 286-34 154-42 218-194 384-194 76 0 126 26 188 66',
  cta: 'M86 152c92 30 144 120 274 158 112 34 218-16 296 30 92 54 108 150 258 198',
} as const;

export function Lap3DTrackMotif({
  className = '',
  variant = 'hero',
}: Lap3DTrackMotifProps) {
  const path = PATHS[variant];

  return (
    <svg
      className={`${styles.trackMotif} ${className}`.trim()}
      viewBox="0 0 1000 600"
      fill="none"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      <path className={styles.trackBase} d={path} pathLength="100" />
      <path className={styles.trackAccent} d={path} pathLength="100" />
      <path className={styles.trackDash} d={path} pathLength="100" />
    </svg>
  );
}
