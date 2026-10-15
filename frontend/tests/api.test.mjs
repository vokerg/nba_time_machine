import test from 'node:test';
import assert from 'node:assert/strict';
import { BackendClient, ApiError, nbaDate, profileIdentity, validDate } from '../src/api.ts';

const profile = '00000000-0000-0000-0000-000000000001';
const game = '00000000-0000-0000-0000-000000000002';
const cursor = '2026-10-13T12:00:00Z';
const timeline = { profile_id: profile, time_cursor: cursor, initialized_at: cursor, updated_at: cursor };
const card = { game_id: game, disclosure: 'pregame', state: 'sealed', home_team: 'Home', away_team: 'Away', scheduled_tip: '2025-10-21T23:00:00Z' };
function fake(responses) {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, options });
    assert.equal(options.cache, 'no-store');
    assert.equal(options.redirect, 'error');
    const next = responses.shift();
    assert.ok(next, 'unexpected or passive endpoint request');
    return new Response(next.status === 204 ? null : JSON.stringify(next.body), { status: next.status ?? 200, headers: { 'Content-Type': 'application/json' } });
  };
  return { calls, client: new BackendClient(profile, fetcher) };
}

test('profile identity survives reload without storing a local cursor or acknowledgement', () => {
  const values = new Map();
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  assert.equal(profileIdentity(storage, () => profile), profile);
  assert.equal(profileIdentity(storage, () => game), profile);
  assert.deepEqual([...values.keys()], ['nba-time-machine:profile:v1']);
});

test('resume and safe list use saved cursor, selected season date and no disclosure requests', async () => {
  const { client, calls } = fake([{ body: timeline }, { body: { time_cursor: cursor, games: [card] } }]);
  assert.deepEqual(await client.resume(), timeline);
  assert.deepEqual((await client.games('2025-10-21', 'observed', cursor)).games, [card]);
  assert.deepEqual(calls.map((c) => c.url), [`/api/timeline/${profile}`, `/api/profiles/${profile}/games?date=2025-10-21&view=observed`]);
  assert.ok(calls.every((c) => c.options.method === 'GET'));
});

test('404 enables explicit initialization, 409 resumes a concurrent initialized profile', async () => {
  const { client, calls } = fake([{ status: 404 }, { status: 409 }, { body: timeline }]);
  assert.equal(await client.resume(), null);
  assert.deepEqual(await client.initialize('2025-10-01T00:00:00Z'), timeline);
  assert.equal(calls[1].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[1].options.body), { time_cursor: '2025-10-01T00:00:00Z' });
});

test('advance persists forward movement, rejects backwards requests before fetching', async () => {
  const next = '2026-10-14T12:00:00.000Z';
  const { client, calls } = fake([{ body: { ...timeline, time_cursor: next } }, { status: 409 }]);
  assert.equal((await client.advance(cursor, 24)).time_cursor, next);
  assert.equal(calls[0].options.method, 'PUT');
  assert.equal(JSON.parse(calls[0].options.body).time_cursor, next);
  await assert.rejects(client.advance(cursor, -1));
  assert.equal(calls.length, 1);
  await assert.rejects(client.advance(cursor, 24), (e) => e instanceof ApiError && e.status === 409);
});

test('both seasons, ET dates, invalid dates, stale cursors and incidental scores fail closed', async () => {
  assert.equal(nbaDate('2026-10-09T00:30:00Z'), '2026-10-08');
  assert.equal(validDate('2026-02-30'), false);
  const { client, calls } = fake([
    { body: { time_cursor: cursor, games: [card] } },
    { body: { time_cursor: '2026-10-14T12:00:00Z', games: [card] } },
    { body: { time_cursor: cursor, games: [{ ...card, home_score: 100 }] } },
  ]);
  await client.games('2026-10-20', 'pregame', cursor);
  assert.match(calls[0].url, /date=2026-10-20&view=pregame/);
  await assert.rejects(client.games('2025-10-21', 'observed', cursor), /another tab/);
  await assert.rejects(client.games('2025-10-21', 'observed', cursor), /Unexpected field/);
  await assert.rejects(client.games('2026-02-30', 'pregame', cursor));
  assert.equal(calls.length, 3);
});

test('only explicit disclosure calls fetch hints and POST reveal; mismatched games fail', async () => {
  const { client, calls } = fake([
    { body: { game_id: game, disclosure: 'watchability' } },
    { body: { game_id: game, disclosure: 'why', watchability_reason: 'A hint' } },
    { body: { game_id: game, disclosure: 'full', home_score: 100, away_score: 90 } },
    { body: { game_id: profile, disclosure: 'full', home_score: 100 } },
  ]);
  await assert.rejects(client.disclose(game, 'full', false), /consent/);
  assert.equal(calls.length, 0);
  await client.disclose(game, 'watchability', true);
  await client.disclose(game, 'why', true);
  assert.equal((await client.disclose(game, 'full', true)).home_score, 100);
  assert.equal(calls[2].url, `/api/profiles/${profile}/games/${game}/reveal`);
  assert.equal(calls[2].options.method, 'POST');
  await assert.rejects(client.disclose(game, 'full', true), /mismatch/);
});

test('backend errors and invalid timeline projections do not fall back to fixtures', async () => {
  const { client } = fake([{ status: 503 }, { body: { ...timeline, profile_id: game } }]);
  await assert.rejects(client.resume(), /database unavailable/);
  await assert.rejects(client.resume(), /Invalid timeline/);
});

test('native fetch receives the browser/global binding rather than the client instance', async () => {
  const client = new BackendClient(profile, function () {
    assert.equal(this, globalThis);
    return Promise.resolve(new Response(JSON.stringify(timeline)));
  });
  assert.deepEqual(await client.resume(), timeline);
});


test('connected ranking uses same-origin proxy and requires consent before fetching', async () => {
  const { client, calls } = fake([{ body: { game_ids: [game] } }]);
  const slate = { time_cursor: cursor, games: [card] };
  await assert.rejects(() => client.recommend(slate, '2025-10-21', false), /consent/);
  assert.equal(calls.length, 0);
  assert.deepEqual(await client.recommend(slate, '2025-10-21', true), [card]);
  assert.equal(calls[0].url, `/api/profiles/${profile}/recommendations/watchability`);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    slate_date: '2025-10-21', candidate_game_ids: [game], consent_to_outcome_ranking: true,
    planned_minutes_per_game: 120,
  });
});

test('queue reads and writes stay cursor-scoped without passive result disclosure', async () => {
  const queued = { game_id: game, queue_state: 'queued', game: card };
  const { client, calls } = fake([
    { body: { time_cursor: cursor, items: [queued] } },
    { status: 204 },
    { status: 204 },
    { body: { time_cursor: '2026-10-14T12:00:00Z', items: [] } },
  ]);
  assert.deepEqual((await client.queue(cursor)).items, [queued]);
  await client.saveQueue(game, 'done', cursor);
  await client.removeQueue(game, cursor);
  assert.deepEqual(calls.slice(0, 3).map((c) => c.options.method), ['GET', 'PUT', 'DELETE']);
  assert.ok(calls[0].url.includes('view=replay'));
  assert.deepEqual(JSON.parse(calls[1].options.body), { time_cursor: cursor, queue_state: 'done' });
  assert.equal(calls[2].url, `/api/profiles/${profile}/watch-queue/${game}?time_cursor=${encodeURIComponent(cursor)}`);
  assert.equal(calls.some((c) => /reveal|watchability|\/why/.test(c.url)), false);
  await assert.rejects(client.queue(cursor), /another tab/);
  await assert.rejects(client.saveQueue(game, 'acknowledged', cursor));
  assert.equal(calls.length, 4);
});
