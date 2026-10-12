import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestWatchabilityRecommendations } from "../src/watchability.ts";

const fixture = JSON.parse(readFileSync(
  new URL("../src/fixtures/read-models.json", import.meta.url), "utf8",
));
const profileId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const slateDate = "2026-05-04";
const firstId = fixture.games.games[0].game_id;
const secondId = "22222222-2222-4222-8222-222222222222";
const gameList = {
  ...fixture.games,
  games: [
    fixture.games.games[0],
    { ...fixture.games.games[0], game_id: secondId, home_team: "Other" },
  ],
};

function fakeFetch(payload, calls, status = 200) {
  return async (...args) => {
    calls.push(args);
    return new Response(JSON.stringify(payload), {
      status, headers: { "Content-Type": "application/json" },
    });
  };
}

test("requires per-action consent before any network activity", async () => {
  const calls = [];
  const fetcher = fakeFetch({ game_ids: [firstId] }, calls);
  await assert.rejects(requestWatchabilityRecommendations({
    profileId, gameList, slateDate, consentToOutcomeRanking: false, fetcher,
  }), /consent/i);
  assert.equal(calls.length, 0);
});

test("POSTs only UUID candidates, consent and uniform budget, returning safe cards", async () => {
  const calls = [];
  const ranked = await requestWatchabilityRecommendations({
    profileId, gameList, slateDate, consentToOutcomeRanking: true,
    budgetMinutes: 180, plannedMinutesPerGame: 90,
    fetcher: fakeFetch({ game_ids: [secondId, firstId] }, calls),
  });
  assert.deepEqual(ranked.map((game) => game.game_id), [secondId, firstId]);
  assert.deepEqual(Object.keys(ranked[0]).sort(), [
    "away_team", "disclosure", "game_id", "home_team",
    "pregame_interest", "scheduled_tip", "state",
  ]);
  assert.equal(ranked[0].disclosure, "pregame");
  assert.equal(calls.length, 1);
  const [url, init] = calls[0];
  assert.equal(url, "/profiles/" + profileId + "/recommendations/watchability");
  assert.equal(init.method, "POST");
  assert.equal(init.cache, "no-store");
  assert.equal(init.redirect, "error");
  assert.equal(init.credentials, "same-origin");
  assert.deepEqual(JSON.parse(init.body), {
    slate_date: slateDate,
    candidate_game_ids: [firstId, secondId],
    consent_to_outcome_ranking: true,
    budget_minutes: 180,
    planned_minutes_per_game: 90,
  });
  assert.equal(init.body.includes("home_team"), false);
  assert.equal(init.body.includes("pregame_interest"), false);
});

test("empty scored result is not replaced with guessed recommendations", async () => {
  const calls = [];
  const result = await requestWatchabilityRecommendations({
    profileId, gameList, slateDate, consentToOutcomeRanking: true,
    fetcher: fakeFetch({ game_ids: [] }, calls),
  });
  assert.deepEqual(result, []);
  assert.equal(calls.length, 1);
});

test("invalid profile, candidates and viewing-time options fail before HTTP", async () => {
  const calls = [];
  const fetcher = fakeFetch({ game_ids: [] }, calls);
  const base = { profileId, gameList, slateDate, consentToOutcomeRanking: true, fetcher };
  const dirtyScore = {
    ...gameList, games: [{ ...gameList.games[0], home_score: 120 }],
  };
  const invalid = [
    { profileId: "../someone" },
    { slateDate: "not-a-date" },
    { slateDate: "2026-02-30" },
    { gameList: { ...gameList, games: [] } },
    { gameList: { ...gameList, games: Array(33).fill(gameList.games[0]) } },
    { gameList: { ...gameList, games: [gameList.games[0], gameList.games[0]] } },
    { gameList: dirtyScore },
    { gameList: { ...gameList, games: [{ ...gameList.games[0], disclosure: "full" }] } },
    { budgetMinutes: -1 },
    { budgetMinutes: 1441 },
    { plannedMinutesPerGame: 0 },
    { plannedMinutesPerGame: 721 },
    { plannedMinutesPerGame: 2.5 },
  ];
  for (const overrides of invalid) {
    await assert.rejects(requestWatchabilityRecommendations({ ...base, ...overrides }));
  }
  assert.equal(calls.length, 0);
});

test("rejects unknown, duplicated and spoiler-bearing ranking responses", async () => {
  const badResponses = [
    { game_ids: [firstId], scores: [9.9] },
    { game_ids: [firstId], watchability_verdict: "legendary" },
    { game_ids: [firstId, firstId] },
    { game_ids: [firstId, "33333333-3333-4333-8333-333333333333"] },
    { game_ids: ["../../api"] },
    { game_ids: [firstId, secondId, firstId] },
    { game_ids: "not an array" },
    { game_ids: null },
    [firstId],
  ];
  for (const payload of badResponses) {
    const calls = [];
    await assert.rejects(requestWatchabilityRecommendations({
      profileId, gameList, slateDate, consentToOutcomeRanking: true,
      fetcher: fakeFetch(payload, calls),
    }), /Invalid watchability ranking response/);
    assert.equal(calls.length, 1);
  }
});

test("HTTP error details are not rendered as a hidden score or leaked response", async () => {
  const calls = [];
  await assert.rejects(requestWatchabilityRecommendations({
    profileId, gameList, slateDate, consentToOutcomeRanking: true,
    fetcher: fakeFetch({ detail: "postgame score 9.9" }, calls, 503),
  }), (err) => err.message === "Watchability ranking unavailable");
  assert.equal(calls.length, 1);
});
