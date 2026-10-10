/**
 * Frontend contract for the intentionally sparse policy projections.
 * Source/provider records must never be bound to dashboard components.
 */
export type GameCard = {
  game_id: string;
  disclosure: "pregame";
  state: "sealed" | "acknowledged";
  home_team?: string;
  away_team?: string;
  scheduled_tip?: string;
  pregame_interest?: number;
};

export type GameList = { time_cursor: string; games: GameCard[] };
export type MediaItem = {
  item_id: string;
  headline: string;
  excerpt?: string;
  thumbnail_url?: string;
  runtime_seconds?: number;
};
export type MediaFeed = { time_cursor: string; items: MediaItem[] };
export type Verdict = {
  game_id: string;
  disclosure: "watchability";
  watchability_verdict?: string;
};
export type Reason = {
  game_id: string;
  disclosure: "why";
  watchability_verdict?: string;
  watchability_reason?: string;
};
export type FullReveal = {
  game_id: string;
  disclosure: "full";
  home_team?: string;
  away_team?: string;
  home_score?: number;
  away_score?: number;
  result?: string;
};

function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Invalid dashboard response");
  }
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]) {
  if (Object.keys(value).some((key) => !keys.includes(key))) {
    throw new Error("Unexpected field in spoiler-safe response");
  }
}

function textOrAbsent(value: unknown): boolean {
  return value === undefined || typeof value === "string";
}

function finiteOrAbsent(value: unknown): boolean {
  return value === undefined || (typeof value === "number" && Number.isFinite(value));
}

export function parseGameList(value: unknown): GameList {
  const data = object(value);
  exactKeys(data, ["time_cursor", "games"]);
  if (typeof data.time_cursor !== "string" || !Number.isFinite(Date.parse(data.time_cursor)) || !Array.isArray(data.games)) {
    throw new Error("Invalid game list");
  }
  const games: GameCard[] = data.games.map((raw: unknown) => {
    const game = object(raw);
    exactKeys(game, [
      "game_id", "disclosure", "state", "home_team", "away_team",
      "scheduled_tip", "pregame_interest",
    ]);
    if (
      typeof game.game_id !== "string" ||
      game.disclosure !== "pregame" ||
      (game.state !== "sealed" && game.state !== "acknowledged") ||
      !textOrAbsent(game.home_team) ||
      !textOrAbsent(game.away_team) ||
      !textOrAbsent(game.scheduled_tip) ||
      !finiteOrAbsent(game.pregame_interest)
    ) {
      throw new Error("Invalid pregame projection");
    }
    return game as GameCard;
  });
  return { time_cursor: data.time_cursor, games };
}

export function parseMediaFeed(value: unknown): MediaFeed {
  const data = object(value);
  exactKeys(data, ["time_cursor", "items"]);
  if (typeof data.time_cursor !== "string" || !Number.isFinite(Date.parse(data.time_cursor)) || !Array.isArray(data.items)) {
    throw new Error("Invalid media feed");
  }
  const items: MediaItem[] = data.items.map((raw: unknown) => {
    const item = object(raw);
    exactKeys(item, ["item_id", "headline", "excerpt", "thumbnail_url", "runtime_seconds"]);
    if (
      typeof item.item_id !== "string" || typeof item.headline !== "string" ||
      !textOrAbsent(item.excerpt) || !textOrAbsent(item.thumbnail_url) ||
      !finiteOrAbsent(item.runtime_seconds)
    ) {
      throw new Error("Invalid safe media projection");
    }
    return item as MediaItem;
  });
  return { time_cursor: data.time_cursor, items };
}

export function parseVerdict(value: unknown, requested: "watchability" | "why"): Verdict | Reason {
  const data = object(value);
  exactKeys(data, requested === "why"
    ? ["game_id", "disclosure", "watchability_verdict", "watchability_reason"]
    : ["game_id", "disclosure", "watchability_verdict"]);
  if (
    typeof data.game_id !== "string" || data.disclosure !== requested ||
    !textOrAbsent(data.watchability_verdict) ||
    (requested === "why" && !textOrAbsent(data.watchability_reason))
  ) {
    throw new Error("Invalid disclosure projection");
  }
  return data as Verdict | Reason;
}

export function parseFull(value: unknown): FullReveal {
  const data = object(value);
  // Full projections may add explicitly authorized details in later backend versions.
  // The UI currently accepts only the fields it knows how to show.
  exactKeys(data, [
    "game_id", "disclosure", "home_team", "away_team", "scheduled_tip",
    "pregame_interest", "pregame_standings", "pregame_availability",
    "watchability_verdict", "watchability_reason", "in_game_status",
    "home_score", "away_score", "result", "box_score", "recap",
    "highlight_url", "highlight_thumbnail", "highlight_runtime_seconds",
  ]);
  if (typeof data.game_id !== "string" || data.disclosure !== "full" ||
      !textOrAbsent(data.result) ||
      !finiteOrAbsent(data.home_score) || !finiteOrAbsent(data.away_score)) {
    throw new Error("Invalid full-game projection");
  }
  return data as FullReveal;
}

/** Only pre-tip interest controls this ordering. Favorites never enter it. */
export function orderByPregameInterest(games: readonly GameCard[]): GameCard[] {
  return [...games].sort((a, b) =>
    (b.pregame_interest ?? -Infinity) - (a.pregame_interest ?? -Infinity) ||
    a.game_id.localeCompare(b.game_id));
}

export function forwardCursor(current: string, hours: number): string {
  const before = Date.parse(current);
  if (!Number.isFinite(before) || !Number.isFinite(hours) || hours <= 0) {
    throw new Error("Invalid forward-only cursor movement");
  }
  return new Date(before + hours * 3_600_000).toISOString();
}

export function restoredCursor(value: string | null, initial: string): string {
  if (!value || !Number.isFinite(Date.parse(value)) ||
      Date.parse(value) < Date.parse(initial)) {
    return initial;
  }
  return new Date(value).toISOString();
}
