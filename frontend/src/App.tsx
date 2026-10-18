import { useEffect, useMemo, useRef, useState } from "react";
import { BackendClient, nbaDate, profileIdentity } from "./api";
import type { ScheduleView, Timeline } from "./api";
import { orderByPregameInterest } from "./dashboard";
import type { FullReveal, GameCard, GameList, MediaFeed, Reason, Verdict } from "./dashboard";
import { NBA_TEAMS, isFavoriteGame, readFavorites, visibleWatchOrder, writeFavorites } from "./favorites";

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
  const [includeFavorites, setIncludeFavorites] = useState(false);
  const [watchPicks, setWatchPicks] = useState<GameCard[] | null>(null);
  const [rankingConsent, setRankingConsent] = useState(false);
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
        setFavorites(readFavorites(window.localStorage, connected.profileId));
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

  function toggleFavorite(team: string) {
    if (!client) return;
    const next = favorites.includes(team) ? favorites.filter((name) => name !== team) : [...favorites, team];
    try {
      writeFavorites(window.localStorage, client.profileId, next);
      setFavorites(next);
    } catch {
      setError("Could not save your teams in this browser.");
    }
  }
  const visiblePicks = watchPicks === null ? null : visibleWatchOrder(watchPicks, favorites, includeFavorites);
  const recommended = useMemo(() => orderByPregameInterest((slate?.games ?? []).filter((game) => game.pregame_interest !== undefined)), [slate]);
  const visiblePregamePicks = visibleWatchOrder(recommended, favorites, includeFavorites);
  return <div className="app">
    <header className="topbar">
      <a className="brand" href="#home" aria-label="NBA Time Machine home"><span className="brand-mark" aria-hidden="true">NBA</span><span>Time Machine</span></a>
      <span className="topbar-caption"><span className="topbar-dot" aria-hidden="true" />Scores stay hidden until you choose to reveal them.</span>
    </header>
    <main className="shell" id="home">
      <section className="intro" aria-labelledby="intro-heading">
        <div><p className="eyebrow">NBA / GAMES</p><h1 id="intro-heading">Find a game worth watching.</h1></div>
        <p>Choose a date. Scores stay hidden until you ask.</p>
      </section>

      <section className={"timeline-panel" + (newProfile ? " needs-setup" : "")} aria-labelledby="timeline-heading">
        <div className="timeline-copy">
          <p className="eyebrow">Time Machine · information cutoff</p>
          <h2 id="timeline-heading">{timeline ? formatTime(timeline.time_cursor) : newProfile ? "Set your starting time" : "Resuming your timeline…"}</h2>
          <p>Your time cutoff protects future information. Imported schedules may include games collected later.</p>
        </div>
        {newProfile ? <div className="timeline-controls"><label>Starting time (UTC)<input type="datetime-local" value={initialCursor} disabled={busy} onChange={(e) => setInitialCursor(e.target.value)} /></label><button className="primary" type="button" disabled={busy || !initialCursor} onClick={() => void initialize()}>Start timeline</button></div> : timeline && <details className="timeline-details"><summary>Adjust cutoff</summary><div className="timeline-controls">
          <button type="button" disabled={busy || loading} onClick={() => void advance(6)}>Advance 6 hours</button>
          <button className="primary" type="button" disabled={busy || loading} onClick={() => void advance(24)}>Advance 1 day</button>
          <button type="button" disabled={busy || loading || Date.parse(timeline.time_cursor) >= Date.now()} onClick={() => { if (window.confirm("Advance to now? This accepts all NBA information up to now and cannot be undone.")) void advance((Date.now() - Date.parse(timeline.time_cursor)) / 3_600_000); }}>Advance to now</button>
        </div></details>}
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
              <label htmlFor="nba-date">Game date · Eastern</label>
              <div className="date-stepper">
                <button type="button" aria-label="Previous NBA date" title="Previous day" disabled={busy || day <= FIRST_NBA_DAY} onClick={() => selectDate(nextNbaDay(day, -1))}>←</button>
                <input id="nba-date" type="date" min={FIRST_NBA_DAY} max={LAST_NBA_DAY} value={day} disabled={busy} onChange={(e) => selectDate(e.target.value)} />
                <button type="button" aria-label="Next NBA date" title="Next day" disabled={busy || day >= LAST_NBA_DAY} onClick={() => selectDate(nextNbaDay(day, 1))}>→</button>
              </div>
            </div>
            <details className="advanced-schedule"><summary>Coverage options</summary>
              <label className="schedule-view-label">Available schedule data
                <select value={view} disabled={busy} onChange={(e) => selectView(e.target.value as ScheduleView)}>
                  <option value="replay">Imported games</option>
                  <option value="pregame">Verified pregame records</option>
                  <option value="observed">Latest collected schedule</option>
                </select>
              </label>
              <p>Imported past games may reflect later corrections. This does not change your saved information cutoff.</p>
            </details>
          </div>
          <p className="section-intro">Schedule coverage may be incomplete. Results remain hidden unless you choose to see them.</p>
          {loading && <div className="empty-state" role="status">Loading games…</div>}
          {!loading && slate?.games.length === 0 && <div className="empty-state"><strong>No covered games for this date.</strong><p>{view === "replay" ? "Only dates up to your information cutoff are available here." : view === "pregame" ? "No verified pre-tip records were collected for this date and cutoff." : "No schedule was collected by your information cutoff."} It could also reflect missing provider coverage, not necessarily that no games were played.</p></div>}
          <div className="game-list">{slate?.games.map((game) => {
            const shown = disclosures[game.game_id] ?? {};
            return <article className={"game-card" + (isFavoriteGame(game, favorites) ? " favorite-game" : "")} key={game.game_id}>
              <div className="game-meta">
                <span className="tip-time">{game.scheduled_tip ? formatTime(game.scheduled_tip) : "Tip time unavailable"}</span>
                <span className="game-meta-end">{isFavoriteGame(game, favorites) && <span className="favorite-marker">Your team</span>}<span className={"game-status " + (game.state === "sealed" ? "is-sealed" : "is-acknowledged")}>{game.state === "sealed" ? "Score hidden" : "Score revealed"}</span></span>
              </div>
              <h3>{matchup(game)}</h3>
              <p className="pregame-label">{game.pregame_interest !== undefined ? "Pregame interest · " + game.pregame_interest.toFixed(1) : "Pregame interest unavailable"}</p>
              <div className="game-actions">
                <button className="hint-action" type="button" aria-describedby={"hint-caution-" + game.game_id} disabled={busy || loading} onClick={() => void disclose(game, "watchability")}>Worth watching?</button>
                <button className="danger-link" type="button" disabled={busy || loading} onClick={() => setConfirming({ gameId: game.game_id, from: "slate" })}>Show score</button>
              </div>
              <p className="hint-caution" id={"hint-caution-" + game.game_id}>This hint uses what happened during the game and may spoil a surprise.</p>
              {(shown.verdict || shown.reason) && !shown.full && <div className="disclosure-box" aria-live="polite">
                <p className="box-kicker">After-the-game verdict · spoiler hint</p>
                <strong>{shown.reason?.watchability_verdict ?? shown.verdict?.watchability_verdict ?? "Watchability data is unavailable"}</strong>
                {shown.reason?.watchability_reason && <p>{shown.reason.watchability_reason}</p>}
              </div>}
              {confirming?.gameId === game.game_id && confirming.from === "slate" && <div className="confirmation" role="group" aria-label="Confirm result reveal"><p><strong>Show the final score for this game?</strong> This doesn't change your information cutoff.</p><div className="confirmation-actions"><button className="confirm-button" disabled={busy} onClick={() => void disclose(game, "full")}>Yes, show score</button><button disabled={busy} onClick={() => setConfirming(null)}>Keep result hidden</button></div></div>}
              {shown.full && <div className="result-box" aria-live="polite"><p className="box-kicker">Revealed for this game only</p><strong>{game.away_team} {shown.full.away_score ?? "–"} — {shown.full.home_score ?? "–"} {game.home_team}</strong>{shown.full.result && <p>{shown.full.result}</p>}</div>}
            </article>;
          })}</div>
        </section>
        <aside className="side-column" aria-label="Viewing tools">
          <section className="side-panel watch-panel" aria-labelledby="guide-heading">
            <p className="eyebrow">THE VIEWING GUIDE</p><h2 id="guide-heading">What should I watch?</h2>
            <p className="side-description">Before tip-off, these are the games with the most pregame interest.</p>
            <div className="guide-pick">{visiblePregamePicks[0] ? <><p className="box-kicker">Top pregame pick</p><strong>{matchup(visiblePregamePicks[0])}</strong></> : recommended.length ? <p>All pregame picks feature your teams. Include your teams to see them here.</p> : <p>No pregame recommendation available for this date.</p>}</div>
            <div className="guide-postgame"><h3>After-the-game picks</h3><p>Optional: rank by how good games turned out, without showing scores. The ordering itself can be a hint.</p>
              {view !== "pregame" ? <p className="muted-note">Postgame rankings are unavailable for this schedule. Individual game verdicts may still be available.</p> : <>
                <label className="ranking-consent"><input type="checkbox" checked={rankingConsent} disabled={busy || loading} onChange={(e) => setRankingConsent(e.target.checked)} /><span>I accept outcome-based hints for this request.</span></label>
                <button className="guide-button" disabled={busy || loading || !rankingConsent || !slate?.games.length} onClick={() => void recommend()}>Rank by watchability</button>
              </>}
              <label className="include-favorites"><input type="checkbox" checked={includeFavorites} onChange={(e) => setIncludeFavorites(e.target.checked)} /> Include my teams in the watch order</label>
              {visiblePicks !== null && <div className="guide-results" aria-live="polite">{visiblePicks.length ? <ol>{visiblePicks.map((game) => <li key={game.game_id}>{matchup(game)}</li>)}</ol> : watchPicks?.length ? <p>All ranked games feature your teams. Select “Include my teams” to see them here.</p> : <p>No eligible picks for this request. Watchability data is unavailable; this is not a poor-quality verdict.</p>}</div>}
            </div>
          </section>
          <section className="side-panel favorites-panel">
            <p className="eyebrow">YOUR TEAMS</p><h2>My teams</h2>
            <p className="side-description">Follow the teams you care about. This never changes how good a game is rated.</p>
            {favorites.length > 0 ? <div className="selected-teams">{favorites.map((team) => <span key={team}>{team}</span>)}</div> : <p className="subtle-empty">No favorites yet.</p>}
            <details className="team-picker">
              <summary>Choose teams ({favorites.length} selected)</summary>
              <div className="favorite-choices">{NBA_TEAMS.map((team) => <label key={team}><input type="checkbox" checked={favorites.includes(team)} onChange={() => toggleFavorite(team)} /><span>{team}</span></label>)}</div>
            </details>
          </section>
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
