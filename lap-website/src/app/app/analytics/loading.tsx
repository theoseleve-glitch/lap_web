export default function AnalyticsLoading() {
  return (
    <div className="space-y-6 p-6 animate-pulse">
      <div className="h-8 w-44 bg-steel/10 rounded" />
      <div className="grid grid-cols-2 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-48 bg-steel/5 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
