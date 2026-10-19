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

const expectation = {
  model: 'pregame-records-v1', rating: 4, overall_points: .8, coverage: 'records-only', basis: 'reconstructed',
  explanation: 'Entering records with conservative sample confidence.', missing: ['Injuries'],
  teams: [{team:'BOS',wins:20,losses:5,smoothed_win_pct:.714}, {team:'NYK',wins:18,losses:7,smoothed_win_pct:.657}],
  sample_confidence: 1, formula: 'Shared record-strength formula', source_ref: 'fact:1', observed_at: cursor, available_at: cursor,
};
test('open expectation is allowlisted, slate-scoped, reconstructed and isolated from Time Machine', async () => {
  const { parseGuideList } = await import('../src/guide.ts');
  const value = {...slate, expectations:{[id]:expectation}};
  assert.equal(parseGuideList(value, 'browse').expectations[id].rating, 4);
  assert.throws(() => parseGuideList(value, 'time-machine'));
  for (const extra of [{home_score:110}, {removed_result:'win'}, {rating:11}, {overall_points:2},
      {teams:[{...expectation.teams[0],provider_after_wins:21}, expectation.teams[1]]}]) {
    assert.throws(() => parseGuideList({...slate, expectations:{[id]:{...expectation,...extra}}}, 'browse'));
  }
  assert.throws(() => parseGuideList({...slate, expectations:{'unknown-game':expectation}}, 'browse'));
});
