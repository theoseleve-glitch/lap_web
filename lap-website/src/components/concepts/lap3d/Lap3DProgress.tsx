import styles from './Lap3DConcept.module.css';

export interface Lap3DBeat {
  id: string;
  label: string;
  title: string;
}

interface Lap3DProgressProps {
  beats: readonly Lap3DBeat[];
  activeBeat: string;
}

export function Lap3DProgress({ beats, activeBeat }: Lap3DProgressProps) {
  return (
    <aside className={styles.progressRail} aria-label="Lap progress">
      <p className={styles.progressEyebrow}>Lap Concept</p>
      <div className={styles.progressTrack}>
        <div className={styles.progressTrackLine} />
        <div className={styles.progressTrackFill} />
        <div className={styles.progressMarker} />
        <ol className={styles.progressList}>
          {beats.map((beat) => {
            const isActive = beat.id === activeBeat;
            return (
              <li
                key={beat.id}
                className={`${styles.progressItem} ${isActive ? styles.progressItemActive : ''}`}
                aria-current={isActive ? 'step' : undefined}
              >
                <span className={styles.progressDot} />
                <span className={styles.progressLabel}>{beat.label}</span>
                <span className={styles.progressTitle}>{beat.title}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </aside>
  );
}
