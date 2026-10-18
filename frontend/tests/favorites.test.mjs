import test from 'node:test';
import assert from 'node:assert/strict';
import { NBA_TEAMS, favoriteKey, readFavorites, writeFavorites, isFavoriteGame, visibleWatchOrder } from '../src/favorites.ts';

test('NBA-wide favorites include Lakers independently of the current slate', () => {
  assert.equal(NBA_TEAMS.length, 30);
  assert.equal(new Set(NBA_TEAMS).size, 30);
  assert.ok(NBA_TEAMS.includes('Los Angeles Lakers'));
});

test('favorites persist per profile, sanitize stored values, and survive reload', () => {
  const saved = new Map();
  const storage = {
    getItem: (key) => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  };
  const profile = 'profile-a';
  writeFavorites(storage, profile, ['Los Angeles Lakers', 'Los Angeles Lakers', 'Imaginary Team', 'Boston Celtics']);
  assert.deepEqual(readFavorites(storage, profile), ['Los Angeles Lakers', 'Boston Celtics']);
  assert.deepEqual(readFavorites(storage, 'profile-b'), []);
  assert.equal(favoriteKey(profile).includes('profile-a'), true);
  saved.set(favoriteKey(profile), 'not json');
  assert.deepEqual(readFavorites(storage, profile), []);
  saved.set(favoriteKey(profile), JSON.stringify(['Los Angeles Lakers', null, 15, 'Imaginary Team']));
  assert.deepEqual(readFavorites(storage, profile), ['Los Angeles Lakers']);
});

test('watch order filters favorite games, never reranks the canonical list', () => {
  const games = [
    { game_id: 'a', home_team: 'Los Angeles Lakers', away_team: 'Boston Celtics' },
    { game_id: 'b', home_team: 'Miami Heat', away_team: 'Orlando Magic' },
    { game_id: 'c', home_team: 'Utah Jazz', away_team: 'Los Angeles Lakers' },
  ];
  const favorites = ['Los Angeles Lakers'];
  assert.equal(isFavoriteGame(games[1], favorites), false);
  assert.deepEqual(visibleWatchOrder(games, favorites, false).map((g) => g.game_id), ['b']);
  assert.deepEqual(visibleWatchOrder(games, favorites, true).map((g) => g.game_id), ['a', 'b', 'c']);
  assert.deepEqual(games.map((g) => g.game_id), ['a', 'b', 'c']);
});
