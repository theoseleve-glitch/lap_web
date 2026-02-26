export default function Home() {
  return (
    <main>
      {/* Rooms will be added in Tasks 5-12 */}
      <section
        id="start-grid"
        data-accent="none"
        className="room"
        aria-label="Start Grid"
      >
        <div className="grid-lap">
          <h1
            className="font-monument col-span-full"
            style={{ fontSize: 'var(--text-monument-xl)' }}
          >
            EVERY LAP<br />HAS A SECRET
          </h1>
        </div>
      </section>
    </main>
  );
}
