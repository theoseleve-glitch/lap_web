export default function TracksLoading() {
  return (
    <div className="space-y-4 p-6 animate-pulse">
      <div className="h-8 w-40 bg-steel/10 rounded" />
      <div className="grid grid-cols-3 gap-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-32 bg-steel/5 rounded-lg" />
        ))}
      </div>
    </div>
  );
}
