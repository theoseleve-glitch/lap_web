import type { Metadata } from 'next';
import { Lap3DConcept } from '@/components/concepts/lap3d/Lap3DConcept';

export const metadata: Metadata = {
  title: 'Concept: Immersive Lap 3D v1',
  description:
    'Experimental LAP landing-page concept exploring a premium, cinematic one-lap scroll narrative.',
  robots: {
    index: false,
    follow: false,
  },
};

export default function Lap3DConceptPage() {
  return <Lap3DConcept />;
}
