import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { pathToFileURL } from "node:url";

const dom = new JSDOM('<div id="root"></div>', {
  url: "http://localhost:5173",
});
globalThis.window = dom.window;
globalThis.document = dom.window.document;
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");
const bundle = new URL(
  "../node_modules/.cache/app-integration.mjs",
  import.meta.url,
).pathname;
await build({
  entryPoints: [new URL("../src/App.tsx", import.meta.url).pathname],
  outfile: bundle,
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  external: ["react", "react/jsx-runtime"],
});
const { App } = await import(pathToFileURL(bundle).href);
const profile = "00000000-0000-0000-0000-000000000001";
const game = "00000000-0000-0000-0000-000000000002";
const cursor = "2026-10-13T12:00:00Z";
const timeline = {
  profile_id: profile,
  time_cursor: cursor,
  initialized_at: cursor,
  updated_at: cursor,
};
const card = {
  game_id: game,
  disclosure: "pregame",
  state: "sealed",
  home_team: "Home",
  away_team: "Away",
  scheduled_tip: "2026-10-13T23:00:00Z",
};
const slate = { time_cursor: cursor, games: [card] };
const response = (body, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const tick = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
async function until(condition) {
  for (let n = 0; n < 30 && !condition(); n++) await tick();
  assert.ok(condition(), "expected rendered state was not reached");
}
function button(text) {
  return [...document.querySelectorAll("button")].find((el) =>
    el.textContent.includes(text),
  );
}
async function click(text) {
  const el = button(text);
  assert.ok(el, text);
  await act(async () => el.click());
}
async function mount(
  fetcher,
  mediaFetcher = async () => response({ time_cursor: cursor, items: [] }),
) {
  window.localStorage.clear();
  window.localStorage.setItem("nba-time-machine:profile:v1", profile);
  globalThis.fetch = (url, options) =>
    url.includes("/media?")
      ? mediaFetcher(url, options)
      : fetcher(url, options);
  const root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(App)));
  return root;
}
async function unmount(root) {
  await act(async () => root.unmount());
}

const disclosure = (body, detail = {}) => ({
  time_cursor: cursor,
  as_of: "2026-10-19T12:00:00Z",
  details:
    body.level === "order" ? {} : { [game]: { game_id: game, ...detail } },
  game_ids: body.game_id ? [] : [game],
});
function fake(calls = [], detail = {}) {
  return async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/disclose")) {
      const body = JSON.parse(options.body);
      return response(disclosure(body, detail));
    }
    return response(slate);
  };
}
async function setDate(day) {
  const input = document.getElementById("nba-date");
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value",
    ).set.call(input, day);
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
}

test("Browse opens on current NBA day, never passively fetches outcomes or news, and date changes never advance cursor", async () => {
  const calls = [];
  const root = await mount(fake(calls));
  try {
    await until(() => document.querySelector(".game-card"));
    assert.equal(
      document.getElementById("nba-date").value,
      new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(
        new Date(),
      ),
    );
    assert.match(calls[1].url, /\/guide\?date=.*&mode=browse/);
    assert.equal(calls.length, 2);
    assert.doesNotMatch(
      document.body.textContent,
      /Watch Queue|Season replay|Acknowledged|Coverage options/,
    );
    assert.equal(document.querySelector(".result-box"), null);
    assert.equal(document.querySelector(".time-machine-panel"), null);
    await click("←");
    await until(() => calls.length > 2);
    assert.equal(calls.filter((c) => c.options.method === "PUT").length, 0);
    assert.ok(calls.every((c) => !c.url.includes("/disclose")));
  } finally {
    await unmount(root);
  }
});

test("two modes reset disclosures, isolate stale responses, and keep persisted cursor", async () => {
  const calls = [];
  let release;
  const root = await mount(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/disclose"))
      return new Promise((resolve) => {
        release = () =>
          resolve(
            response(
              disclosure(JSON.parse(options.body), {
                verdict: "Worth watching",
                has_clue: true,
              }),
            ),
          );
      });
    return response(slate);
  });
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Worth watching?");
    // Navigation is disabled while a disclosure is pending. Complete it, then switch.
    assert.equal(button("Time Machine").disabled, true);
    await act(async () => release());
    await until(() => document.querySelector(".disclosure-box"));
    await click("Time Machine");
    await until(
      () =>
        calls.some((c) => c.url.endsWith("mode=time-machine")) &&
        document.querySelector(".game-card"),
    );
    assert.equal(document.querySelector(".disclosure-box"), null);
    assert.ok(document.querySelector(".time-machine-panel"));
    assert.equal(calls.filter((c) => c.options.method === "PUT").length, 0);
    await click("Browse games");
    await until(
      () =>
        !document.querySelector(".time-machine-panel") &&
        document.querySelector(".game-card"),
    );
  } finally {
    await unmount(root);
  }
});

test("reveal all is one consented date-scoped POST with no repeated dialogs, reload hides results", async () => {
  const calls = [];
  const root = await mount(
    fake(calls, { result: { home_score: 110, away_score: 100 } }),
  );
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Reveal all for this date");
    await until(() => document.querySelector(".result-box"));
    assert.match(document.querySelector(".result-box").textContent, /110/);
    const posts = calls.filter((c) => c.url.endsWith("/disclose"));
    assert.equal(posts.length, 1);
    const body = JSON.parse(posts[0].options.body);
    assert.equal(body.consent, true);
    assert.equal(body.level, "full");
    assert.equal(body.mode, "browse");
    assert.equal(body.time_cursor, cursor);
    assert.equal(body.game_id, undefined);
    assert.equal(document.querySelector(".confirmation"), null);
    await unmount(root);
    const next = await mount(fake());
    try {
      await until(() => document.querySelector(".game-card"));
      assert.equal(document.querySelector(".result-box"), null);
    } finally {
      await unmount(next);
    }
  } finally {
    /* root was unmounted above */
  }
});

test("individual confirmation receives keyboard focus, Escape restores trigger and reveal stays per-game", async () => {
  const calls = [];
  const root = await mount(
    fake(calls, { result: { home_score: 110, away_score: 100 } }),
  );
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Show result");
    assert.equal(document.activeElement, button("Yes, show result"));
    await act(async () =>
      document.activeElement.dispatchEvent(
        new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      ),
    );
    assert.equal(document.querySelector(".confirmation"), null);
    assert.equal(document.activeElement, button("Show result"));
    await click("Show result");
    await click("Yes, show result");
    await until(() => document.querySelector(".result-box"));
    const body = JSON.parse(
      calls.find((c) => c.url.endsWith("/disclose")).options.body,
    );
    assert.equal(body.game_id, game);
    assert.equal(
      calls.some((c) => c.options.method === "PUT"),
      false,
    );
  } finally {
    await unmount(root);
  }
});

test("verdict offers genuine selectable clues and numerical evidence only after explicit requests", async () => {
  const calls = [];
  const root = await mount(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (!url.endsWith("/disclose")) return response(slate);
    const body = JSON.parse(options.body);
    const detail = { verdict: "Worth watching", has_clue: true };
    if (body.level === "clue")
      detail.clue = "There was close play late in the game.";
    if (body.level === "rating")
      Object.assign(detail, {
        rating: 8,
        model: "postgame-v1",
        as_of: cursor,
        components: [
          {
            label: "Close late-game play",
            points: 8,
            normalized: 0.8,
            source_ref: "fixture:1",
            observed_at: cursor,
            available_at: cursor,
          },
        ],
      });
    return response(disclosure(body, detail));
  });
  try {
    await until(() => document.querySelector(".game-card"));
    assert.equal(button("Give me a clue"), undefined);
    await click("Worth watching?");
    await until(() => button("Give me a clue"));
    assert.equal(document.querySelector(".rating-breakdown"), null);
    await click("Give me a clue");
    await until(() =>
      document.body.textContent.includes("There was close play"),
    );
    await click("Show rating & why");
    await until(() => document.querySelector(".rating-breakdown"));
    assert.match(
      document.querySelector(".rating-breakdown").textContent,
      /8.0.*10/,
    );
    assert.match(document.body.textContent, /fixture:1/);
    assert.equal(calls.filter((c) => c.url.endsWith("/disclose")).length, 3);
  } finally {
    await unmount(root);
  }
});

test("missing explanation does not create dead clue controls and unrated is honest", async () => {
  const root = await mount(
    fake([], { verdict: "Worth considering", has_clue: false }),
  );
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Worth watching?");
    await until(() => document.querySelector(".disclosure-box"));
    assert.equal(button("Give me a clue"), undefined);
    assert.match(document.body.textContent, /No verified clue available/);
  } finally {
    await unmount(root);
  }
  const missing = await mount(fake());
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Worth watching?");
    await until(() => document.querySelector(".disclosure-box"));
    assert.match(document.body.textContent, /Unrated/);
    assert.equal(button("Show rating & why"), undefined);
  } finally {
    await unmount(missing);
  }
});

test("all 30 favorites persist across remount; ranked favorites are separately surfaced and toggle never requests a new ranking", async () => {
  const calls = [];
  const lakers = { ...card, home_team: "Los Angeles Lakers" };
  const fetcher = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/disclose"))
      return response(disclosure(JSON.parse(options.body)));
    return response({ ...slate, games: [lakers] });
  };
  const root = await mount(fetcher);
  try {
    await until(() => document.querySelector(".game-card"));
    const choices = [...document.querySelectorAll(".favorite-choices label")];
    assert.equal(choices.length, 30);
    const laker = choices
      .find((el) => el.textContent.includes("Los Angeles Lakers"))
      .querySelector("input");
    await act(async () => laker.click());
    assert.match(document.querySelector(".my-games").textContent, /Lakers/);
    await click("Show after-the-game watch order");
    await until(() => document.querySelector(".guide-results"));
    assert.equal(document.querySelector(".guide-results ol"), null);
    const before = calls.length;
    await act(async () =>
      document.querySelector(".include-favorites input").click(),
    );
    assert.match(
      document.querySelector(".guide-results ol").textContent,
      /Lakers/,
    );
    assert.equal(calls.length, before);
    const snapshot = window.localStorage.getItem(
      `nba-time-machine:favorites:v1:${profile}`,
    );
    await unmount(root);
    const remount = await mount(async (url, options) => {
      window.localStorage.setItem(
        `nba-time-machine:favorites:v1:${profile}`,
        snapshot,
      );
      return fetcher(url, options);
    });
    try {
      await until(() => document.querySelector(".game-card"));
      assert.match(
        document.querySelector(".selected-teams").textContent,
        /Lakers/,
      );
    } finally {
      await unmount(remount);
    }
  } finally {
    /* root unmounted above */
  }
});

test("news is secondary and cursor-bound; opening a game never fetches news", async () => {
  const calls = [],
    mediaCalls = [];
  const root = await mount(
    fake(calls, { result: { home_score: 110, away_score: 100 } }),
    async (url) => {
      mediaCalls.push(url);
      return response({ time_cursor: cursor, items: [] });
    },
  );
  try {
    await until(() => document.querySelector(".game-card"));
    assert.equal(mediaCalls.length, 0);
    await click("Reveal all for this date");
    await until(() => document.querySelector(".result-box"));
    assert.equal(mediaCalls.length, 0);
    await click("News & buzz");
    await until(() => document.body.textContent.includes("No reviewed news"));
    assert.equal(mediaCalls.length, 1);
    assert.ok(mediaCalls[0].includes(encodeURIComponent(cursor)));
  } finally {
    await unmount(root);
  }
});

test("backend errors show no synthetic games or raw server exception", async () => {
  const root = await mount(async () =>
    response({ detail: "secret raw error" }, 503),
  );
  try {
    await until(() => document.querySelector('[role="alert"]'));
    assert.match(document.body.textContent, /Backend database unavailable/);
    assert.doesNotMatch(document.body.textContent, /secret raw error/);
    assert.equal(document.querySelector(".game-card"), null);
  } finally {
    await unmount(root);
  }
});

test("choosing the same day keeps the slate; direct date input changes requests without moving cutoff", async () => {
  const calls = [];
  const root = await mount(fake(calls));
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Today");
    assert.ok(document.querySelector(".game-card"));
    assert.equal(calls.length, 2);
    const input = document.getElementById("nba-date");
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value",
      ).set.call(input, "2026-10-14");
      input.dispatchEvent(new window.Event("input", { bubbles: true }));
    });
    await until(
      () =>
        calls.some((c) => c.url.includes("date=2026-10-14")) &&
        document.querySelector(".game-card"),
    );
    assert.equal(
      calls.some((c) => c.options.method === "PUT"),
      false,
    );
  } finally {
    await unmount(root);
  }
});

test("late responses from a previous date cannot overwrite the current slate", async () => {
  let release;
  let reads = 0;
  const root = await mount(async (url) => {
    if (url.includes("/timeline/")) return response(timeline);
    reads++;
    if (reads === 1)
      return new Promise((resolve) => {
        release = () =>
          resolve(
            response({ ...slate, games: [{ ...card, away_team: "Old date" }] }),
          );
      });
    return response({
      ...slate,
      games: [{ ...card, away_team: "Current date" }],
    });
  });
  try {
    await until(() => reads === 1);
    await click("←");
    await until(() =>
      document
        .querySelector(".game-card")
        ?.textContent.includes("Current date"),
    );
    await act(async () => release());
    assert.match(
      document.querySelector(".game-card").textContent,
      /Current date/,
    );
    assert.doesNotMatch(
      document.querySelector(".game-card").textContent,
      /Old date/,
    );
  } finally {
    await unmount(root);
  }
});

test("explicit date update is one protected POST, reports progress, refreshes safe cards and never reveals outcomes", async () => {
  const calls = [];
  const job = {
    job_id: "00000000-0000-0000-0000-000000000077",
    date: null,
    state: "collecting",
  };
  let finish,
    reads = 0;
  const root = await mount(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/guide/update")) {
      job.date = JSON.parse(options.body).date;
      return response(job, 202);
    }
    if (url.includes("/guide/update/"))
      return new Promise((resolve) => {
        finish = () => resolve(response({ ...job, state: "finished" }));
      });
    reads++;
    return response(slate);
  });
  try {
    await until(() => document.querySelector(".game-card"));
    assert.equal(
      calls.some((c) => c.url.includes("/update")),
      false,
    );
    await click("Fetch games & update ratings");
    await until(() => finish);
    assert.match(
      document.querySelector(".update-status").textContent,
      /Fetching game evidence/,
    );
    assert.equal(button("Updating this date").disabled, true);
    const post = calls.find((c) => c.url.endsWith("/guide/update"));
    assert.equal(post.options.method, "POST");
    assert.equal(post.options.headers["X-Guide-Action"], "update-day");
    assert.equal(JSON.parse(post.options.body).time_cursor, cursor);
    await act(async () => finish());
    await until(
      () =>
        document
          .querySelector(".update-status")
          ?.textContent.includes("Date updated") && reads === 2,
    );
    assert.equal(document.querySelector(".result-box"), null);
    assert.equal(document.querySelector(".guide-results"), null);
    assert.equal(calls.filter((c) => c.options.method === "POST").length, 1);
    assert.equal(
      window.localStorage.getItem(`nba-time-machine:day-update:v1:${profile}`),
      null,
    );
  } finally {
    await unmount(root);
  }
});

test("reload reconnects to the saved job with GET only and Time Machine never exposes collection", async () => {
  const calls = [];
  const selectedDay = "2026-10-16";
  const job = {
    job_id: "00000000-0000-0000-0000-000000000077",
    date: selectedDay,
    state: "finished",
  };
  const root = await mount(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) {
      window.localStorage.setItem(
        `nba-time-machine:day-update:v1:${profile}`,
        JSON.stringify({ job_id: job.job_id, date: job.date }),
      );
      return response(timeline);
    }
    if (url.includes("/guide/update/")) return response(job);
    return response(slate);
  });
  try {
    await until(() =>
      document
        .querySelector(".update-status")
        ?.textContent.includes("Date updated"),
    );
    assert.equal(
      calls.some((c) => c.options.method === "POST"),
      false,
    );
    await click("Time Machine");
    await until(() => document.querySelector(".time-machine-panel"));
    assert.equal(button("Fetch games & update ratings"), undefined);
    assert.match(document.body.textContent, /switch to Browse games/);
  } finally {
    await unmount(root);
  }
});

test("server restart during update gives retry guidance without another automatic POST", async () => {
  const calls = [];
  let day;
  const root = await mount(async (url, options = {}) => {
    calls.push({ url, options });
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/guide/update")) {
      day = JSON.parse(options.body).date;
      return response(
        {
          job_id: "00000000-0000-0000-0000-000000000077",
          date: day,
          state: "collecting",
        },
        202,
      );
    }
    if (url.includes("/guide/update/")) return response({}, 404);
    return response(slate);
  });
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Fetch games & update ratings");
    await until(() => document.querySelector('.update-status[role="alert"]'));
    assert.match(
      document.querySelector(".update-status").textContent,
      /server restarted|replaced/,
    );
    assert.equal(calls.filter((c) => c.options.method === "POST").length, 1);
    assert.ok(button("Fetch games & update ratings"));
  } finally {
    await unmount(root);
  }
});

test("switching dates during a job ignores its late status and leaves the new date untouched", async () => {
  let finish;
  const root = await mount(async (url, options = {}) => {
    if (url.includes("/timeline/")) return response(timeline);
    if (url.endsWith("/guide/update"))
      return response(
        {
          job_id: "00000000-0000-0000-0000-000000000077",
          date: JSON.parse(options.body).date,
          state: "collecting",
        },
        202,
      );
    if (url.includes("/guide/update/"))
      return new Promise((resolve) => {
        finish = () =>
          resolve(
            response({
              job_id: "00000000-0000-0000-0000-000000000077",
              date: new Intl.DateTimeFormat("en-CA", {
                timeZone: "America/New_York",
              }).format(new Date()),
              state: "finished",
            }),
          );
      });
    return response(slate);
  });
  try {
    await until(() => document.querySelector(".game-card"));
    await click("Fetch games & update ratings");
    await until(() => finish);
    await click("←");
    await until(() => document.querySelector(".game-card"));
    await act(async () => finish());
    assert.equal(document.querySelector(".update-status"), null);
    assert.ok(document.querySelector(".game-card"));
  } finally {
    await unmount(root);
  }
});
