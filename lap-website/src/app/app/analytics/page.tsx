import { PageHeader } from '@/components/app';

const analyticsCards = [
  {
    title: 'Weather Analysis',
    description: 'Explore how temperature, wind, and precipitation conditions affect lap times and driving performance.',
    icon: '~',
  },
  {
    title: 'Performance Trends',
    description: 'Track your score progression and best lap times over time to spot improvement patterns.',
    icon: '/',
  },
  {
    title: 'Meteo Correlation',
    description: 'Deep dive into atmospheric correlations: temperature, humidity, and pressure vs performance metrics.',
    icon: '%',
  },
  {
    title: 'Weight Simulator',
    description: 'Simulate the impact of driver weight, kart weight, and ballast changes on lap time.',
    icon: '#',
  },
  {
    title: 'Pace Predictor',
    description: 'Predict target lap times for a given track and conditions based on historical data.',
    icon: '>',
  },
];

export default function AnalyticsHubPage() {
  return (
    <div>
      <PageHeader
        title="Analytics"
        subtitle="Advanced analysis tools and predictive insights"
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-2">
        {analyticsCards.map((card) => (
          <div
            key={card.title}
            className="relative bg-concrete rounded-lg border border-steel/20 p-5 cursor-not-allowed opacity-70 flex flex-col"
          >
            <div className="absolute top-3 right-3">
              <span className="inline-block px-2 py-0.5 bg-amber-500/10 text-amber-400 text-[10px] font-medium rounded-full">
                Coming Soon
              </span>
            </div>
            <div className="flex items-center gap-3 mb-3">
              <span className="font-telemetry text-2xl text-acid-green w-8 text-center">
                {card.icon}
              </span>
              <h2 className="font-monument text-base text-chalk">
                {card.title}
              </h2>
            </div>
            <p className="text-steel font-body text-sm leading-relaxed flex-1">
              {card.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
