export default function SessionsLoading() {
  return (
    <div className="space-y-4 p-6 animate-pulse">
      <div className="h-8 w-48 bg-steel/10 rounded" />
      <div className="flex gap-3">
        <div className="h-10 w-32 bg-steel/10 rounded" />
        <div className="h-10 w-32 bg-steel/10 rounded" />
        <div className="h-10 w-32 bg-steel/10 rounded" />
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="h-16 bg-steel/5 rounded-lg" />
      ))}
    </div>
  );
}
