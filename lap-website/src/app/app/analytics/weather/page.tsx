import { ComingSoon } from '@/components/shared/ComingSoon';

export default function WeatherPage() {
  return (
    <ComingSoon
      title="Weather Analysis"
      description="Correlate weather conditions with lap performance to optimize your setup."
      backHref="/app/analytics"
    />
  );
}
