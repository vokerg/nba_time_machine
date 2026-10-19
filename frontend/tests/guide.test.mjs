import test from "node:test";
import assert from "node:assert/strict";
import { parseDisclosure } from "../src/guide.ts";
const id = "00000000-0000-0000-0000-000000000001";
const cursor = "2026-10-14T12:00:00Z";
const slate = {
  time_cursor: cursor,
  games: [{ game_id: id, state: "sealed", disclosure: "pregame" }],
};
const base = { time_cursor: cursor, as_of: cursor, details: {}, game_ids: [] };
const rating = {
  game_id: id,
  rating: 8,
  model: "postgame-v1",
  as_of: cursor,
  components: [
    {
      label: "Close late play",
      points: 8,
      normalized: 0.8,
      source_ref: "fixture:1",
      observed_at: cursor,
      available_at: cursor,
    },
  ],
};
test("guide rejects off-slate, duplicate, cross-layer, inconsistent and future evidence", () => {
  const bad = [
    [{ ...base, game_ids: [id, id] }, "order"],
    [{ ...base, game_ids: ["00000000-0000-0000-0000-000000000099"] }, "order"],
    [{ ...base, details: { [id]: rating } }, "verdict"],
    [{ ...base, details: { [id]: rating } }, "clue"],
    [
      {
        ...base,
        details: {
          [id]: { game_id: id, result: { home_score: 100, away_score: 90 } },
        },
      },
      "rating",
    ],
    [{ ...base, details: { [id]: { ...rating, rating: 9 } } }, "rating"],
    [
      {
        ...base,
        details: { [id]: { ...rating, as_of: "2026-10-15T00:00:00Z" } },
      },
      "rating",
    ],
    [
      { ...base, details: { [id]: { ...rating, raw_payload: "unsafe" } } },
      "rating",
    ],
    [{ ...base, time_cursor: "2026-10-15T00:00:00Z" }, "order"],
  ];
  for (const [value, level] of bad)
    assert.throws(() => parseDisclosure(value, slate, level));
  assert.equal(
    parseDisclosure({ ...base, details: { [id]: rating } }, slate, "rating", id)
      .details[id].rating,
    8,
  );
});
