"use strict";
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/nba_time_machine/operator/operator.js"), "utf8");

class FakeNode {
  constructor(type = "div") {
    this.type = type;
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.listeners = {};
    this.body = null;
  }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  appendChild(child) { this.children.push(child); }
  replaceChildren(...children) { this.children = [...children]; }
  querySelector(selector) {
    assert.equal(selector, "tbody");
    if (!this.body) this.body = new FakeNode("tbody");
    return this.body;
  }
}

function fixture() {
  const names = ["day", "season", "source", "status", "filters", "state",
    "sources", "games", "outcomes", "runs", "notes", "json", "csv"];
  const nodes = Object.fromEntries(names.map(name => [name, new FakeNode()]));
  const urls = [];
  const downloads = [];
  const data = {
    day: "2026-10-16",
    sources: [{
      id: "source-1", name: "<img src=x onerror=alert(1)>",
      configured: true, verified: "verified", enabled: false,
      requires_auth: false, cadence_minutes: 1440,
      last_attempt_at: null, last_success_at: null, last_outcome: "partial",
      freshness: "disabled", last_error_code: "http_403"
    }],
    games: [{
      game_id: "game", season: "2026-2027", away: "Team A", home: "Team B",
      status: "final", observation_source: "source-1",
      scheduled_tip_at: null, last_observed_at: null,
      play_by_play: {status: "partial", source: "source-1"},
      player_box: {status: "not_collected", source: null},
      team_box: {status: "unsupported", source: null},
      latest_evidence_observed_at: null
    }],
    outcomes: [{
      run_id: "run", source_id: "source-1", status: "partial",
      items_seen: 1, captures_written: 0, finished_at: null, error_code: "http_403"
    }],
    runs: [{id: "run", collector: "test", started_at: null, finished_at: null}],
    notes: ["Incomplete evidence is not healthy"]
  };
  const context = {
    document: {
      getElementById: name => {
        assert.ok(nodes[name], "unknown node " + name);
        return nodes[name];
      },
      createElement: type => new FakeNode(type)
    },
    URLSearchParams,
    fetch: async url => {
      urls.push(url);
      return { ok: true, json: async () => data };
    },
    window: {location: {assign: url => downloads.push(url)}}
  };
  vm.runInNewContext(source, context);
  return {nodes, urls, downloads, data};
}

function settle() {
  return new Promise(resolve => setImmediate(resolve));
}

test("operator UI renders only text, unknown data, independent evidence families", async () => {
  const fixtureState = fixture();
  const {nodes} = fixtureState;
  await settle();
  assert.match(nodes.state.textContent, /1 stored games/);
  const firstSource = nodes.sources.body.children[0].children[0].textContent;
  assert.equal(firstSource, "<img src=x onerror=alert(1)> (source-1)");
  assert.equal(nodes.sources.body.children[0].children[9].textContent, "disabled");
  assert.equal(nodes.sources.body.children[0].children[10].textContent, "http_403");
  const game = nodes.games.body.children[0];
  assert.equal(game.children[6].textContent, "partial · source-1");
  assert.equal(game.children[7].textContent, "not_collected");
  assert.equal(game.children[8].textContent, "unsupported");
  assert.equal(game.children[4].textContent, "unknown");
  assert.equal(nodes.notes.children[0].textContent, "Incomplete evidence is not healthy");
  assert.ok(!source.includes("innerHTML"));
});

test("source/day filters and export URLs use the same bounded read API", async () => {
  const f = fixture();
  await settle();
  f.nodes.day.value = "2026-10-13";
  f.nodes.season.value = "2026-2027";
  f.nodes.source.value = "espn-nba-games";
  f.nodes.status.value = "partial";
  f.nodes.filters.listeners.submit({preventDefault() {}});
  await settle();
  assert.match(f.urls.at(-1), /day=2026-10-13/);
  assert.match(f.urls.at(-1), /source=espn-nba-games/);
  f.nodes.csv.listeners.click();
  f.nodes.json.listeners.click();
  assert.match(f.downloads[0], /format=csv/);
  assert.match(f.downloads[1], /format=json/);
  assert.match(f.downloads[0], /source=espn-nba-games/);
  assert.ok(f.urls.every(u => u.startsWith("/api/report?")));
});
