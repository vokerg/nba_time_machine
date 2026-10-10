import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  forwardCursor, orderByPregameInterest, parseFull, parseGameList,
  parseMediaFeed, parseVerdict, restoredCursor,
} from "../src/dashboard.ts";

const sample = JSON.parse(readFileSync(new URL("../src/fixtures/read-models.json", import.meta.url), "utf8"));

test("backend-exported fixtures satisfy the exact spoiler-safe UI contracts", () => {
  const games = parseGameList(sample.games);
  const media = parseMediaFeed(sample.media);
  assert.equal(games.games[0].state, "sealed");
  assert.equal(media.items.length, 1);
  assert.equal(parseVerdict(sample.watchability, "watchability").disclosure, "watchability");
  assert.equal(parseVerdict(sample.reason, "why").disclosure, "why");
  assert.equal(parseFull(sample.full).disclosure, "full");
});

test("sealed card parser rejects incidental result and outcome hints", () => {
  for (const forbidden of [
    { home_score: 105 }, { result: "Home wins" }, { runtime_seconds: 7200 },
    { highlight_thumbnail: "suspicious.jpg" }, { watchability_verdict: "Great" },
    { postgame_quality: 9.9 }, { watched: true },
  ]) {
    const dirty = structuredClone(sample.games);
    Object.assign(dirty.games[0], forbidden);
    assert.throws(() => parseGameList(dirty), /Unexpected field/);
  }
});

test("watchability and why projections reject full-reveal fields", () => {
  assert.throws(() => parseVerdict({ ...sample.watchability, home_score: 100 }, "watchability"));
  assert.throws(() => parseVerdict({ ...sample.reason, postgame_quality: 10 }, "why"));
  assert.throws(() => parseVerdict(sample.reason, "watchability"));
  assert.throws(() => parseFull(sample.watchability));
});

test("media is a separate timeline-filtered projection and rejects unsafe extras", () => {
  const media = parseMediaFeed(sample.media);
  const altered = structuredClone(sample.media);
  altered.items[0].home_score = 110;
  assert.throws(() => parseMediaFeed(altered));
  assert.deepEqual(parseMediaFeed(sample.media), media);
});

test("pregame interest ranking is stable and does not accept favorites or hidden scores", () => {
  const first = sample.games.games[0];
  const games = [
    { ...first, game_id: "b", pregame_interest: 2 },
    { ...first, game_id: "a", pregame_interest: 2 },
    { ...first, game_id: "c", pregame_interest: 7 },
  ];
  const original = [...games];
  assert.deepEqual(orderByPregameInterest(games).map((g) => g.game_id), ["c", "a", "b"]);
  assert.deepEqual(games, original);
});

test("demo cursor is forward only and reload cannot restore an earlier world", () => {
  const first = sample.games.time_cursor;
  const later = forwardCursor(first, 24);
  assert.equal(Date.parse(later) - Date.parse(first), 86_400_000);
  assert.equal(restoredCursor(later, first), later);
  assert.equal(restoredCursor("2020-01-01T00:00:00Z", first), first);
  assert.equal(restoredCursor("invalid", first), first);
  assert.throws(() => forwardCursor(first, 0));
  assert.throws(() => forwardCursor(first, -1));
});
