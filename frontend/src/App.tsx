import { useDayUpdate } from "./useDayUpdate";
import { savedUpdate, updateFailure } from "./dayUpdate";
import { useEffect, useRef, useState } from "react";
import { BackendClient, nbaDate, profileIdentity, type Timeline } from "./api";
import type { GameCard, MediaFeed } from "./dashboard";
import type { Detail, Level, Mode } from "./guide";
import {
  NBA_TEAMS,
  isFavoriteGame,
  readFavorites,
  visibleWatchOrder,
  writeFavorites,
} from "./favorites";

const FIRST = "2025-07-01",
  LAST = "2027-06-30";
const today = () => nbaDate(new Date().toISOString());
const step = (day: string, n: number) =>
  new Date(Date.parse(day + "T12:00:00Z") + n * 86400000)
    .toISOString()
    .slice(0, 10);
const matchup = (g: GameCard) => `${g.away_team} at ${g.home_team}`;
const time = (iso: string) =>
  new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso)) + " ET";
const tip = (iso?: string) =>
  iso
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "2-digit",
      }).format(new Date(iso)) + " ET"
    : "Time unavailable";

export function App() {
  const [client, setClient] = useState<BackendClient | null>(null);
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [mode, setMode] = useState<Mode>("browse");
  const [day, setDay] = useState(today);
  const [cutoff, setCutoff] = useState(() =>
    new Date().toISOString().slice(0, 16),
  );
  const [slate, setSlate] = useState<import("./guide").GuideList | null>(null);
  const [details, setDetails] = useState<Record<string, Detail>>({});
  const [order, setOrder] = useState<string[] | null>(null);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [include, setInclude] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [media, setMedia] = useState<MediaFeed | null>(null);
  const [news, setNews] = useState(false);
  const [mediaError, setMediaError] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const update = useDayUpdate(client, day, mode, timeline?.time_cursor);
  const generation = useRef(0);
  const loadedLevels = useRef<Record<string, number>>({});
  const loadedOrder = useRef(false);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const revealTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
  }, [confirming]);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    (async () => {
      const connected = new BackendClient(profileIdentity(window.localStorage));
      const saved =
        (await connected.resume(controller.signal)) ??
        (await connected.initialize("2025-07-01T04:00:00Z"));
      if (!alive) return;
      const pendingUpdate = savedUpdate(
        window.localStorage,
        connected.profileId,
      );
      if (
        pendingUpdate &&
        pendingUpdate.date >= FIRST &&
        pendingUpdate.date <= LAST &&
        pendingUpdate.date <= today()
      ) {
        setDay(pendingUpdate.date);
      }
      setClient(connected);
      setTimeline(saved);
      setCutoff(new Date(saved.time_cursor).toISOString().slice(0, 16));
      setFavorites(readFavorites(window.localStorage, connected.profileId));
    })().catch(() => {
      if (alive) {
        setError("Backend database unavailable. Try reloading saved state.");
        setLoading(false);
      }
    });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [reload]);

  useEffect(() => {
    if (!client || !timeline) return;
    const controller = new AbortController(),
      ticket = ++generation.current;
    setLoading(true);
    setSlate(null);
    setDetails({});
    loadedLevels.current = {};
    loadedOrder.current = false;
    setOrder(null);
    setConfirming(null);
    setError(null);
    client
      .guideGames(day, mode, timeline.time_cursor, controller.signal)
      .then((data) => {
        if (ticket === generation.current) setSlate(data);
      })
      .catch((cause) => {
        if (!controller.signal.aborted && ticket === generation.current)
          setError(cause.message);
      })
      .finally(() => {
        if (ticket === generation.current) setLoading(false);
      });
    return () => {
      controller.abort();
      generation.current++;
    };
  }, [client, timeline, day, mode, update.version]);

  useEffect(() => {
    if (!news || !client || !timeline) return;
    const controller = new AbortController();
    setMedia(null);
    setMediaError(false);
    client
      .media(timeline.time_cursor, undefined, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setMedia(data);
      })
      .catch(() => {
        if (!controller.signal.aborted) setMediaError(true);
      });
    return () => controller.abort();
  }, [news, client, timeline]);

  function reset() {
    generation.current++;
    setSlate(null);
    setDetails({});
    loadedLevels.current = {};
    loadedOrder.current = false;
    setOrder(null);
    setConfirming(null);
    setError(null);
  }
  function selectDate(value: string) {
    if (value !== day && value >= FIRST && value <= LAST) {
      reset();
      setDay(value);
    }
  }
  function selectMode(value: Mode) {
    if (value === mode) return;
    reset();
    setMode(value);
  }
  function cancelReveal() {
    setConfirming(null);
    revealTrigger.current?.focus();
  }
  async function disclose(level: Level, gameId?: string) {
    if (!client || !slate || busy) return;
    const depth = { verdict: 1, clue: 2, rating: 3, full: 4, order: 0 }[level];
    const ids = gameId ? [gameId] : slate.games.map((g) => g.game_id);
    const alreadyLoaded = level === "order"
      ? loadedOrder.current
      : (gameId !== undefined || loadedOrder.current) &&
        ids.every((id) => (loadedLevels.current[id] ?? 0) >= depth);
    if (alreadyLoaded) {
      setError(null);
      setConfirming(null);
      if (gameId && level === "full") revealTrigger.current?.focus();
      return;
    }
    const ticket = generation.current;
    setBusy(true);
    setError(null);
    try {
      const response = await client.guideDisclosure(
        slate,
        day,
        mode,
        level,
        gameId,
      );
      if (ticket !== generation.current) return;
      if (level !== "order") {
        for (const id of ids) loadedLevels.current[id] = Math.max(loadedLevels.current[id] ?? 0, depth);
      }
      if (!gameId) loadedOrder.current = true;
      setDetails((prior) => {
        const next = { ...prior };
        for (const [id, d] of Object.entries(response.details)) next[id] = { ...prior[id], ...d };
        return next;
      });
      if (!gameId) setOrder(response.game_ids);
      setConfirming(null);
      if (gameId && level === "full") revealTrigger.current?.focus();
    } catch (cause) {
      if (ticket === generation.current)
        setError(
          cause instanceof Error ? cause.message : "Details unavailable.",
        );
    } finally {
      setBusy(false);
    }
  }
  async function advance() {
    if (!client || !timeline || !cutoff) return;
    const requested = new Date(cutoff + ":00Z").toISOString();
    if (
      Date.parse(requested) <= Date.parse(timeline.time_cursor) ||
      Date.parse(requested) > Date.now()
    ) {
      setError("Choose a later cutoff, up to now.");
      return;
    }
    if (
      !window.confirm(
        "Move your Time Machine forward? This accepts information up to this time and cannot be undone.",
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      setTimeline(
        await client.advance(
          timeline.time_cursor,
          (Date.parse(requested) - Date.parse(timeline.time_cursor)) / 3600000,
        ),
      );
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not advance cutoff.",
      );
    } finally {
      setBusy(false);
    }
  }
  function toggle(team: string) {
    if (!client) return;
    const next = favorites.includes(team)
      ? favorites.filter((t) => t !== team)
      : [...favorites, team];
    try {
      writeFavorites(window.localStorage, client.profileId, next);
      setFavorites(next);
    } catch {
      setError("Could not save your teams in this browser.");
    }
  }
  const ranked =
    order
      ?.map((id) => slate?.games.find((g) => g.game_id === id))
      .filter((g): g is GameCard => !!g) ?? [];
  const picks = visibleWatchOrder(ranked, favorites, include);
  const myGames =
    slate?.games.filter((g) => isFavoriteGame(g, favorites)) ?? [];
  const before = visibleWatchOrder(
    (slate?.games ?? [])
      .filter((g) => slate?.expectations?.[g.game_id] !== undefined || g.pregame_interest !== undefined)
      .sort((a, b) => (slate?.expectations?.[b.game_id]?.rating ?? b.pregame_interest ?? 0) -
        (slate?.expectations?.[a.game_id]?.rating ?? a.pregame_interest ?? 0)),
    favorites,
    include,
  );
  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#home">
          <span className="brand-mark" aria-hidden="true">
            TM
          </span>
          <span>
            NBA <b>Time Machine</b>
          </span>
        </a>
        <span className="topbar-caption">Basketball, on your time.</span>
      </header>
      <main className="shell" id="home">
        <div className="page-heading">
          <div>
            <p className="eyebrow">YOUR DAILY VIEWING GUIDE</p>
            <h1>Good games. Zero surprises.</h1>
          </div>
          <nav className="mode-switch" aria-label="Viewing mode">
            <button
              aria-pressed={mode === "browse"}
              disabled={busy}
              onClick={() => selectMode("browse")}
            >
              Browse games
            </button>
            <button
              aria-pressed={mode === "time-machine"}
              disabled={busy}
              onClick={() => selectMode("time-machine")}
            >
              Time Machine
            </button>
          </nav>
        </div>
        {mode === "time-machine" && (
          <section
            className="time-machine-panel"
            aria-label="Time Machine cutoff"
          >
            <div>
              <p className="eyebrow">INFORMATION STOPS HERE</p>
              <strong>
                {timeline ? time(timeline.time_cursor) : "Connecting…"}
              </strong>
              <p>
                Only information known by this cutoff. Moving forward cannot be
                undone.
              </p>
            </div>
            <div className="cutoff-controls">
              <label htmlFor="cutoff">New cutoff (UTC)</label>
              <input
                id="cutoff"
                type="datetime-local"
                value={cutoff}
                onChange={(e) => setCutoff(e.target.value)}
              />
              <button
                disabled={busy || !timeline}
                onClick={() => void advance()}
              >
                Move forward
              </button>
            </div>
          </section>
        )}
        {error && (
          <div className="notice error" role="alert">
            {error}{" "}
            <button
              disabled={busy}
              onClick={() => {
                reset();
                setReload((n) => n + 1);
              }}
            >
              Reload saved state
            </button>
          </div>
        )}
        <div className="date-bar">
          <div className="date-control">
            <label htmlFor="nba-date">Game date · Eastern</label>
            <div className="date-stepper">
              <button
                aria-label="Previous NBA date"
                disabled={busy || day <= FIRST}
                onClick={() => selectDate(step(day, -1))}
              >
                ←
              </button>
              <input
                id="nba-date"
                type="date"
                min={FIRST}
                max={LAST}
                value={day}
                disabled={busy}
                onInput={(e) => selectDate(e.currentTarget.value)}
                onChange={(e) => selectDate(e.target.value)}
              />
              <button
                aria-label="Next NBA date"
                disabled={busy || day >= LAST}
                onClick={() => selectDate(step(day, 1))}
              >
                →
              </button>
            </div>
          </div>
          <button
            className="today-button"
            disabled={busy}
            onClick={() => selectDate(today())}
          >
            Today
          </button>
          <span className="season-label">
            {Number(day.slice(5, 7)) >= 7
              ? day.slice(0, 4)
              : Number(day.slice(0, 4)) - 1}
            /
            {String(
              Number(day.slice(0, 4)) + (Number(day.slice(5, 7)) >= 7 ? 1 : 0),
            ).slice(2)}{" "}
            season
          </span>
          {mode === "browse" && day <= today() && (
            <button
              className="fetch-day"
              disabled={busy || !timeline || update.active}
              onClick={() => void update.start()}
            >
              {update.active
                ? "Updating this date…"
                : "Fetch games & update ratings"}
            </button>
          )}
          <button
            className="reveal-all"
            disabled={busy || loading || !slate?.games.length}
            onClick={() => void disclose("full")}
          >
            Reveal all for this date
          </button>
        </div>
        {mode === "browse" && (update.job || update.error) && (
          <div
            className="update-status"
            role={
              update.error || update.job?.state === "failed"
                ? "alert"
                : "status"
            }
            aria-live="polite"
          >
            {update.error ??
              (update.job?.state === "collecting"
                ? "Fetching game evidence…"
                : update.job?.state === "publishing"
                  ? "Updating verified ratings…"
                  : update.job?.state === "failed"
                    ? updateFailure(update.job.error)
                    : "Date updated. Choose a spoiler option to see available ratings. Completed, verified evidence is required; some games may remain unrated.")}
          </div>
        )}
        {mode === "time-machine" && (
          <p className="coverage-note">
            To fetch fresh data, switch to Browse games. Fetching never moves
            this cutoff.
          </p>
        )}
        <div className="dashboard-grid">
          <section className="games-section" aria-labelledby="games-heading">
            <div className="section-header">
              <h2 id="games-heading">
                Games{" "}
                <span className="section-count">
                  {slate?.games.length ?? ""}
                </span>
              </h2>
              <span className="privacy-note">
                Scores hidden until you choose
              </span>
            </div>
            {loading && (
              <div className="empty-state" role="status">
                {timeline ? "Loading games…" : "Connecting to backend…"}
              </div>
            )}
            {!loading && slate?.games.length === 0 && (
              <div className="empty-state">
                <strong>No covered games for this date.</strong>
                <p>
                  {mode === "time-machine"
                    ? "No schedule is available at this cutoff."
                    : "Schedule coverage may be missing."}{" "}
                  This does not confirm an empty NBA day.
                </p>
              </div>
            )}
            <div className="game-list">
              {slate?.games.map((g) => {
                const d = details[g.game_id];
                const expectation = slate.expectations?.[g.game_id];
                const records = slate.entering_records?.[g.game_id]?.teams ??
                  (expectation && expectation.coverage !== "stars-only" ? expectation.teams : undefined);
                return (
                  <article
                    className={
                      "game-card" +
                      (isFavoriteGame(g, favorites) ? " favorite-game" : "")
                    }
                    key={g.game_id}
                  >
                    <div className="game-meta">
                      <span className="tip-time">{tip(g.scheduled_tip)}</span>
                      <span className="game-meta-end">
                        {isFavoriteGame(g, favorites) && (
                          <span className="favorite-marker">My team</span>
                        )}
                        <span className="game-status">
                          {d?.result ? "Score shown" : "Score hidden"}
                        </span>
                      </span>
                    </div>
                    <h3>
                      <span>{g.away_team}</span>
                      <small>at</small>
                      <span>{g.home_team}</span>
                    </h3>
                    <div className="pregame-expectation">
                      <p className="pregame-label">
                        Pregame expectation · {expectation ? `${expectation.rating.toFixed(1)} / 10` :
                          g.pregame_interest !== undefined ? `${g.pregame_interest.toFixed(1)} / 10` : "Not available"}
                      </p>
                      {records && <p className="pregame-records">{records.map(t => `${t.team} ${t.wins}–${t.losses}`).join(" · ")}</p>}
                      {expectation ? <>
                        {expectation.star_power && <div className="pregame-stars">
                          {expectation.star_power.teams.map(t => t.players.length > 0 && <p key={t.team}>{t.team}: {t.players.map(p => p.name).join(", ")}</p>)}
                        </div>}
                      </> : <p className="muted-note">{mode === "time-machine" ?
                        "No pregame rating at this cutoff." : "No pregame rating yet."}</p>}

                    </div>
                    <div className="game-actions">
                      <button
                        disabled={busy || loading}
                        onClick={() => void disclose("verdict", g.game_id)}
                      >
                        Worth watching?
                      </button>
                      <button
                        className="danger-link"
                        disabled={busy || loading}
                        onClick={(e) => {
                          revealTrigger.current = e.currentTarget;
                          setConfirming(g.game_id);
                        }}
                      >
                        Show result
                      </button>
                    </div>
                    {d && (
                      <div className="disclosure-box" aria-live="polite">
                        <p className="box-kicker">
                          After the game · spoiler details
                        </p>
                        <strong>
                          {d.verdict ??
                            "Unrated — verified rating evidence unavailable"}
                        </strong>
                        {d.verdict && (
                          <div className="detail-actions">
                            {d.has_clue && !d.clue && (
                              <button
                                disabled={busy}
                                onClick={() => void disclose("clue", g.game_id)}
                              >
                                Give me a clue
                              </button>
                            )}
                            {d.rating === undefined && (
                              <button
                                disabled={busy}
                                onClick={() =>
                                  void disclose("rating", g.game_id)
                                }
                              >
                                Show rating &amp; why
                              </button>
                            )}
                          </div>
                        )}
                        {d.verdict && !d.has_clue && (
                          <p className="muted-note">
                            No verified clue available.
                          </p>
                        )}
                        {d.clue && <p>{d.clue}</p>}
                        {d.rating !== undefined && (
                          <div className="rating-breakdown">
                            <div className="rating-total">
                              <strong>
                                {d.rating.toFixed(1)}
                                <small> / 10</small>
                              </strong>
                              <span>Why this rating?</span>
                            </div>
                            <ul>
                              {d.components?.map((p) => (
                                <li key={p.label}>
                                  <span>{p.label}</span>
                                  <meter
                                    min="0"
                                    max="10"
                                    value={p.points}
                                    aria-label={p.label + " contribution"}
                                  />
                                  <b>+{p.points.toFixed(2)}</b>
                                </li>
                              ))}
                            </ul>
                            <p className="muted-note">
                              Available components only. Provisional model;
                              missing evidence is not zero.
                            </p>
                            <details>
                              <summary>Rating evidence</summary>
                              <p>
                                {d.model} · {d.as_of && time(d.as_of)}
                              </p>
                              {d.components?.map((p) => (
                                <p key={p.source_ref + p.label}>
                                  {p.label}: {p.source_ref}
                                  <br />
                                  Known {time(p.available_at)} · Collected{" "}
                                  {time(p.observed_at)}
                                </p>
                              ))}
                            </details>
                          </div>
                        )}
                        {d.result && (
                          <div className="result-box">
                            <strong>
                              {g.away_team} {d.result.away_score} —{" "}
                              {d.result.home_score} {g.home_team}
                            </strong>
                          </div>
                        )}
                        {!d.result && d.rating === undefined && !d.verdict && (
                          <p className="muted-note">
                            Completed results may also be unavailable at this
                            date or cutoff.
                          </p>
                        )}
                      </div>
                    )}
                    {confirming === g.game_id && (
                      <div
                        className="confirmation"
                        role="group"
                        aria-label="Confirm result reveal"
                        onKeyDown={(e) => {
                          if (e.key === "Escape") cancelReveal();
                        }}
                      >
                        <p>
                          Show this game's result? Your Time Machine cutoff
                          stays the same.
                        </p>
                        <div className="confirmation-actions">
                          <button
                            ref={confirmRef}
                            disabled={busy}
                            onClick={() => void disclose("full", g.game_id)}
                          >
                            Yes, show result
                          </button>
                          <button onClick={cancelReveal}>
                            Keep result hidden
                          </button>
                        </div>
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
            <p className="coverage-note">
              Partial schedule coverage · Ratings use verified completed-game
              evidence. Browse dates never move your Time Machine.
            </p>
          </section>
          <aside className="side-column" aria-label="Viewing tools">
            <section className="side-panel watch-panel">
              <p className="eyebrow">MAKE IT A GOOD WATCH</p>
              <h2>Best games to watch</h2>
              <p className="side-description">
                Ask for a watch order based on what happened. The order itself
                can spoil a surprise.
              </p>
              <button
                className="guide-button"
                disabled={busy || loading || !slate?.games.length}
                onClick={() => void disclose("order")}
              >
                Show after-the-game watch order
              </button>
              <label className="include-favorites">
                <input
                  type="checkbox"
                  checked={include}
                  onChange={(e) => setInclude(e.target.checked)}
                />
                Include my teams
              </label>
              {order !== null && (
                <div className="guide-results" aria-live="polite">
                  {picks.length ? (
                    <ol>
                      {picks.map((g) => (
                        <li key={g.game_id}>{matchup(g)}</li>
                      ))}
                    </ol>
                  ) : (
                    <p>
                      {ranked.length
                        ? "Your teams are listed separately below. Include them to see their place in the watch order."
                        : "No verified ratings available. Unrated games are not poor games."}
                    </p>
                  )}
                  {(slate?.games.length ?? 0) > ranked.length && (
                    <p className="muted-note">
                      {(slate?.games.length ?? 0) - ranked.length} unrated.
                      Missing evidence never counts as a low rating.
                    </p>
                  )}
                </div>
              )}
              <div className="before-tip">
                <h3>Before tip-off</h3>
                {before.length ? (
                  <ol>
                    {before.map((g) => (
                      <li key={g.game_id}>{matchup(g)}</li>
                    ))}
                  </ol>
                ) : (
                  <p>No trustworthy pregame recommendations for this date.</p>
                )}
              </div>
              {!include && myGames.length > 0 && (
                <div className="my-games">
                  <h3>Your teams on this date</h3>
                  {myGames.map((g) => (
                    <p key={g.game_id}>{matchup(g)}</p>
                  ))}
                </div>
              )}
            </section>
            <section className="side-panel favorites-panel">
              <p className="eyebrow">FANDOM IS PERSONAL</p>
              <h2>My teams</h2>
              <p className="side-description">
                Your teams get their own space. Every game's rating stays the
                same.
              </p>
              <div className="selected-teams">
                {favorites.map((t) => (
                  <span key={t}>{t}</span>
                ))}
              </div>
              <details className="team-picker">
                <summary>Choose teams ({favorites.length} selected)</summary>
                <div className="favorite-choices">
                  {NBA_TEAMS.map((t) => (
                    <label key={t}>
                      <input
                        type="checkbox"
                        checked={favorites.includes(t)}
                        onChange={() => toggle(t)}
                      />
                      <span>{t}</span>
                    </label>
                  ))}
                </div>
              </details>
              <p className="muted-note">
                Saved for this profile in this browser.
              </p>
            </section>
          </aside>
        </div>
        <section className="news-secondary">
          <button aria-expanded={news} onClick={() => setNews((v) => !v)}>
            News &amp; buzz {news ? "−" : "+"}
          </button>
          {news && (
            <div>
              <p>
                Headlines follow your saved Time Machine cutoff
                {timeline ? ` (${time(timeline.time_cursor)})` : ""}. Game
                reveals never unlock newer news.
              </p>
              {mediaError ? (
                <p role="alert">Reviewed news unavailable.</p>
              ) : !media ? (
                <p role="status">Loading reviewed news…</p>
              ) : !media.items.length ? (
                <p>No reviewed news at this cutoff.</p>
              ) : (
                media.items.map((item) => (
                  <article key={item.item_id}>
                    <h3>
                      {item.url ? (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          {item.headline}
                        </a>
                      ) : (
                        item.headline
                      )}
                    </h3>
                    <p>{item.excerpt}</p>
                  </article>
                ))
              )}
            </div>
          )}
        </section>
        <footer className="footer">
          <span>NBA Time Machine</span>
          <span>Choose your game. Choose what you know.</span>
        </footer>
      </main>
    </div>
  );
}
