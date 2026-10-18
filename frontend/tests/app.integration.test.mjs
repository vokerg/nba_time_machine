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
const response = (body, status = 200) => new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
async function until(condition) {
  for (let n = 0; n < 30 && !condition(); n++) await tick();
  assert.ok(condition(), 'expected rendered state was not reached');
}
function button(text) { return [...document.querySelectorAll('button')].find((el) => el.textContent.includes(text)); }
async function click(text) { const el = button(text); assert.ok(el, text); await act(async () => el.click()); }
async function mount(fetcher, mediaFetcher = async () => response({ time_cursor: cursor, items: [] })) {
  window.localStorage.clear();
  window.localStorage.setItem('nba-time-machine:profile:v1', profile);
  globalThis.fetch = (url, options) => url.includes("/media?") ? mediaFetcher(url, options) : fetcher(url, options);
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
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/reveal')) { acknowledged = true; return response({ game_id: game, disclosure: 'full', home_score: 100, away_score: 90, result: 'Home won' }); }
    return response({ ...slate, games: [{ ...card, state: acknowledged ? 'acknowledged' : 'sealed' }] });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.equal(calls.length, 2);
    assert.doesNotMatch(document.querySelector('.game-card').textContent, /100|Home won/);
    await click('Show score');
    assert.equal(calls.length, 2);
    await click('Yes, show score');
    await until(() => document.querySelector('.result-box'));
    assert.match(document.querySelector('.result-box').textContent, /100/);
    const revealedCall = calls.find((c) => c.url.endsWith('/reveal'));
    assert.equal(revealedCall.options.method, 'POST');
    assert.equal(calls.filter((c) => c.options.method === 'PUT').length, 0);
    // A reload resumes stored acknowledgement but still keeps scores hidden.
    await unmount(root);
    const resumed = await mount(async (url) => response(
      url.includes('/timeline/') ? timeline :
      url.includes('/watch-queue') ? { time_cursor: cursor, items: [] } :
      { ...slate, games: [{ ...card, state: 'acknowledged' }] }
    ));
    try {
      await until(() => document.querySelector('.game-card'));
      assert.match(document.querySelector('.game-card').textContent, /Score revealed/);
      assert.equal(document.querySelector('.result-box'), null);
    } finally { await unmount(resumed); }
  } catch (e) { await unmount(root); throw e; }
});

test('changing schedule view rejects an old pending slate and shows explicit missing coverage', async () => {
  let old;
  const calls = [];
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('games?date=') && url.includes('view=replay')) return new Promise((resolve) => { old = resolve; });
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
    assert.equal(calls.find((c) => c.url.includes('games?date=') && c.url.includes('view=replay')).options.signal.aborted, true);
    assert.match(document.body.textContent, /missing provider coverage/);
  } finally { await unmount(root); }
});


test('schedule arrows browse adjacent Eastern dates without moving the saved NBA world', async () => {
  const calls = [];
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/timeline/')) return response(timeline);
    return response(slate);
  });
  try {
    await until(() => document.querySelector('.game-card'));
    const date = document.querySelector('#nba-date');
    assert.equal(date.value, '2026-10-13');
    assert.equal(document.querySelector('label[for="nba-date"]').textContent, 'Game date · Eastern');
    const next = document.querySelector('button[aria-label="Next NBA date"]');
    const previous = document.querySelector('button[aria-label="Previous NBA date"]');
    assert.ok(next);
    assert.ok(previous);
    await act(async () => next.click());
    await until(() => date.value === '2026-10-14' &&
      calls.some((call) => call.url.includes('games?date=2026-10-14&view=replay')));
    await act(async () => previous.click());
    await until(() => date.value === '2026-10-13' &&
      calls.filter((call) => call.url.includes('games?date=2026-10-13&view=replay')).length === 2);
    assert.equal(calls.some((call) => call.options.method === 'PUT'), false);
    assert.equal(calls.some((call) => call.url.includes('/reveal')), false);
    assert.equal(calls.filter((call) => call.url.includes('/watch-queue')).length, 0);
    assert.match(document.querySelector('#timeline-heading').textContent, /Oct 13, 2026/);
  } finally { await unmount(root); }
});

test('historical profile defaults to season replay and advancement follows the NBA date', async () => {
  const calls = [];
  let saved = { ...timeline, time_cursor: '2025-11-03T12:00:00Z' };
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/watch-queue')) return response({ time_cursor: saved.time_cursor, items: [] });
    if (url.includes('/timeline/')) {
      if (options.method === 'PUT') saved = { ...saved, time_cursor: JSON.parse(options.body).time_cursor };
      return response(saved);
    }
    return response({ time_cursor: saved.time_cursor, games: [{ ...card, scheduled_tip: '2025-11-03T23:00:00Z' }] });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.ok(calls.some((c) => c.url.endsWith('date=2025-11-03&view=replay')));
    assert.equal(document.querySelector('select').value, 'replay');
    assert.match(document.body.textContent, /Schedule coverage may be incomplete/);
    assert.equal(document.querySelector('.result-box'), null);
    await act(async () => document.querySelector('.timeline-details summary').click());
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
  const checkbox = document.querySelector('.ranking-consent input[type="checkbox"]');
  assert.ok(checkbox);
  await act(async () => checkbox.click());
}

test('mounted ranking requires fresh consent, has no time-budget controls and excludes favorites, keeps ordinary list unchanged', async () => {
  const other = '00000000-0000-0000-0000-000000000003';
  const cards = [
    { ...card, home_team: 'Los Angeles Lakers', away_team: 'Boston Celtics', pregame_interest: 9 },
    { ...card, game_id: other, home_team: 'Miami Heat', away_team: 'Orlando Magic', pregame_interest: 8 },
  ];
  const calls = [];
  const root = await mount(async (url, options) => {
    calls.push({ url, options });
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/recommendations/')) return response({ game_ids: [other, game] });
    return response({ ...slate, games: cards });
  });
  try {
    await until(() => document.querySelector('.game-card'));
    assert.equal(button('Rank by watchability'), undefined); // replay is not an eligible slate
    await choosePregame();
    assert.equal(button('Rank by watchability').disabled, true);
    assert.equal(document.querySelector('.watch-panel input[type="number"]'), null);
    assert.equal(button('Choose within budget'), undefined);
    assert.doesNotMatch(document.querySelector('.watch-panel').textContent, /budget|minutes|allocation/i);
    assert.match(document.querySelector('.guide-pick').textContent, /Boston Celtics at Los Angeles Lakers/);
    assert.equal(calls.filter((call) => call.url.includes('/recommendations/')).length, 0);
    const lakers = [...document.querySelectorAll('.favorite-choices label')].find((el) => el.textContent.includes('Los Angeles Lakers'));
    assert.ok(lakers);
    await act(async () => lakers.querySelector('input').click());
    assert.ok(document.querySelector('.favorite-game'));
    assert.match(document.querySelector('.guide-pick').textContent, /Orlando Magic at Miami Heat/);
    assert.equal(JSON.parse(window.localStorage.getItem('nba-time-machine:favorites:v1:' + profile))[0], 'Los Angeles Lakers');
    await acceptRanking();
    await click('Rank by watchability');
    await until(() => document.querySelector('.watch-panel ol'));
    const request = calls.find((call) => call.url.includes('/recommendations/'));
    assert.equal(request.url, `/api/profiles/${profile}/recommendations/watchability`);
    assert.deepEqual(JSON.parse(request.options.body), {
      slate_date: '2026-10-13', candidate_game_ids: [game, other], consent_to_outcome_ranking: true,
      planned_minutes_per_game: 120,
    });
    assert.deepEqual([...document.querySelectorAll('.watch-panel li')].map((el) => el.textContent), ['Orlando Magic at Miami Heat']);
    const include = document.querySelector('.include-favorites input');
    await act(async () => include.click());
    assert.match(document.querySelector('.guide-pick').textContent, /Boston Celtics at Los Angeles Lakers/);
    assert.deepEqual([...document.querySelectorAll('.watch-panel li')].map((el) => el.textContent),
      ['Orlando Magic at Miami Heat', 'Boston Celtics at Los Angeles Lakers']);
    assert.deepEqual([...document.querySelectorAll('.game-card h3')].map((el) => el.textContent),
      ['Boston Celtics at Los Angeles Lakers', 'Orlando Magic at Miami Heat']);
    assert.equal(button('Rank by watchability').disabled, true);
    assert.equal(document.querySelector('.ranking-consent input[type="checkbox"]').checked, false);
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
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
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


test('missing watchability shows no dead-end why action', async () => {
  const root = await mount(async (url) => {
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/timeline/')) return response(timeline);
    if (url.endsWith('/watchability')) return response({ game_id: game, disclosure: 'watchability' });
    return response(slate);
  });
  try {
    await until(() => document.querySelector('.game-card'));
    const hint = button('Worth watching?');
    const warning = document.getElementById(hint.getAttribute('aria-describedby'));
    assert.match(warning.textContent, /may spoil a surprise/);
    await click('Worth watching?');
    await until(() => document.querySelector('.disclosure-box'));
    assert.match(document.querySelector('.disclosure-box').textContent, /Watchability data is unavailable/);
    assert.equal(button('Why?'), undefined);
  } finally { await unmount(root); }
});

test('favorite teams persist across remount, and the queue is absent from the consumer surface', async () => {
  const requests = [];
  const teamCard = { ...card, home_team: 'Los Angeles Lakers', away_team: 'Golden State Warriors' };
  const backend = async (url) => {
    requests.push(url);
    if (url.includes('/timeline/')) return response(timeline);
    return response({ time_cursor: cursor, games: [teamCard] });
  };
  const root = await mount(backend);
  try {
    await until(() => document.querySelector('.game-card'));
    assert.equal(document.querySelectorAll('.favorite-choices input').length, 30);
    assert.equal(document.querySelector('.queue-panel'), null);
    assert.equal(button('Save to queue'), undefined);
    assert.equal(requests.some((url) => url.includes('/watch-queue')), false);
    const summary = document.querySelector('.team-picker summary');
    await act(async () => summary.click());
    const label = [...document.querySelectorAll('.favorite-choices label')].find((el) => el.textContent.includes('Los Angeles Lakers'));
    assert.ok(label);
    await act(async () => label.querySelector('input').click());
    assert.match(document.querySelector('.game-card').textContent, /Your team/);
    assert.ok(window.localStorage.getItem('nba-time-machine:favorites:v1:' + profile).includes('Los Angeles Lakers'));
    await unmount(root);
    const resumed = createRoot(document.getElementById('root'));
    await act(async () => resumed.render(createElement(App)));
    try {
      await until(() => document.querySelector('.game-card'));
      assert.ok([...document.querySelectorAll('.favorite-choices label')].find(
        (el) => el.textContent.includes('Los Angeles Lakers')).querySelector('input').checked);
      assert.match(document.querySelector('.game-card').textContent, /Your team/);
    } finally { await unmount(resumed); }
  } catch (e) { if (document.querySelector('.game-card')) { /* root may already be unmounted */ } throw e; }
});

test('coarse verdict never offers an explanation button without evidence', async () => {
  const calls = [];
  const root = await mount(async (url) => {
    calls.push(url);
    if (url.includes('/timeline/')) return response(timeline);
    if (url.endsWith('/watchability')) return response({ game_id: game, disclosure: 'watchability', watchability_verdict: 'Worth considering' });
    return response(slate);
  });
  try {
    await until(() => document.querySelector('.game-card'));
    await click('Worth watching?');
    await until(() => document.querySelector('.disclosure-box'));
    assert.match(document.querySelector('.disclosure-box').textContent, /Worth considering/);
    assert.equal(button('Why?'), undefined);
    assert.equal(calls.some((url) => url.endsWith('/why')), false);
  } finally { await unmount(root); }
});

test('reviewed news renders approved metadata, paginates and never requests results', async () => {
  const requests = [];
  const mediaFetcher = async (url, options) => {
    requests.push({ url, options });
    if (url.includes('page=page_2')) return response({
      time_cursor: cursor, items: [{
        item_id: 'feed-2', headline: 'Second reviewed article',
        source: 'NBA press', media_type: 'article', known_at: cursor,
      }],
    });
    return response({
      time_cursor: cursor, items: [{
        item_id: 'feed-1', headline: 'First reviewed article',
        excerpt: 'Safe context', source: 'NBA press', media_type: 'article',
        known_at: cursor, url: 'https://example.org/safe',
      }], next_page: 'page_2',
    });
  };
  const root = await mount(async (url) => {
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    return response(slate);
  }, mediaFetcher);
  try {
    await until(() => document.querySelector('.media-item'));
    assert.match(document.querySelector('.media-item').textContent, /First reviewed article/);
    assert.match(document.querySelector('.media-item').textContent, /NBA press/);
    assert.equal(document.querySelector('.media-item a').getAttribute('rel'), 'noopener noreferrer');
    assert.equal(requests.length, 1);
    await click('Explore News & Buzz');
    await click('Load more reviewed news');
    await until(() => document.querySelectorAll('.media-item').length === 2);
    assert.equal(requests.length, 2);
    assert.match(requests[1].url, /page=page_2/);
    assert.equal(document.querySelectorAll('.media-item').length, 2);
    assert.equal(requests.every((r) => r.options.method === 'GET'), true);
    assert.equal(document.querySelector('.result-box'), null);
  } finally { await unmount(root); }
});

test('individual result reveal cannot advance or refetch general media', async () => {
  let count = 0;
  const root = await mount(async (url) => {
    if (url.includes('/timeline/')) return response(timeline);
    if (url.includes('/watch-queue')) return response({ time_cursor: cursor, items: [] });
    if (url.includes('/reveal')) return response({
      game_id: game, disclosure: 'full', home_score: 123, away_score: 100,
    });
    return response(slate);
  }, async () => {
    count += 1;
    return response({ time_cursor: cursor, items: [{ item_id: 'early', headline: 'Safe earlier story' }] });
  });
  try {
    await until(() => document.querySelector('.media-item') && document.querySelector('.game-card'));
    await click('Show score');
    await click('Yes, show score');
    await until(() => document.querySelector('.result-box'));
    assert.equal(count, 1);
    assert.equal(document.querySelector('.media-item').textContent.includes('123'), false);
  } finally { await unmount(root); }
});

test('stale media load is aborted when the global cursor advances', async () => {
  let release;
  let current = timeline;
  const calls = [];
  const root = await mount(async (url, options) => {
    if (url.includes('/timeline/')) {
      if (options.method === 'PUT') current = { ...current, time_cursor: JSON.parse(options.body).time_cursor };
      return response(current);
    }
    if (url.includes('/watch-queue')) return response({ time_cursor: current.time_cursor, items: [] });
    return response({ time_cursor: current.time_cursor, games: [card] });
  }, (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return new Promise((resolve) => { release = resolve; });
    return Promise.resolve(response({
      time_cursor: current.time_cursor,
      items: [{ item_id: 'new', headline: 'Known at advanced cursor' }],
    }));
  });
  try {
    await until(() => release && document.querySelector('.game-card'));
    await act(async () => document.querySelector('.timeline-details summary').click());
    await click('Advance 1 day');
    await until(() => document.querySelector('.media-item')?.textContent.includes('advanced cursor'));
    release(response({ time_cursor: cursor, items: [{ item_id: 'stale', headline: 'Stale old story' }] }));
    await tick();
    assert.equal(calls[0].options.signal.aborted, true);
    assert.doesNotMatch(document.querySelector('.media-section').textContent, /Stale old story/);
  } finally { await unmount(root); }
});
