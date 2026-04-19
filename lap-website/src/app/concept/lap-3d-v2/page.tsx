import type { Metadata } from 'next';
import { Lap3DConceptV2 } from '@/components/concepts/lap3d/Lap3DConceptV2';

export const metadata: Metadata = {
  title: 'Concept: Immersive Lap 3D v2',
  description:
    'More ambitious LAP concept exploring a premium scroll-driven motorsport brand experience with spatial depth and WebGL atmosphere.',
  robots: {
    index: false,
    follow: false,
  },
};

export default function Lap3DConceptV2Page() {
  return <Lap3DConceptV2 />;
}
