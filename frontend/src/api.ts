import { parseDayUpdate } from "./dayUpdate.ts";
/** Same-origin backend integration. Only allowlisted policy responses enter UI state. */
import { forwardCursor, parseFull, parseGameList, parseMediaFeed, parseVerdict } from "./dashboard.ts";
import type { FullReveal, GameList, MediaFeed, Reason, Verdict } from "./dashboard.ts";
import { requestWatchabilityRecommendations } from "./watchability.ts";
import { parseWatchQueue } from "./watchQueue.ts";
import type { QueueState, WatchQueue } from "./watchQueue.ts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export type Timeline = { profile_id: string; time_cursor: string; initialized_at: string; updated_at: string };
export type ScheduleView = "pregame" | "observed" | "replay";

export class ApiError extends Error {
  status: number;
  constructor(status: number) {
    super(status === 503 ? "Backend database unavailable." : status === 409 ? "This action conflicts with the saved timeline or game state. Reload to resume." : "Backend request unavailable.");
    this.status = status;
  }
}

function id(value: string): string {
  if (!UUID.test(value)) throw new Error("Invalid profile or game identity.");
  return value.toLowerCase();
}
function instant(value: unknown): value is string {
  return typeof value === "string" && /(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value));
}
export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T00:00:00Z");
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}
export function nbaDate(cursor: string): string {
  if (!instant(cursor)) throw new Error("Invalid timeline.");
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(cursor));
  const get = (name: string) => parts.find((part) => part.type === name)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
export function parseTimeline(value: unknown, profileId: string): Timeline {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid timeline response.");
  const data = value as Record<string, unknown>;
  if (Object.keys(data).some((key) => !["profile_id", "time_cursor", "initialized_at", "updated_at"].includes(key)) ||
      data.profile_id !== id(profileId) || !instant(data.time_cursor) || !instant(data.initialized_at) || !instant(data.updated_at)) {
    throw new Error("Invalid timeline response.");
  }
  return data as Timeline;
}

export class BackendClient {
  async startDayUpdate(day: string, cursor: string, fetchEvidence = true) {
    if (!validDate(day) || !instant(cursor)) throw new Error("Invalid update date or timeline.");
    const response = await this.fetcher(`/api/profiles/${this.profileId}/guide/update`, {
      method: "POST", cache: "no-store", redirect: "error", credentials: "same-origin",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-Guide-Action": "update-day" },
      body: JSON.stringify({ date: day, mode: "browse", time_cursor: cursor, ...(fetchEvidence ? {} : { fetch_evidence: false }) }),
    });
    if (!response.ok) throw new ApiError(response.status);
    return parseDayUpdate(await response.json());
  }
  async updateStatus(jobId: string, signal?: AbortSignal) {
    return parseDayUpdate(await this.request(`/profiles/${this.profileId}/guide/update/${id(jobId)}`, "GET", undefined, signal));
  }

  async guideGames(day: string, mode: import("./guide").Mode, cursor: string, signal?: AbortSignal): Promise<import("./guide").GuideList> {
    if (!validDate(day)) throw new Error("Choose a valid NBA date.");
    const { parseGuideList } = await import("./guide");
    const result = parseGuideList(await this.request(`/profiles/${this.profileId}/guide?date=${day}&mode=${mode}`, "GET", undefined, signal), mode);
    if (Date.parse(result.time_cursor) !== Date.parse(cursor)) throw new Error("Timeline changed. Reload saved state.");
    return result;
  }
  async guideDisclosure(slate: GameList, day: string, mode: import("./guide").Mode, level: import("./guide").Level, gameId?: string) {
    const { parseDisclosure } = await import("./guide");
    const raw = await this.request(`/profiles/${this.profileId}/guide/disclose`, "POST", {
      date: day, mode, time_cursor: slate.time_cursor, level, consent: true, ...(gameId ? { game_id: id(gameId) } : {}),
    });
    return parseDisclosure(raw, slate, level, gameId);
  }

  profileId: string;
  fetcher: typeof fetch;
  constructor(profileId: string, fetcher: typeof fetch = fetch) {
    this.profileId = id(profileId);
    this.fetcher = fetcher.bind(globalThis);
  }
  async request(path: string, method = "GET", body?: unknown, signal?: AbortSignal): Promise<unknown> {
    const response = await this.fetcher("/api" + path, {
      method, signal, cache: "no-store", redirect: "error", credentials: "same-origin",
      headers: { Accept: "application/json", ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    if (!response.ok) throw new ApiError(response.status);
    if (response.status === 204) return null;
    return response.json();
  }
  async resume(signal?: AbortSignal): Promise<Timeline | null> {
    try {
      return parseTimeline(await this.request("/timeline/" + this.profileId, "GET", undefined, signal), this.profileId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }
  async initialize(cursor: string): Promise<Timeline> {
    if (!instant(cursor)) throw new Error("Timezone-aware cursor required.");
    try {
      return parseTimeline(await this.request("/timeline/" + this.profileId, "POST", { time_cursor: cursor }), this.profileId);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        const saved = await this.resume();
        if (saved) return saved;
      }
      throw error;
    }
  }
  async advance(current: string, hours: number): Promise<Timeline> {
    const requested = forwardCursor(current, hours);
    const state = parseTimeline(await this.request("/timeline/" + this.profileId, "PUT", { time_cursor: requested }), this.profileId);
    if (Date.parse(state.time_cursor) < Date.parse(current)) throw new Error("Invalid regressed timeline response.");
    return state;
  }
  async games(day: string, view: ScheduleView, cursor: string, signal?: AbortSignal): Promise<GameList> {
    if (!validDate(day) || !["pregame", "observed", "replay"].includes(view)) throw new Error("Invalid schedule selection.");
    const result = parseGameList(await this.request(`/profiles/${this.profileId}/games?date=${day}&view=${view}`, "GET", undefined, signal));
    if (Date.parse(result.time_cursor) !== Date.parse(cursor)) throw new Error("Timeline changed in another tab. Reload to resume.");
    const seen = new Set<string>();
    for (const card of result.games) {
      const gameId = id(card.game_id);
      if (seen.has(gameId) || (card.scheduled_tip !== undefined && !instant(card.scheduled_tip))) throw new Error("Invalid game list response.");
      seen.add(gameId);
    }
    return result;
  }
  async media(cursor: string, page?: string, signal?: AbortSignal): Promise<MediaFeed> {
    if (!instant(cursor) || (page !== undefined && !/^[A-Za-z0-9_-]{1,512}$/.test(page)))
      throw new Error("Invalid media request.");
    const query = new URLSearchParams({ time_cursor: cursor, limit: "10" });
    if (page) query.set("page", page);
    const data = parseMediaFeed(await this.request(
      `/profiles/${this.profileId}/media?${query.toString()}`, "GET", undefined, signal,
    ));
    if (Date.parse(data.time_cursor) !== Date.parse(cursor))
      throw new Error("Timeline changed in another tab. Reload to resume.");
    if (data.items.some((item) => item.known_at && Date.parse(item.known_at) > Date.parse(cursor)))
      throw new Error("Future media was rejected.");
    return data;
  }
  async disclose(gameId: string, layer: "watchability" | "why" | "full", consent: true): Promise<Verdict | Reason | FullReveal> {
    if (consent !== true) throw new Error("Explicit disclosure consent required.");
    const game = id(gameId);
    if (!["watchability", "why", "full"].includes(layer)) throw new Error("Invalid disclosure layer.");
    const data = await this.request(`/profiles/${this.profileId}/games/${game}/${layer === "full" ? "reveal" : layer}`, layer === "full" ? "POST" : "GET");
    const result = layer === "full" ? parseFull(data) : parseVerdict(data, layer);
    if (id(result.game_id) !== game) throw new Error("Disclosure game mismatch.");
    return result;
  }
  async queue(cursor: string, view: ScheduleView, signal?: AbortSignal): Promise<WatchQueue> {
    if (!instant(cursor) || !["pregame", "observed", "replay"].includes(view)) throw new Error("Invalid queue selection.");
    const data = parseWatchQueue(await this.request(
      `/profiles/${this.profileId}/watch-queue?time_cursor=${encodeURIComponent(cursor)}&view=${view}`,
      "GET", undefined, signal,
    ));
    if (Date.parse(data.time_cursor) !== Date.parse(cursor)) throw new Error("Timeline changed in another tab. Reload to resume.");
    return data;
  }
  async saveQueue(gameId: string, state: QueueState, cursor: string): Promise<void> {
    if (!instant(cursor) || !["queued", "done", "dismissed"].includes(state)) throw new Error("Invalid queue action.");
    await this.request(`/profiles/${this.profileId}/watch-queue/${id(gameId)}`, "PUT", { time_cursor: cursor, queue_state: state });
  }
  async removeQueue(gameId: string, cursor: string): Promise<void> {
    if (!instant(cursor)) throw new Error("Invalid timeline.");
    await this.request(`/profiles/${this.profileId}/watch-queue/${id(gameId)}?time_cursor=${encodeURIComponent(cursor)}`, "DELETE");
  }
  async recommend(gameList: GameList, slateDate: string, consent: true) {
    return requestWatchabilityRecommendations({
      profileId: this.profileId, gameList, slateDate, consentToOutcomeRanking: consent,
      fetcher: ((path, options) => this.fetcher("/api" + path, options)) as typeof fetch,
    });
  }
}

export function profileIdentity(storage: Pick<Storage, "getItem" | "setItem">, generate = () => crypto.randomUUID()): string {
  const key = "nba-time-machine:profile:v1";
  const saved = storage.getItem(key);
  if (saved && UUID.test(saved)) return id(saved);
  const created = id(generate());
  storage.setItem(key, created);
  return created;
}
