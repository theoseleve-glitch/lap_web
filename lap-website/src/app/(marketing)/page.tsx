'use client';

import { StartGrid } from '@/components/rooms/StartGrid';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S1DeepSculpture } from '@/components/rooms/S1DeepSculpture';
import { S2Pipeline } from '@/components/rooms/S2Pipeline';
import { S2Proof } from '@/components/rooms/S2Proof';
import { S3Product } from '@/components/rooms/S3Product';
import { S4WorkflowCoverage } from '@/components/rooms/S4WorkflowCoverage';
import { PitStop } from '@/components/rooms/PitStop';
import { Garage } from '@/components/rooms/Garage';
import { Podium } from '@/components/rooms/Podium';

export default function Home() {
  return (
    <main>
      <StartGrid />
      <S1Pain />
      <S1DeepSculpture />
      <S2Pipeline />
      <S2Proof />
      <S3Product />
      <S4WorkflowCoverage />
      <PitStop />
      <Garage />
      <Podium />
    </main>
  );
}
