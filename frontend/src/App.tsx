import { useEffect, useMemo, useRef, useState } from "react";
import { BackendClient, nbaDate, profileIdentity } from "./api";
import type { ScheduleView, Timeline } from "./api";
import { orderByPregameInterest } from "./dashboard";
import type { FullReveal, GameCard, GameList, MediaFeed, Reason, Verdict } from "./dashboard";
import type { QueueState, WatchQueue } from "./watchQueue";

type Disclosure = { verdict?: Verdict; reason?: Reason; full?: FullReveal };

const FIRST_NBA_DAY = "2025-07-01";
const LAST_NBA_DAY = "2027-06-30";

function nextNbaDay(day: string, offset: number): string {
  const time = Date.parse(day + "T12:00:00Z");
  return Number.isFinite(time) ? new Date(time + offset * 86_400_000).toISOString().slice(0, 10) : day;
}
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
  const [confirming, setConfirming] = useState<{ gameId: string; from: "slate" | "queue" } | null>(null);
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
  const [media, setMedia] = useState<MediaFeed | null>(null);
  const [mediaLoading, setMediaLoading] = useState(false);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [mediaExpanded, setMediaExpanded] = useState(false);
  const mediaGeneration = useRef(0);

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
    client.queue(timeline.time_cursor, view, controller.signal).then((data) => {
      if (ticket === queueGeneration.current) setQueue(data);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && ticket === queueGeneration.current)
        setQueueError(cause instanceof Error ? cause.message : "Cannot load Watch Queue.");
    }).finally(() => {
      if (ticket === queueGeneration.current) setQueueLoading(false);
    });
    return () => { controller.abort(); queueGeneration.current += 1; };
  }, [client, timeline, view, queueRevision]);

  useEffect(() => {
    if (!client || !timeline) { setMedia(null); return; }
    const controller = new AbortController();
    const ticket = ++mediaGeneration.current;
    setMedia(null); setMediaError(null); setMediaLoading(true); setMediaExpanded(false);
    client.media(timeline.time_cursor, undefined, controller.signal).then((data) => {
      if (ticket === mediaGeneration.current) setMedia(data);
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted && ticket === mediaGeneration.current)
        setMediaError(cause instanceof Error ? cause.message : "News unavailable.");
    }).finally(() => {
      if (ticket === mediaGeneration.current) setMediaLoading(false);
    });
    return () => { controller.abort(); mediaGeneration.current += 1; };
  }, [client, timeline]);

  async function loadMoreMedia() {
    if (!client || !timeline || !media?.next_page || mediaLoading) return;
    const ticket = mediaGeneration.current;
    const page = media.next_page;
    setMediaLoading(true); setMediaError(null);
    try {
      const incoming = await client.media(timeline.time_cursor, page);
      if (ticket !== mediaGeneration.current) return;
      if (incoming.next_page === page) throw new Error("Invalid repeated media page.");
      setMedia((current) => current?.next_page === page
        ? { time_cursor: current.time_cursor, items: [...current.items, ...incoming.items], next_page: incoming.next_page }
        : current);
    } catch (cause) {
      if (ticket === mediaGeneration.current)
        setMediaError(cause instanceof Error ? cause.message : "Cannot load more news.");
    } finally {
      if (ticket === mediaGeneration.current) setMediaLoading(false);
    }
  }

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
    <header className="topbar">
      <a className="brand" href="#home" aria-label="NBA Time Machine home"><span className="brand-mark" aria-hidden="true">NBA</span><span>Time Machine</span></a>
      <span className="topbar-caption"><span className="topbar-dot" aria-hidden="true" />Scores stay hidden until you choose to reveal them.</span>
    </header>
    <main className="shell" id="home">
      <section className="intro" aria-labelledby="intro-heading">
        <div><p className="eyebrow">NBA / YOUR TIMELINE</p><h1 id="intro-heading">Find your next game.</h1></div>
        <p>Browse the schedule, save what looks good, and reveal only what you want to know.</p>
      </section>

      <section className="timeline-panel" aria-labelledby="timeline-heading">
        <div className="timeline-copy">
          <p className="eyebrow">Your NBA world · Eastern time</p>
          <h2 id="timeline-heading">{timeline ? formatTime(timeline.time_cursor) : newProfile ? "Set your starting time" : "Resuming your timeline…"}</h2>
          <p>Moving forward unlocks newer information. You can't move this timeline backward.</p>
        </div>
        {newProfile ? <div className="timeline-controls"><label>Starting time (UTC)<input type="datetime-local" value={initialCursor} disabled={busy} onChange={(e) => setInitialCursor(e.target.value)} /></label><button className="primary" type="button" disabled={busy || !initialCursor} onClick={() => void initialize()}>Start timeline</button></div> : timeline && <div className="timeline-controls">
          <button type="button" disabled={busy || loading} onClick={() => void advance(6)}>Advance 6 hours</button>
          <button className="primary" type="button" disabled={busy || loading} onClick={() => void advance(24)}>Advance 1 day</button>
          <button type="button" disabled={busy || loading || Date.parse(timeline.time_cursor) >= Date.now()} onClick={() => { if (window.confirm("Advance to now? This accepts all NBA information up to now and cannot be undone.")) void advance((Date.now() - Date.parse(timeline.time_cursor)) / 3_600_000); }}>Advance to now</button>
        </div>}
      </section>

      {error && <div className="notice error" role="alert">{error} <button type="button" disabled={busy} onClick={() => setReload((n) => n + 1)}>Reload saved state</button></div>}

      {timeline && <div className="dashboard-grid">
        <section className="games-section" aria-labelledby="games-heading">
          <div className="section-header">
            <div><p className="eyebrow">THE SCHEDULE</p><h2 id="games-heading">Games</h2></div>
            {!loading && slate && <span className="section-count" aria-live="polite">{slate.games.length} {slate.games.length === 1 ? "game" : "games"} shown</span>}
          </div>
          <div className="schedule-controls">
            <div className="date-control">
              <label htmlFor="nba-date">NBA date · Eastern</label>
              <div className="date-stepper">
                <button type="button" aria-label="Previous NBA date" title="Previous day" disabled={busy || day <= FIRST_NBA_DAY} onClick={() => selectDate(nextNbaDay(day, -1))}>←</button>
                <input id="nba-date" type="date" min={FIRST_NBA_DAY} max={LAST_NBA_DAY} value={day} disabled={busy} onChange={(e) => selectDate(e.target.value)} />
                <button type="button" aria-label="Next NBA date" title="Next day" disabled={busy || day >= LAST_NBA_DAY} onClick={() => selectDate(nextNbaDay(day, 1))}>→</button>
              </div>
            </div>
            <label className="schedule-view-label">Schedule view
              <select value={view} disabled={busy} onChange={(e) => selectView(e.target.value as ScheduleView)}>
                <option value="replay">Season replay</option>
                <option value="pregame">Historically observed pregame</option>
                <option value="observed">Observed schedule / backfill</option>
              </select>
            </label>
          </div>
          <p className="section-intro">{view === "replay" ? "Season replay shows retrospective matchups on their original dates, not reconstructed pregame knowledge. Coverage is partial." : view === "pregame" ? "Only pre-tip observations known at this point in your timeline appear here." : "Shows matchups once collected. Backfilled schedules aren't a reconstruction of what people knew before tip."} Results stay hidden until you explicitly open them.</p>
          {loading && <div className="empty-state" role="status">Loading games…</div>}
          {!loading && slate?.games.length === 0 && <div className="empty-state"><strong>No covered games for this date.</strong><p>{view === "replay" ? "Replay only shows games through your current NBA day." : view === "pregame" ? "This view needs pre-tip observations available at your cursor." : "This view needs a schedule observation available at your cursor."} It could also reflect missing provider coverage, not necessarily that no games were played.</p></div>}
          <div className="game-list">{slate?.games.map((game) => {
            const shown = disclosures[game.game_id] ?? {};
            return <article className="game-card" key={game.game_id}>
              <div className="game-meta">
                <span className="tip-time">{game.scheduled_tip ? formatTime(game.scheduled_tip) : "Tip time unavailable"}</span>
                <span className={"game-status " + (game.state === "sealed" ? "is-sealed" : "is-acknowledged")}>{game.state === "sealed" ? "Sealed" : "Acknowledged"}</span>
              </div>
              <h3>{matchup(game)}</h3>
              <p className="pregame-label">{game.pregame_interest !== undefined ? "Pregame interest · " + game.pregame_interest.toFixed(1) : "Pregame interest unavailable"}</p>
              <div className="game-actions">
                <button className="save-action" type="button" disabled={busy || loading || queueLoading || !queue} onClick={() => void editQueue(game.game_id, queuedIds.has(game.game_id) ? null : "queued")}>{queuedIds.has(game.game_id) ? "Remove from queue" : "Save to queue"}</button>
                <button className="hint-action" type="button" aria-describedby={"hint-caution-" + game.game_id} disabled={busy || loading} onClick={() => void disclose(game, "watchability")}>Show watchability hint</button>
                <button className="danger-link" type="button" disabled={busy || loading} onClick={() => setConfirming({ gameId: game.game_id, from: "slate" })}>Reveal result</button>
              </div>
              <p className="hint-caution" id={"hint-caution-" + game.game_id}>Watchability hints may spoil surprises.</p>
              {(shown.verdict || shown.reason) && !shown.full && <div className="disclosure-box" aria-live="polite">
                <p className="box-kicker">Watchability hint · may imply what happened</p>
                <strong>{shown.reason?.watchability_verdict ?? shown.verdict?.watchability_verdict ?? "Watchability data is unavailable"}</strong>
                {shown.reason?.watchability_reason && <p>{shown.reason.watchability_reason}</p>}
                {!shown.reason && shown.verdict?.watchability_verdict && <button className="text-action" disabled={busy} onClick={() => void disclose(game, "why")}>Why? Show one more hint →</button>}
              </div>}
              {confirming?.gameId === game.game_id && confirming.from === "slate" && <div className="confirmation" role="group" aria-label="Confirm result reveal"><p><strong>Reveal this game's score?</strong> This acknowledges the game but leaves your timeline where it is.</p><div className="confirmation-actions"><button className="confirm-button" disabled={busy} onClick={() => void disclose(game, "full")}>Yes, reveal score</button><button disabled={busy} onClick={() => setConfirming(null)}>Keep result hidden</button></div></div>}
              {shown.full && <div className="result-box" aria-live="polite"><p className="box-kicker">Revealed for this game only</p><strong>{game.away_team} {shown.full.away_score ?? "–"} — {shown.full.home_score ?? "–"} {game.home_team}</strong>{shown.full.result && <p>{shown.full.result}</p>}</div>}
            </article>;
          })}</div>
        </section>
        <aside className="side-column" aria-label="Viewing tools">
          <section className="side-panel watch-panel" aria-labelledby="guide-heading">
            <p className="eyebrow">THE VIEWING GUIDE</p><h2 id="guide-heading">What should I watch?</h2>
            <p className="side-description">Before tip-off, these are the games with the most pregame interest.</p>
            <div className="guide-pick">{recommended[0] ? <><p className="box-kicker">Top pregame pick</p><strong>{matchup(recommended[0])}</strong></> : <p>No pregame recommendation available for this date.</p>}</div>
            <div className="guide-postgame"><h3>After-the-game picks</h3><p>Optional: rank by how good games turned out, without showing scores. The ordering itself can be a hint.</p>
              {view !== "pregame" ? <p className="muted-note">Switch to Historically observed pregame to request these picks.</p> : <>
                <label className="ranking-consent"><input type="checkbox" checked={rankingConsent} disabled={busy || loading} onChange={(e) => setRankingConsent(e.target.checked)} /><span>I accept outcome-based hints for this request.</span></label>
                <button className="guide-button" disabled={busy || loading || !rankingConsent || !slate?.games.length} onClick={() => void recommend()}>Rank by watchability</button>
              </>}
              {watchPicks !== null && <div className="guide-results" aria-live="polite">{watchPicks.length ? <ol>{watchPicks.map((game) => <li key={game.game_id}>{matchup(game)}</li>)}</ol> : <p>No eligible picks for this request. Watchability data is unavailable; this is not a poor-quality verdict.</p>}</div>}
            </div>
          </section>
          <section className="side-panel queue-panel" aria-labelledby="queue-heading">
            <div className="side-heading"><div><p className="eyebrow">YOUR SHORTLIST</p><h2 id="queue-heading">Watch Queue</h2></div>{queue && <span className="queue-count">{queue.items.length}</span>}</div>
            <p className="side-description">Save games for later. Your plans never reveal scores or change your timeline.</p>
            {queueError && <p role="alert">Watch Queue: {queueError} <button disabled={busy} onClick={() => setReload((n) => n + 1)}>Reload saved state</button></p>}
            {queueLoading && <p role="status">Loading Watch Queue…</p>}
            {!queueLoading && queue?.items.length === 0 && <p className="subtle-empty">No games saved yet. Use “Save to queue” on a matchup.</p>}
            <ol className="queue-list">{queue?.items.map((item) => {
              const game = item.game;
              const shown = disclosures[item.game_id] ?? {};
              return <li key={item.game_id} className="queue-item">
                <strong>{game ? matchup(game) : "Saved game"}</strong>
                <p className="small-label">{game ? (game.scheduled_tip ? formatTime(game.scheduled_tip) : "Tip unavailable") + " · " + (game.state === "sealed" ? "Sealed" : "Acknowledged") : "Game details unavailable at this cursor."}</p>
                <div className="queue-actions">
                  <label>My plan <select aria-label="My plan" value={item.queue_state} disabled={busy} onChange={(e) => void editQueue(item.game_id, e.target.value as QueueState)}><option value="queued">Queued</option><option value="done">Done</option><option value="dismissed">Dismissed</option></select></label>
                  <button type="button" disabled={busy} onClick={() => void editQueue(item.game_id, null)}>Remove</button>
                  {game && <button className="danger-link" type="button" disabled={busy} onClick={() => setConfirming({ gameId: item.game_id, from: "queue" })}>Reveal result</button>}
                </div>
                {game && confirming?.gameId === item.game_id && confirming.from === "queue" && <div className="confirmation" role="group" aria-label="Confirm queue result reveal"><p>Reveal this game's score separately from your queue plan? Your timeline won't move.</p><div className="confirmation-actions"><button className="confirm-button" disabled={busy} onClick={() => void disclose(game, "full")}>Yes, reveal score</button><button disabled={busy} onClick={() => setConfirming(null)}>Keep result hidden</button></div></div>}
                {game && shown.full && <div className="result-box"><strong>{game.away_team} {shown.full.away_score ?? "–"} — {shown.full.home_score ?? "–"} {game.home_team}</strong></div>}
              </li>;
            })}</ol>
          </section>
          <section className="side-panel favorites-panel"><p className="eyebrow">PERSONAL VIEW</p><h2>Favorite teams</h2><p className="side-description">Mark teams on this slate. This doesn't change the watchability ranking.</p>{teams.length ? <div className="favorite-choices">{teams.map((team) => <label key={team}><input type="checkbox" checked={favorites.includes(team)} onChange={() => setFavorites((prior) => prior.includes(team) ? prior.filter((name) => name !== team) : [...prior, team])} /><span>{team}</span></label>)}</div> : <p className="subtle-empty">Teams appear when a slate loads.</p>}</section>
        </aside>
        <section className="media-section" aria-labelledby="media-heading">
          <div className="section-header"><div><p className="eyebrow">REVIEWED COVERAGE</p><h2 id="media-heading">News &amp; buzz</h2></div>{media?.items.length ? <button type="button" className="secondary-button" onClick={() => setMediaExpanded((value) => !value)}>{mediaExpanded ? "Show fewer" : "Explore News & Buzz"}</button> : null}</div>
          <p className="section-intro">News is limited to what was verified as known at your timeline cursor. Revealing one game doesn't unlock newer headlines.</p>
          {mediaError && <p role="alert">News &amp; Buzz: {mediaError} <button onClick={() => setReload((n) => n + 1)}>Reload saved state</button></p>}
          {mediaLoading && !media && <p role="status">Loading reviewed news…</p>}
          {!mediaLoading && media?.items.length === 0 && <div className="empty-state"><strong>No reviewed news available yet.</strong><p>Source collection or review coverage may be missing at this point in your timeline.</p></div>}
          <div className="media-list">{(mediaExpanded ? media?.items : media?.items.slice(0, 3))?.map((item) =>
            <article className="media-item" key={item.item_id}>
              <div><p className="small-label">{item.media_type ?? "Article"} · {item.source ?? "Reviewed source"}{item.known_at ? " · Known " + formatTime(item.known_at) : ""}</p>
                <h3>{item.url ? <a href={item.url} target="_blank" rel="noopener noreferrer">{item.headline}</a> : item.headline}</h3>
                {item.excerpt && <p>{item.excerpt}</p>}
              </div>
            </article>)}</div>
          {mediaExpanded && media?.next_page && <button className="secondary-button" disabled={mediaLoading} onClick={() => void loadMoreMedia()}>{mediaLoading ? "Loading…" : "Load more reviewed news"}</button>}
        </section>
      </div>}
      {!timeline && loading && <p className="startup-status" role="status">Connecting to backend…</p>}
      <footer className="footer"><span>NBA Time Machine</span><span>Partial season coverage · Your timeline only moves forward</span></footer>
    </main>
  </div>;
}
