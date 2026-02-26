import { PersonaPage } from '@/components/site/PersonaPage';
import { personaBySlug } from '@/data/personas';

export default function TeamsPage() {
  return <PersonaPage persona={personaBySlug.teams} />;
}
