export default function SessionDetailLoading() {
  return (
    <div className="space-y-6 p-6 animate-pulse">
      <div className="h-8 w-64 bg-steel/10 rounded" />
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-24 bg-steel/5 rounded-lg" />
        ))}
      </div>
      <div className="h-[300px] bg-steel/5 rounded-lg" />
      <div className="h-[200px] bg-steel/5 rounded-lg" />
    </div>
  );
}
