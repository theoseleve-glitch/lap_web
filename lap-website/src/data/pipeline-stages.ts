export interface PipelineStage {
  name: string;
  label: string;
  stamp: { label: string; detail: string };
  telemetryLabel: string;
}

export const pipelineStages: PipelineStage[] = [
  {
    name: 'INGEST',
    label: 'Ingest',
    stamp: { label: 'HEADER DETECTED', detail: '47 CHANNELS' },
    telemetryLabel: 'csv/25hz',
  },
  {
    name: 'CLEAN',
    label: 'Clean',
    stamp: { label: 'OUTLIERS REMOVED', detail: '99.2% RETAINED' },
    telemetryLabel: 'gps+imu',
  },
  {
    name: 'MAP',
    label: 'Map',
    stamp: { label: 'TRACK MATCHED', detail: 'CITY KART SAUTRON' },
    telemetryLabel: 'fingerprint',
  },
  {
    name: 'ANALYZE',
    label: 'Analyze',
    stamp: { label: '14 CORNERS SEGMENTED', detail: '25 LAPS' },
    telemetryLabel: 'physics',
  },
  {
    name: 'REPORT',
    label: 'Report',
    stamp: { label: 'SCORE: 86', detail: 'GRADE A' },
    telemetryLabel: '4-pillar',
  },
];
