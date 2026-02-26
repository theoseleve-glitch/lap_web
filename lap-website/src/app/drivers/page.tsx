import { PersonaPage } from '@/components/site/PersonaPage';
import { personaBySlug } from '@/data/personas';

export default function DriversPage() {
  return <PersonaPage persona={personaBySlug.drivers} />;
}
