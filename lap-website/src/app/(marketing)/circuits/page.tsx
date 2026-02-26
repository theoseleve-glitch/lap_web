import { PersonaPage } from '@/components/site/PersonaPage';
import { personaBySlug } from '@/data/personas';

export default function CircuitsPage() {
  return <PersonaPage persona={personaBySlug.circuits} />;
}
