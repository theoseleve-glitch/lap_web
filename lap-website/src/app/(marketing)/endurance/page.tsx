import { PersonaPage } from '@/components/site/PersonaPage';
import { personaBySlug } from '@/data/personas';

export default function EndurancePage() {
  return <PersonaPage persona={personaBySlug.endurance} />;
}
