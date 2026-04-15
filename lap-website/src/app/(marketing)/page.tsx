import { StartGrid } from '@/components/rooms/StartGrid';
import { SessionProof } from '@/components/rooms/SessionProof';
import { S1Pain } from '@/components/rooms/S1Pain';
import { S2Versus } from '@/components/rooms/S2Versus';
import { S3Product } from '@/components/rooms/S3Product';
import { SimFirst } from '@/components/rooms/SimFirst';
import { PremiumLayer } from '@/components/rooms/PremiumLayer';
import { Garage } from '@/components/rooms/Garage';
import { PitStop } from '@/components/rooms/PitStop';
import { Podium } from '@/components/rooms/Podium';

function Divider() {
  return <div className="section-divider" aria-hidden="true" />;
}

export default function Home() {
  return (
    <main id="main-content">
      <h1 className="sr-only">
        LAP Coach — Motorsport telemetry analysis for kart and car drivers
      </h1>
      <StartGrid />
      <Divider />
      <SessionProof />
      <Divider />
      <S1Pain />
      <Divider />
      <S2Versus />
      <S3Product />
      <Divider />
      <SimFirst />
      <Divider />
      <PremiumLayer />
      <Divider />
      <Garage />
      <Divider />
      <PitStop />
      <Divider />
      <Podium />
    </main>
  );
}
