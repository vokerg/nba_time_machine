import { useState } from "react";
import fixtures from "./fixtures/read-models.json";
import {
  forwardCursor, orderByPregameInterest, parseFull, parseGameList,
  parseMediaFeed, parseVerdict, restoredCursor,
  type FullReveal, type GameCard, type Reason, type Verdict,
} from "./dashboard";

const slate = parseGameList(fixtures.games);
const media = parseMediaFeed(fixtures.media);
const recommended = orderByPregameInterest(slate.games);
const CURSOR_KEY = "nba-time-machine:demo-cursor:v1";
const FAVORITES_KEY = "nba-time-machine:demo-favorites:v1";
const ACKNOWLEDGED_KEY = "nba-time-machine:demo-acknowledged:v1";

type DisclosureState = { verdict?: Verdict; reason?: Reason; full?: FullReveal };
type Status = { tone: "error" | "info"; message: string } | null;

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Private browsing or disabled storage should not prevent the demo from working.
  }
}
function storedList(key: string): string[] {
  try {
    const value: unknown = JSON.parse(readStorage(key) ?? "[]");
    return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
  } catch {
    return [];
  }
}
function formatCursor(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "full", timeStyle: "short", timeZone: "UTC",
  }).format(new Date(iso)) + " UTC";
}
function formatTip(iso?: string): string {
  if (!iso) return "Tip time unavailable";
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "Tip time unavailable";
  return new Intl.DateTimeFormat("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    timeZone: "UTC", timeZoneName: "short",
  }).format(new Date(time));
}
function labelFor(game: GameCard): string {
  return (game.away_team ?? "Away team") + " at " + (game.home_team ?? "Home team");
}

export function App() {
  const [cursor, setCursor] = useState(() =>
    restoredCursor(readStorage(CURSOR_KEY), slate.time_cursor));
  const [favorites, setFavorites] = useState<string[]>(() => storedList(FAVORITES_KEY));
  const [acknowledged, setAcknowledged] = useState<string[]>(() => storedList(ACKNOWLEDGED_KEY));
  const [disclosures, setDisclosures] = useState<Record<string, DisclosureState>>({});
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);

  // Demo fixtures come from the backend read-model exporter. They are NOT live
  // NBA events or the response from a connected profile/account endpoint.
  const teams = [...new Set(slate.games.flatMap((game) =>
    [game.home_team, game.away_team].filter((name): name is string => !!name)))].sort();

  function advance(hours: number) {
    setBusy("timeline");
    try {
      const next = forwardCursor(cursor, hours);
      setCursor(next);
      writeStorage(CURSOR_KEY, next);
      setStatus({ tone: "info", message: "Demo NBA-world cursor advanced. Game reveals do not change it." });
    } catch {
      setStatus({ tone: "error", message: "Unable to move the cursor." });
    } finally {
      setBusy(null);
    }
  }

  function toggleFavorite(team: string) {
    const next = favorites.includes(team)
      ? favorites.filter((value) => value !== team)
      : [...favorites, team];
    setFavorites(next);
    writeStorage(FAVORITES_KEY, JSON.stringify(next));
  }

  function disclose(game: GameCard, layer: "watchability" | "why" | "full") {
    setBusy(game.game_id + ":" + layer);
    setStatus(null);
    try {
      if (layer === "full") {
        // Deliberate, confirmed action. The full fixture is never read or
        // displayed by any passive card, ranking, or media code path.
        const full = parseFull(fixtures.full);
        if (full.game_id !== game.game_id) throw new Error("Fixture game mismatch");
        const next = [...new Set([...acknowledged, game.game_id])];
        setAcknowledged(next);
        writeStorage(ACKNOWLEDGED_KEY, JSON.stringify(next));
        setDisclosures((prior) => ({ ...prior, [game.game_id]: {
          ...prior[game.game_id], full,
        } }));
        setConfirming(null);
      } else {
        const projection = parseVerdict(
          layer === "why" ? fixtures.reason : fixtures.watchability, layer);
        if (projection.game_id !== game.game_id) throw new Error("Fixture game mismatch");
        setDisclosures((prior) => ({ ...prior, [game.game_id]: {
          ...prior[game.game_id],
          ...(layer === "why"
            ? { reason: projection as Reason }
            : { verdict: projection as Verdict }),
        } }));
      }
    } catch {
      setStatus({ tone: "error", message: "The requested disclosure is unavailable or invalid." });
    } finally {
      setBusy(null);
    }
  }

  const favoriteGames = slate.games.filter((game) =>
    (game.home_team && favorites.includes(game.home_team)) ||
    (game.away_team && favorites.includes(game.away_team)));

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="#home" aria-label="NBA Time Machine home">
          <span className="brand-mark">TM</span>
          <span>NBA <strong>TIME MACHINE</strong></span>
        </a>
        <div className="topbar-right">
          <span className="demo-pill"><span className="demo-dot" /> Fixture demo</span>
          <span className="topbar-caption">Spoiler-safe by design</span>
        </div>
      </header>

      <main className="shell" id="home">
        <section className="masthead" aria-labelledby="welcome-heading">
          <div>
            <p className="eyebrow">Your own NBA universe</p>
            <h1 id="welcome-heading">Catch up without <em>catching spoilers.</em></h1>
            <p className="lede">A delayed view of the league. Choose how far your NBA world moves, then open each game's story only when you're ready.</p>
          </div>
          <div className="fixture-explainer" role="note">
            <span className="fixture-icon" aria-hidden="true">◈</span>
            <div><strong>Demonstration data</strong><p>The slate, results and media below are synthetic fixtures, not today's games. Profile-backed game lists and feeds are not connected yet.</p></div>
          </div>
        </section>

        <section className="timeline-panel" aria-labelledby="timeline-heading">
          <div className="timeline-copy">
            <p className="eyebrow">Current NBA-world time</p>
            <h2 id="timeline-heading">{formatCursor(cursor)}</h2>
            <p>This cursor resumes from this browser on reload. It only moves forward.</p>
          </div>
          <div className="timeline-controls" aria-label="Forward-only timeline controls">
            <button type="button" disabled={busy !== null} onClick={() => advance(6)}>Advance 6 hours <span aria-hidden="true">↗</span></button>
            <button className="primary" type="button" disabled={busy !== null} onClick={() => advance(24)}>Advance 1 day <span aria-hidden="true">→</span></button>
          </div>
          <div className="timeline-rule"><span>01</span> Your world only moves forward <span className="rule-mark">→</span></div>
        </section>

        {status && <div className={"notice " + status.tone} role={status.tone === "error" ? "alert" : "status"}>{status.message}</div>}

        <div className="dashboard-grid">
          <section className="games-section" aria-labelledby="games-heading">
            <div className="section-header">
              <div><p className="eyebrow">Tonight's board · sample</p><h2 id="games-heading">Games, on your terms.</h2></div>
              <span className="count-pill">{slate.games.length} sample game{slate.games.length === 1 ? "" : "s"}</span>
            </div>
            <p className="section-intro">The list shows pregame facts only. Ask for a verdict, learn why, or deliberately reveal the result. Nothing opens by accident.</p>
            {slate.games.length === 0 && <div className="empty-state">No safe game cards available at this cursor.</div>}
            <div className="game-list">
              {slate.games.map((game) => {
                const shown = disclosures[game.game_id] ?? {};
                const isAcknowledged = acknowledged.includes(game.game_id) || game.state === "acknowledged";
                const confirmingThis = confirming === game.game_id;
                return (
                  <article className="game-card" key={game.game_id}>
                    <div className="game-meta">
                      <span className="tip-label">{formatTip(game.scheduled_tip)}</span>
                      <span className={"state-pill " + (isAcknowledged ? "acknowledged" : "sealed")}>
                        <span aria-hidden="true">{isAcknowledged ? "◉" : "◇"}</span> {isAcknowledged ? "Acknowledged" : "Sealed"}
                      </span>
                    </div>
                    <h3>{labelFor(game)}</h3>
                    <p className="pregame-label">Pregame interest {typeof game.pregame_interest === "number" ? "· " + game.pregame_interest.toFixed(1) : "· Not available"}</p>
                    <div className="game-actions">
                      <button type="button" disabled={busy !== null} onClick={() => disclose(game, "watchability")}>Show watchability</button>
                      <button className="danger-link" type="button" disabled={busy !== null} onClick={() => setConfirming(confirmingThis ? null : game.game_id)}>{isAcknowledged ? "View result" : "Reveal result"} <span aria-hidden="true">↗</span></button>
                    </div>
                    {(shown.verdict || shown.reason) && !shown.full && (
                      <div className="disclosure-box" aria-live="polite">
                        <p className="small-label">Optional watchability hint</p>
                        <strong>{shown.reason?.watchability_verdict ?? shown.verdict?.watchability_verdict ?? "No verdict available"}</strong>
                        {shown.reason?.watchability_reason && <p>{shown.reason.watchability_reason}</p>}
                        {!shown.reason && <button type="button" className="text-action" disabled={busy !== null} onClick={() => disclose(game, "why")}>Why? Show one more hint →</button>}
                      </div>
                    )}
                    {confirmingThis && (
                      <div className="confirmation" role="group" aria-label="Confirm result disclosure">
                        <p>Reveal the full game result? This acknowledges only this game. Your global news timeline will not move.</p>
                        <div><button type="button" className="confirm-button" disabled={busy !== null} onClick={() => disclose(game, "full")}>Yes, reveal score</button>
                        <button type="button" disabled={busy !== null} onClick={() => setConfirming(null)}>Keep it sealed</button></div>
                      </div>
                    )}
                    {shown.full && (
                      <div className="result-box" aria-live="polite">
                        <p className="small-label">Explicitly revealed · sample result</p>
                        <strong>{shown.full.away_team ?? game.away_team} {shown.full.away_score ?? "–"} <span>—</span> {shown.full.home_score ?? "–"} {shown.full.home_team ?? game.home_team}</strong>
                        {shown.full.result && <p>{shown.full.result}</p>}
                      </div>
                    )}
                  </article>
                );
              })}
            </div>
          </section>

          <aside className="side-column">
            <section className="side-panel watch-panel" aria-labelledby="watch-heading">
              <div className="side-icon">✦</div>
              <p className="eyebrow">The viewing guide</p>
              <h2 id="watch-heading">What should I watch?</h2>
              <p>These demo suggestions use pregame interest only. Postgame watchability ranking is not available yet.</p>
              {recommended[0] ? (
                <div className="recommendation">
                  <p className="small-label">Pregame pick</p>
                  <strong>{labelFor(recommended[0])}</strong>
                  <p>Based solely on pre-tip information, never on a result or your favorites.</p>
                </div>
              ) : <p>No pregame recommendation available.</p>}
            </section>

            <section className="side-panel favorites-panel" aria-labelledby="favorites-heading">
              <p className="eyebrow">Your corner</p>
              <h2 id="favorites-heading">Favorite teams</h2>
              <p>Follow multiple teams. These choices never change the canonical list order.</p>
              <div className="favorite-choices">
                {teams.map((team) => <label key={team}>
                  <input type="checkbox" checked={favorites.includes(team)} onChange={() => toggleFavorite(team)} />
                  <span>{team}</span>
                </label>)}
              </div>
              {favoriteGames.length > 0 && <p className="favorite-summary">{favoriteGames.length} matching sample game{favoriteGames.length === 1 ? "" : "s"} · shown separately</p>}
              {teams.length === 0 && <p>No teams in this sample slate.</p>}
            </section>
          </aside>

          <section className="media-section" aria-labelledby="media-heading">
            <div className="section-header">
              <div><p className="eyebrow">Across the league · sample</p><h2 id="media-heading">News &amp; buzz</h2></div>
              <span className="media-lock">↳ Cursor-controlled</span>
            </div>
            <p className="section-intro">This feed comes from a separately filtered timeline projection. Revealing one game never unlocks later general media.</p>
            <div className="media-list">
              {media.items.map((item) => <article key={item.item_id} className="media-item">
                <span className="media-number">◉</span>
                <div><h3>{item.headline}</h3>{item.excerpt && <p>{item.excerpt}</p>}</div>
                <span className="media-arrow" aria-hidden="true">↗</span>
              </article>)}
              {media.items.length === 0 && <div className="empty-state">No media items cleared for this timeline.</div>}
            </div>
          </section>
        </div>
        <footer className="footer"><span>NBA TIME MACHINE / PROTOTYPE</span><span>No live data · no hidden score APIs · forward-only fixture cursor</span></footer>
      </main>
    </div>
  );
}
