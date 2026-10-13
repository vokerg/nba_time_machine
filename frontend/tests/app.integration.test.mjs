import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { pathToFileURL } from 'node:url';

const dom = new JSDOM('<div id="root"></div>', { url: 'http://localhost:5173' });
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, 'navigator', { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import('react-dom/client');
const bundle = new URL('../node_modules/.cache/app-integration.mjs', import.meta.url).pathname;
await build({ entryPoints: [new URL('../src/App.tsx', import.meta.url).pathname], outfile: bundle,
  bundle: true, format: 'esm', platform: 'node', jsx: 'automatic', external: ['react', 'react/jsx-runtime'] });
const { App } = await import(pathToFileURL(bundle).href);
const profile = '00000000-0000-0000-0000-000000000001';
const game = '00000000-0000-0000-0000-000000000002';
const cursor = '2026-10-13T12:00:00Z';
const timeline = { profile_id: profile, time_cursor: cursor, initialized_at: cursor, updated_at: cursor };
const card = { game_id: game, disclosure: 'pregame', state: 'sealed', home_team: 'Home', away_team: 'Away', scheduled_tip: '2026-10-13T23:00:00Z' };
const slate = { time_cursor: cursor, games: [card] };
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
async function until(condition) {
  for (let n = 0; n < 30 && !condition(); n++) await tick();
  assert.ok(condition(), 'expected rendered state was not reached');
}
function button(text) { return [...document.querySelectorAll('button')].find((el) => el.textContent.includes(text)); }
async function click(text) { const el = button(text); assert.ok(el, text); await act(async () => el.click()); }
async function mount(fetcher) {
  window.localStorage.clear();
  window.localStorage.setItem('nba-time-machine:profile:v1', profile);
  globalThis.fetch = fetcher;
  const root = createRoot(document.getElementById('root'));
  await act(async () => root.render(createElement(App)));
  return root;
}
async function unmount(root) { await act(async () => root.unmount()); }

test('rendered loading and database error states contain no synthetic fallback', async () => {
  let finish;
  const root = await mount(() => new Promise((resolve) => { finish = resolve; }));
  try {
    assert.match(document.body.textContent, /Connecting to backend/);
    assert.equal(document.querySelectorAll('.game-card').length, 0);
    finish(response({}, 503));
    await until(() => document.querySelector('[role="alert"]'));
    assert.match(document.body.textContent, /Backend database unavailable/);
    assert.equal(document.querySelectorAll('.game-card').length, 0);
  } finally { await unmount(root); }
});

test('rendered cards fetch no passive outcomes; full reveal requires confirmation and reload preserves backend state', async () => {
  const calls = [];
  let acknowledged = false;
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/reveal')) { acknowledged = true; return response({ game_id: game, disclosure: 'full', home_score: 100, away_score: 90, result: 'Home won' }); }
    return response({ ...slate, games: [{ ...card, state: acknowledged ? 'acknowledged' : 'sealed' }] });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.equal(calls.length, 2);
    assert.doesNotMatch(document.querySelector('.game-card').textContent, /100|Home won/);
    await click('Reveal result');
    assert.equal(calls.length, 2);
    await click('Yes, reveal score');
    await until(() => document.querySelector('.result-box'));
    assert.match(document.querySelector('.result-box').textContent, /100/);
    assert.equal(calls[2].options.method, 'POST');
    assert.ok(calls[2].url.endsWith('/reveal'));
    assert.equal(calls.filter((c) => c.options.method === 'PUT').length, 0);
    // A reload resumes stored acknowledgement but still keeps scores hidden.
    await unmount(root);
    const resumed = await mount(async (url) => response(url.includes('/timeline/') ? timeline : { ...slate, games: [{ ...card, state: 'acknowledged' }] }));
    try {
      await until(() => document.querySelector('.game-card'));
      assert.match(document.querySelector('.game-card').textContent, /Acknowledged/);
      assert.equal(document.querySelector('.result-box'), null);
    } finally { await unmount(resumed); }
  } catch (e) { await unmount(root); throw e; }
});

test('changing schedule view rejects an old pending slate and shows explicit missing coverage', async () => {
  let old;
  const calls = [];
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('view=replay')) return new Promise((resolve) => { old = resolve; });
    return response({ time_cursor: cursor, games: [] });
  });
  try {
    await until(() => old && document.querySelector('select'));
    assert.match(document.body.textContent, /Loading games/);
    const select = document.querySelector('select');
    await act(async () => { select.value = 'observed'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    await until(() => document.body.textContent.includes('No covered games'));
    old(response(slate));
    await tick();
    assert.equal(document.querySelectorAll('.game-card').length, 0);
    assert.equal(calls[1].options.signal.aborted, true);
    assert.match(document.body.textContent, /missing provider coverage/);
  } finally { await unmount(root); }
});


test('historical profile defaults to season replay and advancement follows the NBA date', async () => {
  const calls = [];
  let saved = { ...timeline, time_cursor: '2025-11-03T12:00:00Z' };
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/timeline/')) {
      if (options.method === 'PUT') saved = { ...saved, time_cursor: JSON.parse(options.body).time_cursor };
      return response(saved);
    }
    return response({ time_cursor: saved.time_cursor, games: [{ ...card, scheduled_tip: '2025-11-03T23:00:00Z' }] });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.ok(calls[1].url.endsWith('date=2025-11-03&view=replay'));
    assert.equal(document.querySelector('select').value, 'replay');
    assert.match(document.body.textContent, /retrospective matchups/);
    assert.equal(document.querySelector('.result-box'), null);
    await click('Advance 1 day');
    await until(() => calls.some((c) => c.url.endsWith('date=2025-11-04&view=replay')));
    assert.equal(document.querySelector('input[type="date"]').value, '2025-11-04');
    assert.equal(calls.filter((c) => c.url.includes('/reveal')).length, 0);
  } finally { await unmount(root); }
});


async function choosePregame() {
  const select = document.querySelector('select');
  await act(async () => { select.value = 'pregame'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
  await until(() => document.querySelector('.game-card') && !document.body.textContent.includes('Loading games'));
}
async function acceptRanking() {
  const checkbox = document.querySelector('.watch-panel input[type="checkbox"]');
  assert.ok(checkbox);
  await act(async () => checkbox.click());
}

test('mounted ranking requires fresh consent, sends budget without favorites, keeps ordinary list unchanged', async () => {
  const other = '00000000-0000-0000-0000-000000000003';
  const cards = [card, { ...card, game_id: other, home_team: 'Other' }];
  const calls = [];
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/recommendations/')) return response({ game_ids: [other, game] });
    return response({ ...slate, games: cards });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.equal(button('Rank by watchability'), undefined); // replay is not an eligible slate
    await choosePregame();
    assert.equal(button('Rank by watchability').disabled, true);
    assert.equal(calls.filter((call) => call.url.includes('/recommendations/')).length, 0);
    for (const checkbox of document.querySelectorAll('.favorite-choices input')) await act(async () => checkbox.click());
    await acceptRanking();
    await click('Choose within budget');
    await until(() => document.querySelector('.watch-panel ol'));
    const request = calls.find((call) => call.url.includes('/recommendations/'));
    assert.equal(request.url, `/api/profiles/${profile}/recommendations/watchability`);
    assert.deepEqual(JSON.parse(request.options.body), {
      slate_date: '2026-10-13', candidate_game_ids: [game, other], consent_to_outcome_ranking: true,
      budget_minutes: 240, planned_minutes_per_game: 120,
    });
    assert.deepEqual([...document.querySelectorAll('.watch-panel li')].map((el) => el.textContent), ['Away at Other', 'Away at Home']);
    assert.deepEqual([...document.querySelectorAll('.game-card h3')].map((el) => el.textContent), ['Away at Home', 'Away at Other']);
    assert.equal(button('Rank by watchability').disabled, true);
    assert.equal(document.querySelector('.watch-panel input[type="checkbox"]').checked, false);
    assert.equal(calls.some((call) => /\/(reveal|watchability|why)$/.test(call.url) && !call.url.includes('/recommendations/')), false);
    await acceptRanking();
    await click('Rank by watchability');
    await until(() => calls.filter((call) => call.url.includes('/recommendations/')).length === 2 && document.querySelector('.watch-panel ol'));
    assert.equal(Object.hasOwn(JSON.parse(calls.at(-1).options.body), 'budget_minutes'), false);
    assert.equal(calls.some((call) => call.options.method === 'PUT'), false);
  } finally { await unmount(root); }
});

test('mounted empty picks mean unavailable coverage and stale picks cannot cross a schedule change', async () => {
  let finish;
  let count = 0;
  const root = await mount(async (url) => {
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/recommendations/')) {
      count++;
      return count === 1 ? response({ game_ids: [] }) : new Promise((resolve) => { finish = resolve; });
    }
    return response(slate);
  });
  try {
    await until(() => document.querySelector('.game-card'));
    await choosePregame();
    await acceptRanking(); await click('Rank by watchability');
    await until(() => document.body.textContent.includes('No eligible picks'));
    assert.match(document.body.textContent, /not a poor-quality verdict/);
    await acceptRanking(); await click('Rank by watchability');
    await until(() => finish);
    // Force an external slate change while ranking is pending, to test generation isolation.
    const select = document.querySelector('select');
    await act(async () => { select.value = 'observed'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    await until(() => document.querySelector('.game-card'));
    finish(response({ game_ids: [game] })); await tick();
    assert.equal(document.querySelector('.watch-panel ol'), null);
    assert.equal(document.body.textContent.includes('No eligible picks'), false);
  } finally { await unmount(root); }
});
