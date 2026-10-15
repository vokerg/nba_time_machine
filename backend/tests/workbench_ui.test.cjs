// Synthetic DOM tests; no browser automation, provider fetches or database access.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("../../frontend/node_modules/jsdom");
const root = path.resolve(__dirname, "../..");
const assets = path.join(root, "backend/src/nba_time_machine/workbench/static");
const baseline = JSON.parse(
  fs.readFileSync(
    path.join(root, "config/ranking/trajectory-baseline-v1.json"),
  ),
);
const enrichedConfig = JSON.parse(
  fs.readFileSync(
    path.join(root, "config/ranking/entertainment-preview-v2.json"),
  ),
);
const id = "11111111-1111-4111-8111-111111111111";
const metric = {
  score: 3.2,
  version: baseline.version,
  verdict: "Lower priority",
  weight_denominator: 70,
  signals: [],
};
function report(config = baseline) {
  return {
    schema_version: 1,
    slate_date: "2026-10-14",
    as_of: "2026-10-15T04:00:00Z",
    coverage: "Fixture",
    baseline_config: baseline,
    experiment_config: config,
    default_candidate_config: enrichedConfig,
    missing_criteria: [],
    games: [
      {
        game_id: id,
        home: "Home",
        away: "Away",
        status: "final",
        tip: "2026-10-15T01:00:00Z",
        archived: { score: 3.2, eligible: true, status: "Matches" },
        baseline: metric,
        experiment: { ...metric, version: config.version },
        diagnostics: [],
        supporting_plays: [],
        evidence: null,
      },
    ],
  };
}
async function setup(initial = baseline) {
  const dom = new JSDOM(
    fs.readFileSync(path.join(assets, "index.html"), "utf8"),
    {
      url: "http://127.0.0.1:8765/?date=2026-10-14",
      runScripts: "outside-only",
    },
  );
  const w = dom.window,
    requests = [],
    downloads = [];
  w.structuredClone = structuredClone;
  w.fetch = async (url, options) => {
    requests.push({ url, options });
    const body = options ? JSON.parse(options.body) : null;
    return { ok: true, json: async () => report(body?.config || initial) };
  };
  w.URL.createObjectURL = (blob) => {
    downloads.push(blob);
    return "blob:test";
  };
  w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () {};
  w.eval(fs.readFileSync(path.join(assets, "enrichment.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(assets, "workbench.js"), "utf8"));
  await new Promise((resolve) => setImmediate(resolve));
  return { w, requests, downloads, close: () => w.close() };
}
function input(w, id, value) {
  const e = w.document.getElementById(id);
  e.value = value;
  e.dispatchEvent(new w.Event("input", { bubbles: true }));
}

test("edits require preview before exports and render source text safely", async () => {
  const s = await setup();
  try {
    input(s.w, "weights-clutch", "50");
    assert.equal(s.w.document.getElementById("export-config").disabled, true);
    assert.equal(s.w.document.getElementById("version").value, "experiment-v1");
    s.w.document.getElementById("preview").click();
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(
      JSON.parse(s.requests.at(-1).options.body).config.weights.clutch,
      50,
    );
    assert.equal(s.w.document.getElementById("export-config").disabled, false);
    s.w.document.getElementById("export-config").click();
    assert.equal(s.downloads.length, 1);
  } finally {
    s.close();
  }
});

test("review import restores notes but recomputes instead of trusting file scores", async () => {
  const s = await setup();
  try {
    const imported = report({ ...baseline, version: "imported-v1" });
    imported.games[0].archived.score = 999;
    const value = {
      schema_version: 1,
      kind: "nba-scoring-review",
      report: imported,
      reviews: { [id]: { rating: "8", notes: "<script>unsafe()</script>" } },
    };
    const file = { size: 1000, text: async () => JSON.stringify(value) };
    const field = s.w.document.getElementById("import");
    Object.defineProperty(field, "files", {
      value: [file],
      configurable: true,
    });
    field.dispatchEvent(new s.w.Event("change", { bubbles: true }));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(s.requests.at(-1).url, "/api/preview");
    assert.equal(s.w.document.getElementById("review-rating").value, "8");
    assert.equal(
      s.w.document.getElementById("review-notes").value,
      "<script>unsafe()</script>",
    );
    assert.equal(s.w.document.querySelectorAll("#detail script").length, 0);
    assert.equal(
      s.w.document.getElementById("detail").textContent.includes("999"),
      false,
    );
  } finally {
    s.close();
  }
});

test("v2 settings and minute-based scales round-trip without dropping enrichment", async () => {
  const s = await setup(enrichedConfig);
  try {
    assert.equal(s.w.document.getElementById("scales-clutch").value, "5");
    input(s.w, "scales-clutch", "6");
    input(s.w, "player-max_bonus", "2");
    input(s.w, "pattern-scoring_drought_floor", "6");
    s.w.document.getElementById("preview").click();
    await new Promise((resolve) => setImmediate(resolve));
    const sent = JSON.parse(s.requests.at(-1).options.body).config;
    assert.equal(sent.schema_version, 2);
    assert.equal(sent.scales.clutch, 360000);
    assert.equal(sent.player.max_bonus, 2);
    assert.equal(sent.pattern.scoring_drought_floor, 360000);
    assert.equal(sent.player.points_peak, enrichedConfig.player.points_peak);
  } finally {
    s.close();
  }
});

test("a legacy config can replace v2 without retaining hidden bonus settings", async () => {
  const s = await setup(enrichedConfig);
  try {
    const field = s.w.document.getElementById("import");
    Object.defineProperty(field, "files", {
      value: [{ size: 100, text: async () => JSON.stringify(baseline) }],
    });
    field.dispatchEvent(new s.w.Event("change", { bubbles: true }));
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(s.w.document.getElementById("player-max_bonus"), null);
    assert.equal(
      s.w.document.getElementById("version").value,
      baseline.version,
    );
    assert.equal(s.w.document.getElementById("scales-clutch").value, "5");
  } finally {
    s.close();
  }
});
