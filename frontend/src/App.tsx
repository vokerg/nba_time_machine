export function App() {
  return (
    <main className="shell">
      <header className="hero">
        <p className="eyebrow">NBA Time Machine</p>
        <h1>Watch yesterday without learning tomorrow.</h1>
        <p className="lede">
          The product shell is in place. The next issues will connect the time cursor,
          spoiler firewall, source ingestion, Neon history and game recommendations.
        </p>
      </header>

      <section className="card" aria-labelledby="timeline-heading">
        <div>
          <p className="label">NBA world</p>
          <h2 id="timeline-heading">Time cursor not connected yet</h2>
        </div>
        <span className="badge">Strict spoilers</span>
      </section>

      <section className="grid">
        <article className="panel">
          <p className="label">Games</p>
          <h2>Pregame rankings</h2>
          <p>Only information knowable before tip-off belongs here.</p>
        </article>
        <article className="panel">
          <p className="label">Media</p>
          <h2>News and buzz</h2>
          <p>Articles, social posts and podcasts will respect the selected timeline.</p>
        </article>
        <article className="panel">
          <p className="label">Ask</p>
          <h2>What should I watch?</h2>
          <p>Canonical recommendations will optimize watchability, not fandom.</p>
        </article>
      </section>
    </main>
  );
}
