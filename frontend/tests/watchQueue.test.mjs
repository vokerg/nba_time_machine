import test from 'node:test';
import assert from 'node:assert/strict';
import { parseWatchQueue } from '../src/watchQueue.ts';

const cursor = '2026-10-13T12:00:00Z';
const gameId = '00000000-0000-0000-0000-000000000002';
const card = { game_id: gameId, disclosure: 'pregame', state: 'sealed', home_team: 'Home', away_team: 'Away' };

test('queue metadata is personal-only and projected cards pass the existing whitelist', () => {
  const items = [{ game_id: gameId, queue_state: 'done', game: card }];
  assert.deepEqual(parseWatchQueue({ time_cursor: cursor, items }).items, items);
  assert.deepEqual(parseWatchQueue({ time_cursor: cursor, items: [{ game_id: gameId, queue_state: 'queued', game: null }] }).items[0].game, null);
  for (const bad of [
    { ...items[0], game: { ...card, home_score: 124 } },
    { ...items[0], game: { ...card, result: 'Home won' } },
    { ...items[0], game: { ...card, watchability_verdict: 'Amazing' } },
    { ...items[0], game: { ...card, thumbnail_url: 'spoiler.jpg' } },
    { ...items[0], game: { ...card, game_id: '00000000-0000-0000-0000-000000000003' } },
    { ...items[0], queue_state: 'acknowledged' },
    { ...items[0], home_score: 124 },
  ]) {
    assert.throws(() => parseWatchQueue({ time_cursor: cursor, items: [bad] }));
  }
  assert.throws(() => parseWatchQueue({ time_cursor: cursor, items: [items[0], items[0]] }), /Duplicate/);
  assert.throws(() => parseWatchQueue({ time_cursor: cursor, items: [], headline: 'Future news' }));
});
