/** Explicit-consent boundary for outcome-influenced ranking.
 *
 * Do not invoke from passive renders/effects. Supply only a backend-projected,
 * cursor-scoped game list from the same connected profile (never demo fixtures).
 * A ranked game's inclusion/position is a spoiler even without numeric scores.
 */
import type { GameCard, GameList } from "./dashboard.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const NBA_DATE = /^\d{4}-\d{2}-\d{2}$/;
const CARD_KEYS = new Set([
  "game_id", "disclosure", "state", "home_team", "away_team",
  "scheduled_tip", "pregame_interest",
]);

export type WatchabilityRequest = {
  profileId: string;
  gameList: GameList;
  /** NBA/Eastern calendar date passed to the safe game-list request. */
  slateDate: string;
  consentToOutcomeRanking: true;
  budgetMinutes?: number;
  plannedMinutesPerGame?: number;
  fetcher?: typeof fetch;
};

function validSlateDate(value: string): boolean {
  if (typeof value !== "string" || !NBA_DATE.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function validOptionalMinutes(value: number | undefined, min: number, max: number): boolean {
  return value === undefined || (Number.isInteger(value) && value >= min && value <= max);
}

/** Returns only existing PREGAME cards in outcome-ranked order, never scores. */
export async function requestWatchabilityRecommendations({
  profileId, gameList, slateDate, consentToOutcomeRanking,
  budgetMinutes, plannedMinutesPerGame = 120, fetcher = fetch,
}: WatchabilityRequest): Promise<GameCard[]> {
  // Verify everything before issuing any request; absence of consent is final.
  if (consentToOutcomeRanking !== true) {
    throw new Error("Explicit outcome-ranking consent required");
  }
  if (!UUID.test(profileId) || !validSlateDate(slateDate) || !gameList ||
      !Number.isFinite(Date.parse(gameList.time_cursor)) ||
      !Array.isArray(gameList.games) ||
      gameList.games.length < 1 || gameList.games.length > 32) {
    throw new Error("Invalid connected profile or safe candidate slate");
  }
  if (!validOptionalMinutes(budgetMinutes, 0, 1440) ||
      !validOptionalMinutes(plannedMinutesPerGame, 1, 720)) {
    throw new Error("Invalid planned viewing time");
  }

  const cards = new Map<string, GameCard>();
  for (const card of gameList.games) {
    if (!card || typeof card !== "object" ||
        Object.keys(card).some((key) => !CARD_KEYS.has(key)) ||
        !UUID.test(card.game_id) || card.disclosure !== "pregame" ||
        (card.state !== "sealed" && card.state !== "acknowledged") ||
        (card.home_team !== undefined && typeof card.home_team !== "string") ||
        (card.away_team !== undefined && typeof card.away_team !== "string") ||
        (card.scheduled_tip !== undefined && typeof card.scheduled_tip !== "string") ||
        (card.pregame_interest !== undefined &&
         (typeof card.pregame_interest !== "number" || !Number.isFinite(card.pregame_interest)))) {
      throw new Error("Invalid spoiler-safe candidate card");
    }
    const key = card.game_id.toLowerCase();
    if (cards.has(key)) throw new Error("Duplicate candidate game");
    cards.set(key, card);
  }

  const response = await fetcher(
    "/profiles/" + profileId.toLowerCase() + "/recommendations/watchability",
    {
      method: "POST",
      credentials: "same-origin",
      redirect: "error",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        slate_date: slateDate,
        candidate_game_ids: [...cards.values()].map((card) => card.game_id),
        consent_to_outcome_ranking: true,
        ...(budgetMinutes !== undefined ? { budget_minutes: budgetMinutes } : {}),
        planned_minutes_per_game: plannedMinutesPerGame,
      }),
    },
  );
  if (!response.ok) throw new Error("Watchability ranking unavailable");

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("Invalid watchability ranking response");
  }
  if (data === null || typeof data !== "object" || Array.isArray(data) ||
      Object.keys(data).length !== 1 || !Object.hasOwn(data, "game_ids")) {
    throw new Error("Invalid watchability ranking response");
  }
  const ids = (data as Record<string, unknown>).game_ids;
  if (!Array.isArray(ids) || ids.length > cards.size) {
    throw new Error("Invalid watchability ranking response");
  }

  const seen = new Set<string>();
  return ids.map((id: unknown) => {
    if (typeof id !== "string" || !UUID.test(id)) {
      throw new Error("Invalid watchability ranking response");
    }
    const key = id.toLowerCase();
    const card = cards.get(key);
    if (!card || seen.has(key)) {
      throw new Error("Invalid watchability ranking response");
    }
    seen.add(key);
    // Return a freshly constructed allowlisted pregame card, never server
    // ranking metadata or unvalidated spread fields.
    return {
      game_id: card.game_id,
      disclosure: "pregame" as const,
      state: card.state,
      ...(card.home_team !== undefined ? { home_team: card.home_team } : {}),
      ...(card.away_team !== undefined ? { away_team: card.away_team } : {}),
      ...(card.scheduled_tip !== undefined ? { scheduled_tip: card.scheduled_tip } : {}),
      ...(card.pregame_interest !== undefined ? { pregame_interest: card.pregame_interest } : {}),
    };
  });
}
