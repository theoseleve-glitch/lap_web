import { StartGrid } from '@/components/rooms/StartGrid';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S1DeepSculpture } from '@/components/rooms/S1DeepSculpture';
import { S2Pipeline } from '@/components/rooms/S2Pipeline';
import { S2Versus } from '@/components/rooms/S2Versus';
import { S3Product } from '@/components/rooms/S3Product';
import { S4WorkflowCoverage } from '@/components/rooms/S4WorkflowCoverage';
import { PitStop } from '@/components/rooms/PitStop';
import { Garage } from '@/components/rooms/Garage';
import { Podium } from '@/components/rooms/Podium';
import { MarqueeStrip } from '@/components/ui/MarqueeStrip';

const MARQUEE_TOP = [
  'TELEMETRY', 'LAP ANALYSIS', 'CORNER COACHING', 'PERFORMANCE SCORING',
  'SESSION DEBRIEF', 'DATA ENGINEERING', 'TRACK MAPPING',
];

const MARQUEE_MID = [
  'PACE', 'CONSISTENCY', 'EXECUTION', 'ROBUSTNESS',
  'BRAKING', 'APEX SPEED', 'EXIT DRIVE', 'RACING LINE',
];

export default function Home() {
  return (
    <main id="main-content">
      <StartGrid />
      <S1Pain />
      <MarqueeStrip items={MARQUEE_TOP} speed={35} />
      <S1DeepSculpture />
      <S2Pipeline />
      <S2Versus />
      <S3Product />
      <S4WorkflowCoverage />
      <MarqueeStrip items={MARQUEE_MID} speed={40} reverse />
      <PitStop />
      <Garage />
      <Podium />
    </main>
  );
}
