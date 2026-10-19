import { parseGameList, type GameList } from "./dashboard.ts";
export type Mode = "browse" | "time-machine";
export type Level = "verdict" | "clue" | "rating" | "full" | "order";
export type Detail = {
  game_id: string;
  verdict?: string;
  has_clue?: boolean;
  clue?: string | null;
  rating?: number;
  model?: string;
  as_of?: string;
  components?: {
    label: string;
    points: number;
    normalized: number;
    source_ref: string;
    observed_at: string;
    available_at: string;
  }[];
  result?: { home_score: number; away_score: number };
};
export type GuideDisclosure = {
  time_cursor: string;
  as_of: string;
  details: Record<string, Detail>;
  game_ids: string[];
};
const uuid = /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i;
function record(v: unknown): Record<string, unknown> {
  if (!v || typeof v !== "object" || Array.isArray(v))
    throw new Error("Invalid guide response.");
  return v as Record<string, unknown>;
}
function keys(v: Record<string, unknown>, allowed: string[]) {
  if (Object.keys(v).some((k) => !allowed.includes(k)))
    throw new Error("Unexpected guide field.");
}
function instant(v: unknown): v is string {
  return (
    typeof v === "string" &&
    /(?:Z|[+-]\d\d:\d\d)$/.test(v) &&
    Number.isFinite(Date.parse(v))
  );
}
export function parseDisclosure(
  value: unknown,
  slate: GameList,
  level: Level,
  gameId?: string,
): GuideDisclosure {
  const data = record(value);
  keys(data, ["time_cursor", "as_of", "details", "game_ids"]);
  if (
    !instant(data.time_cursor) ||
    Date.parse(data.time_cursor) !== Date.parse(slate.time_cursor) ||
    !instant(data.as_of)
  )
    throw new Error("Timeline changed. Reload saved state.");
  const ids = new Set(slate.games.map((g) => g.game_id));
  const details = record(data.details);
  if (
    !Array.isArray(data.game_ids) ||
    new Set(data.game_ids).size !== data.game_ids.length ||
    data.game_ids.some((id) => typeof id !== "string" || !ids.has(id))
  )
    throw new Error("Invalid watch order.");
  if (gameId && data.game_ids.length)
    throw new Error("Unexpected watch order.");
  for (const [id, raw] of Object.entries(details)) {
    const d = record(raw);
    keys(d, [
      "game_id",
      "verdict",
      "has_clue",
      "clue",
      "rating",
      "model",
      "as_of",
      "components",
      "result",
    ]);
    if (
      !uuid.test(id) ||
      !ids.has(id) ||
      d.game_id !== id ||
      (gameId && gameId !== id)
    )
      throw new Error("Disclosure game mismatch.");
    if (d.verdict !== undefined && typeof d.verdict !== "string")
      throw new Error("Invalid verdict.");
    if (d.has_clue !== undefined && typeof d.has_clue !== "boolean")
      throw new Error("Invalid clue status.");
    if (d.clue !== undefined && d.clue !== null && typeof d.clue !== "string")
      throw new Error("Invalid clue.");
    if (
      level === "order" ||
      (level === "verdict" &&
        (d.clue !== undefined || d.rating !== undefined)) ||
      (level === "clue" && d.rating !== undefined) ||
      (level !== "full" && d.result !== undefined)
    )
      throw new Error("Unexpected spoiler level.");
    if (d.rating !== undefined) {
      if (
        typeof d.rating !== "number" ||
        !Number.isFinite(d.rating) ||
        d.rating < 0 ||
        d.rating > 10 ||
        typeof d.model !== "string" ||
        !instant(d.as_of) ||
        Date.parse(d.as_of) > Date.parse(data.as_of) ||
        !Array.isArray(d.components) ||
        !d.components.length
      )
        throw new Error("Invalid rating.");
      for (const rawPart of d.components) {
        const part = record(rawPart);
        keys(part, [
          "label",
          "points",
          "normalized",
          "source_ref",
          "observed_at",
          "available_at",
        ]);
        if (
          typeof part.label !== "string" ||
          typeof part.points !== "number" ||
          !Number.isFinite(part.points) ||
          part.points < 0 ||
          part.points > 10 ||
          typeof part.normalized !== "number" ||
          !Number.isFinite(part.normalized) ||
          part.normalized < 0 ||
          part.normalized > 1 ||
          typeof part.source_ref !== "string" ||
          !instant(part.observed_at) ||
          !instant(part.available_at) ||
          Date.parse(part.observed_at) > Date.parse(d.as_of) ||
          Date.parse(part.available_at) > Date.parse(d.as_of)
        )
          throw new Error("Invalid rating evidence.");
      }
      if (
        Math.abs(
          d.components.reduce((sum, p) => sum + p.points, 0) - d.rating,
        ) > 0.002
      )
        throw new Error("Inconsistent rating.");
    } else if (
      d.components !== undefined ||
      d.model !== undefined ||
      d.as_of !== undefined
    )
      throw new Error("Unexpected evidence.");
    if (d.result !== undefined) {
      const r = record(d.result);
      keys(r, ["home_score", "away_score"]);
      if (
        ![r.home_score, r.away_score].every(
          (n) => typeof n === "number" && Number.isInteger(n) && n >= 0,
        )
      )
        throw new Error("Invalid result.");
    }
  }
  return data as GuideDisclosure;
}
export { parseGameList };
