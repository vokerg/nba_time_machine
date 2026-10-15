import { useEffect, useMemo, useRef, useState } from "react";
import { BackendClient, nbaDate, profileIdentity } from "./api";
import type { ScheduleView, Timeline } from "./api";
import { orderByPregameInterest } from "./dashboard";
import type { FullReveal, GameCard, GameList, Reason, Verdict } from "./dashboard";
import type { QueueState, WatchQueue } from "./watchQueue";

type Disclosure = { verdict?: Verdict; reason?: Reason; full?: FullReveal };
function formatTime(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short", timeZone: "America/New_York" }).format(new Date(iso)) + " ET";
}
function matchup(game: GameCard): string {
  return `${game.away_team ?? "Away team"} at ${game.home_team ?? "Home team"}`;
}

export function App() {
  const [client, setClient] = useState<BackendClient | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [newProfile, setNewProfile] = useState(false);
  const [initialCursor, setInitialCursor] = useState("2025-10-01T00:00");
  const [day, setDay] = useState("2025-10-21");
  const [view, setView] = useState<ScheduleView>("replay");
  const [slate, setSlate] = useState<GameList | null>(null);
  const [disclosures, setDisclosures] = useState<Record<string, Disclosure>>({});
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [watchPicks, setWatchPicks] = useState<GameCard[] | null>(null);
  const [rankingConsent, setRankingConsent] = useState(false);
  const [queue, setQueue] = useState<WatchQueue | null>(null);
  const [queueRevision, setQueueRevision] = useState(0);
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueError, setQueueError] = useState<string | null>(null);
  const queueGeneration = useRef(0);

  useEffect(() => {
    setWatchPicks(null); setRankingConsent(false);
  }, [timeline, day, view, reload]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(null); setSlate(null); setTimeline(null); setNewProfile(false);
    setWatchPicks(null); setRankingConsent(false);
    setDisclosures({}); setConfirming(null); generation.current += 1;
    let alive = true;
    async function resume() {
      try {
        const connected = new BackendClient(profileIdentity(window.localStorage));
        const saved = await connected.resume(controller.signal);
        if (!alive) return;
        setClient(connected); setTimeline(saved); setNewProfile(!saved);
        if (saved) setDay(nbaDate(saved.time_cursor));
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : "Cannot resume profile.");
      } finally { if (alive) setLoading(false); }
    }
    void resume();
    return () => { alive = false; controller.abort(); };
  }, [reload]);

  useEffect(() => {
    if (!client || !timeline) return;
    const controller = new AbortController();
    const ticket = ++generation.current;
    setLoading(true); setError(null); setSlate(null); setDisclosures({}); setConfirming(null);
    setWatchPicks(null); setRankingConsent(false);
    client.games(day, view, timeline.time_cursor, controller.signal).then((data) => {
      if (ticket === generation.current) setSlate(data);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && ticket === generation.current) setError(cause instanceof Error ? cause.message : "Cannot load games.");
    }).finally(() => { if (ticket === generation.current) setLoading(false); });
    return () => { controller.abort(); generation.current += 1; };
  }, [client, timeline, day, view]);

  useEffect(() => {
    if (!client || !timeline) { setQueue(null); return; }
    const controller = new AbortController();
    const ticket = ++queueGeneration.current;
    setQueue(null); setQueueError(null); setQueueLoading(true);
    client.queue(timeline.time_cursor, controller.signal).then((data) => {
      if (ticket === queueGeneration.current) setQueue(data);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && ticket === queueGeneration.current)
        setQueueError(cause instanceof Error ? cause.message : "Cannot load Watch Queue.");
    }).finally(() => {
      if (ticket === queueGeneration.current) setQueueLoading(false);
    });
    return () => { controller.abort(); queueGeneration.current += 1; };
  }, [client, timeline, queueRevision]);

  async function editQueue(gameId: string, state: QueueState | null) {
    if (!client || !timeline) return;
    const ticket = queueGeneration.current;
    setBusy(true); setQueueError(null);
    try {
      if (state === null) await client.removeQueue(gameId, timeline.time_cursor);
      else await client.saveQueue(gameId, state, timeline.time_cursor);
      if (ticket === queueGeneration.current) setQueueRevision((value) => value + 1);
    } catch (cause) {
      if (ticket === queueGeneration.current)
        setQueueError(cause instanceof Error ? cause.message : "Cannot update Watch Queue.");
    } finally { setBusy(false); }
  }

  async function initialize() {
    if (!client) return;
    setBusy(true); setError(null);
    try {
      const saved = await client.initialize(new Date(initialCursor + ":00Z").toISOString());
      setTimeline(saved); setNewProfile(false); setDay(nbaDate(saved.time_cursor));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Cannot initialize timeline."); }
    finally { setBusy(false); }
  }
  async function advance(hours: number) {
    if (!client || !timeline) return;
    setBusy(true); setError(null); setSlate(null); setDisclosures({}); setConfirming(null); generation.current += 1;
    setWatchPicks(null); setRankingConsent(false);
    try {
      const saved = await client.advance(timeline.time_cursor, hours);
      setTimeline(saved); setDay(nbaDate(saved.time_cursor));
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Cannot advance timeline."); }
    finally { setBusy(false); }
  }
  function selectDate(value: string) {
    setWatchPicks(null); setRankingConsent(false);
    generation.current += 1; setSlate(null); setDisclosures({}); setConfirming(null); setDay(value);
  }
  function selectView(value: ScheduleView) {
    setWatchPicks(null); setRankingConsent(false);
    generation.current += 1; setSlate(null); setDisclosures({}); setConfirming(null); setView(value);
  }
  async function disclose(game: GameCard, layer: "watchability" | "why" | "full") {
    if (!client) return;
    const ticket = generation.current;
    setBusy(true); setError(null);
    try {
      const result = await client.disclose(game.game_id, layer, true);
      if (ticket !== generation.current) return;
      setDisclosures((prior) => ({ ...prior, [game.game_id]: {
        ...prior[game.game_id], ...(layer === "full" ? { full: result as FullReveal } : layer === "why" ? { reason: result as Reason } : { verdict: result as Verdict }),
      } }));
      if (layer === "full") {
        setSlate((prior) => prior && ({ ...prior, games: prior.games.map((card) => card.game_id === game.game_id ? { ...card, state: "acknowledged" } : card) }));
        setConfirming(null);
        setQueueRevision((value) => value + 1);
      }
    } catch (cause) {
      if (ticket === generation.current) setError(cause instanceof Error ? cause.message : "Disclosure unavailable.");
    } finally { setBusy(false); }
  }

  async function recommend() {
    if (!client || !slate || view !== "pregame" || !rankingConsent) return;
    const ticket = generation.current;
    setBusy(true); setError(null); setWatchPicks(null); setRankingConsent(false);
    try {
      const picks = await client.recommend(slate, day, true);
      if (ticket === generation.current) setWatchPicks(picks);
    } catch (cause) {
      if (ticket === generation.current) setError(cause instanceof Error ? cause.message : "Watchability ranking unavailable.");
    } finally { setBusy(false); }
  }

  const teams = [...new Set((slate?.games ?? []).flatMap((game) => [game.home_team, game.away_team].filter((name): name is string => !!name)))].sort();
  const queuedIds = new Set((queue?.items ?? []).map((item) => item.game_id));
  const recommended = useMemo(() => orderByPregameInterest((slate?.games ?? []).filter((game) => game.pregame_interest !== undefined)), [slate]);
  return <div className="app">
    <header className="topbar"><a className="brand" href="#home"><span className="brand-symbol">↶</span><span>NBA <strong>TIME MACHINE</strong></span></a><div className="topbar-right"><span className="demo-pill">Backend data</span></div></header>
    <main className="shell" id="home">
      <section className="masthead"><div><p className="eyebrow">Your own NBA universe</p><h1>Catch up without <em>catching spoilers.</em></h1><p className="lede">Move your NBA world forward, then open each game's story when you're ready.</p></div></section>
      <section className="timeline-panel" aria-labelledby="timeline-heading">
        <div className="timeline-copy"><p className="eyebrow">Current NBA-world time</p><h2 id="timeline-heading">{timeline ? formatTime(timeline.time_cursor) : newProfile ? "Choose your starting point" : "Resuming timeline…"}</h2><p>The backend saves your cursor and game acknowledgements. Your world only moves forward.</p></div>
        {newProfile ? <div className="timeline-controls"><label>Starting cursor (UTC)<input type="datetime-local" value={initialCursor} disabled={busy} onChange={(e) => setInitialCursor(e.target.value)} /></label><button type="button" disabled={busy || !initialCursor} onClick={() => void initialize()}>Start timeline</button></div> : timeline && <div className="timeline-controls">
          <button disabled={busy || loading} onClick={() => void advance(6)}>Advance 6 hours</button><button className="primary" disabled={busy || loading} onClick={() => void advance(24)}>Advance 1 day</button>
          <button disabled={busy || loading || Date.parse(timeline.time_cursor) >= Date.now()} onClick={() => { if (window.confirm("Advance to now? This accepts all NBA information up to now and cannot be undone.")) void advance((Date.now() - Date.parse(timeline.time_cursor)) / 3_600_000); }}>Advance to now</button>
        </div>}
      </section>
      {error && <div className="notice error" role="alert">{error} <button disabled={busy} onClick={() => setReload((n) => n + 1)}>Reload saved state</button></div>}
      {timeline && <div className="dashboard-grid">
        <section className="games-section" aria-labelledby="games-heading">
          <div className="section-header"><div><p className="eyebrow">2025/26 · 2026/27</p><h2 id="games-heading">Games, on your terms.</h2></div></div>
          <div className="schedule-controls"><label>NBA date (Eastern)<input type="date" min="2025-07-01" max="2027-06-30" value={day} disabled={busy} onChange={(e) => selectDate(e.target.value)} /></label>
            <label>Schedule view<select value={view} disabled={busy} onChange={(e) => selectView(e.target.value as ScheduleView)}><option value="replay">Season replay</option><option value="pregame">Historically observed pregame</option><option value="observed">Observed schedule / backfill</option></select></label></div>
          <p className="section-intro">{view === "replay" ? "Replay the imported season on its original game dates, through your current NBA day. These are retrospective matchups and tip times, not archived pregame context. Coverage is partial." : view === "pregame" ? "Only genuine pre-tip observations known at your cursor appear here." : "Matchups and tip times appear only after we observed them. Backfill does not reconstruct the historical pregame world."} Results remain behind explicit actions.</p>
          {loading && <div className="empty-state" role="status">Loading games…</div>}
          {!loading && slate?.games.length === 0 && <div className="empty-state">No covered games available at this cursor and date. Season replay covers dates through your current NBA day. Empty dates may mean missing provider coverage or observations, rather than no NBA games.</div>}
          <div className="game-list">{slate?.games.map((game) => {
            const shown = disclosures[game.game_id] ?? {};
            return <article className="game-card" key={game.game_id}>
              <div className="game-meta"><span>{game.scheduled_tip ? formatTime(game.scheduled_tip) : "Tip unavailable"}</span><span>{game.state === "sealed" ? "Sealed" : "Acknowledged"}</span></div>
              <h3>{matchup(game)}</h3><p className="pregame-label">Pregame interest · {game.pregame_interest?.toFixed(1) ?? "Not available"}</p>
              <p className="small-label">Watchability hints can reveal that something unusual happened. Why reveals more detail.</p>
              <div className="game-actions"><button disabled={busy || loading || queueLoading || !queue} onClick={() => void editQueue(game.game_id, queuedIds.has(game.game_id) ? null : "queued")}>{queuedIds.has(game.game_id) ? "Remove from queue" : "Save to queue"}</button><button disabled={busy || loading} onClick={() => void disclose(game, "watchability")}>Show watchability hint</button><button className="danger-link" disabled={busy || loading} onClick={() => setConfirming(game.game_id)}>Reveal result ↗</button></div>
              {(shown.verdict || shown.reason) && !shown.full && <div className="disclosure-box" aria-live="polite"><strong>{shown.reason?.watchability_verdict ?? shown.verdict?.watchability_verdict ?? "Watchability data is unavailable"}</strong>{shown.reason?.watchability_reason && <p>{shown.reason.watchability_reason}</p>}{!shown.reason && shown.verdict?.watchability_verdict && <button disabled={busy} onClick={() => void disclose(game, "why")}>Why? Show one more hint</button>}</div>}
              {confirming === game.game_id && <div className="confirmation"><p>Reveal this game's score and acknowledge it? Your global timeline will stay where it is.</p><button disabled={busy} onClick={() => void disclose(game, "full")}>Yes, reveal score</button><button disabled={busy} onClick={() => setConfirming(null)}>Keep result hidden</button></div>}
              {shown.full && <div className="result-box" aria-live="polite"><p className="small-label">Explicitly revealed</p><strong>{game.away_team} {shown.full.away_score ?? "–"} — {shown.full.home_score ?? "–"} {game.home_team}</strong>{shown.full.result && <p>{shown.full.result}</p>}</div>}
            </article>;
          })}</div>
        </section>
        <aside className="side-column"><section className="side-panel watch-panel"><p className="eyebrow">The viewing guide</p><h2>What should I watch?</h2><p>Pregame interest alone determines these suggestions.</p>{recommended[0] ? <strong>{matchup(recommended[0])}</strong> : <p>No pregame recommendation available.</p>}
          <h3>Postgame viewing guide</h3><p>Selection and order use completed-game quality and can hint at surprises. Numeric quality scores stay hidden.</p>
          {view !== "pregame" ? <p>Use Historically observed pregame to request watchability picks from a historically observed slate.</p> : <>
            <label className="ranking-consent"><input type="checkbox" checked={rankingConsent} disabled={busy || loading} onChange={(e) => setRankingConsent(e.target.checked)} />I accept outcome-based hints for this request.</label>
            <div className="game-actions"><button disabled={busy || loading || !rankingConsent || !slate?.games.length} onClick={() => void recommend()}>Rank by watchability</button></div>
          </>}
          {watchPicks !== null && <div aria-live="polite">{watchPicks.length ? <ol>{watchPicks.map((game) => <li key={game.game_id}>{matchup(game)}</li>)}</ol> : <p>No eligible picks for this request. Watchability data is unavailable; this is not a poor-quality verdict.</p>}</div>}
        </section>
          <section className="side-panel queue-panel" aria-labelledby="queue-heading">
            <p className="eyebrow">Personal, not a reveal</p><h2 id="queue-heading">Watch Queue</h2>
            <p>Queued / done / dismissed tracks your plans only. It never acknowledges games or moves your timeline. Cards use spoiler-safe season replay; unavailable games stay hidden.</p>
            {queueError && <p role="alert">Watch Queue: {queueError} <button disabled={busy} onClick={() => setReload((n) => n + 1)}>Reload saved state</button></p>}
            {queueLoading && <p role="status">Loading Watch Queue…</p>}
            {!queueLoading && queue?.items.length === 0 && <p>Your Watch Queue is empty.</p>}
            <ol className="queue-list">{queue?.items.map((item) => {
              const game = item.game;
              const shown = disclosures[item.game_id] ?? {};
              return <li key={item.game_id} className="queue-item">
                <strong>{game ? matchup(game) : "Saved game"}</strong>
                <p className="small-label">{game ? (game.scheduled_tip ? formatTime(game.scheduled_tip) : "Tip unavailable") + " · " + (game.state === "sealed" ? "Sealed" : "Acknowledged") : "Game details unavailable at this cursor."}</p>
                <div className="game-actions">
                  <label>My plan <select aria-label="My plan" value={item.queue_state} disabled={busy} onChange={(e) => void editQueue(item.game_id, e.target.value as QueueState)}><option value="queued">Queued</option><option value="done">Done</option><option value="dismissed">Dismissed</option></select></label>
                  <button disabled={busy} onClick={() => void editQueue(item.game_id, null)}>Remove</button>
                  {game && <button className="danger-link" disabled={busy} onClick={() => setConfirming(item.game_id)}>Reveal result ↗</button>}
                </div>
                {game && confirming === item.game_id && <div className="confirmation"><p>Reveal this game's result separately from your queue plan? The global cursor stays unchanged.</p><button disabled={busy} onClick={() => void disclose(game, "full")}>Yes, reveal score</button><button disabled={busy} onClick={() => setConfirming(null)}>Keep result hidden</button></div>}
                {game && shown.full && <div className="result-box"><strong>{game.away_team} {shown.full.away_score ?? "–"} — {shown.full.home_score ?? "–"} {game.home_team}</strong></div>}
              </li>;
            })}</ol>
          </section>
          <section className="side-panel favorites-panel"><h2>Favorite teams</h2><p>Favorites never change the canonical list order.</p><div className="favorite-choices">{teams.map((team) => <label key={team}><input type="checkbox" checked={favorites.includes(team)} onChange={() => setFavorites((prior) => prior.includes(team) ? prior.filter((name) => name !== team) : [...prior, team])} /><span>{team}</span></label>)}</div></section></aside>
        <section className="media-section"><h2>News &amp; buzz</h2><p>A timeline-filtered media endpoint is not connected yet. Game reveals never unlock later general media.</p></section>
      </div>}
      {!timeline && loading && <p role="status">Connecting to backend…</p>}
      <footer className="footer"><span>NBA TIME MACHINE</span><span>Partial season coverage · forward-only cursor</span></footer>
    </main>
  </div>;
}
