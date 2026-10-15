/** Spoiler-denying queue contract: all game details come from GameCardResponse. */
import { parseGameList } from "./dashboard.ts";
import type { GameCard } from "./dashboard.ts";

export type QueueState = "queued" | "done" | "dismissed";
export type QueueItem = { game_id: string; queue_state: QueueState; game: GameCard | null };
export type WatchQueue = { time_cursor: string; items: QueueItem[] };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseWatchQueue(value: unknown): WatchQueue {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid Watch Queue response.");
  const raw = value as Record<string, unknown>;
  if (Object.keys(raw).some((key) => !["time_cursor", "items"].includes(key)) ||
      typeof raw.time_cursor !== "string" || !/(?:Z|[+-]\d\d:\d\d)$/.test(raw.time_cursor) ||
      !Number.isFinite(Date.parse(raw.time_cursor)) || !Array.isArray(raw.items)) {
    throw new Error("Invalid Watch Queue response.");
  }
  const seen = new Set<string>();
  const items = raw.items.map((value: unknown) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid queue entry.");
    const item = value as Record<string, unknown>;
    if (Object.keys(item).some((key) => !["game_id", "queue_state", "game"].includes(key)) ||
        typeof item.game_id !== "string" || !UUID.test(item.game_id) ||
        !["queued", "done", "dismissed"].includes(item.queue_state as string) ||
        !Object.hasOwn(item, "game")) {
      throw new Error("Invalid queue entry.");
    }
    const id = item.game_id.toLowerCase();
    if (seen.has(id)) throw new Error("Duplicate queue entry.");
    seen.add(id);
    let game: GameCard | null = null;
    if (item.game !== null) {
      game = parseGameList({ time_cursor: raw.time_cursor, games: [item.game] }).games[0];
      if (game.game_id.toLowerCase() !== id) throw new Error("Queue card identity mismatch.");
    }
    return { game_id: id, queue_state: item.queue_state as QueueState, game };
  });
  return { time_cursor: raw.time_cursor, items };
}
