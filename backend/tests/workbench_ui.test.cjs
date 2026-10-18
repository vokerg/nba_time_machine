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
const contextConfig = JSON.parse(fs.readFileSync(path.join(root, "config/ranking/entertainment-context-v3.json")));
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
async function setup(initial = baseline, transform = (value) => value) {
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
    return { ok: true, json: async () => transform(report(body?.config || initial)) };
  };
  w.URL.createObjectURL = (blob) => {
    downloads.push(blob);
    return "blob:test";
  };
  w.URL.revokeObjectURL = () => {};
  w.HTMLAnchorElement.prototype.click = function () {};
  w.eval(fs.readFileSync(path.join(assets, "enrichment.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(assets, "context.js"), "utf8"));
  w.eval(fs.readFileSync(path.join(assets, "stars.js"), "utf8"));
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

test("proposed score leads, app comparison uses the stored score and verification is collapsed", async () => {
  const s = await setup(enrichedConfig, (value) => {
    value.games[0].archived.score = 2;
    value.games[0].experiment = { ...metric, score: 4.5, coverage: 'partial' };
    return value;
  });
  try {
    const d = s.w.document;
    assert.deepEqual([...d.querySelectorAll('#games tr:first-child td')].slice(1, 4).map(e => e.textContent), ['4.50', '2.00', '+2.50']);
    assert.deepEqual([...d.querySelectorAll('.metric strong')].map(e => e.textContent), ['4.50', '2.00']);
    assert.match(d.querySelector('.metric').textContent, /Proposed score · out of 10/);
    assert.match(d.querySelector('.metric').textContent, /player performance/);
    assert.equal(d.getElementById('calculation-check').open, false);
    assert.match(d.getElementById('calculation-check').textContent, /Recalculated original formula: 3.20/);
    assert.match(d.getElementById('detail').textContent, /below 4 = Lower priority/);
    assert.doesNotMatch(d.body.textContent, /Experimental preview|Recomputed baseline|Saved rating|Δ baseline/);
  } finally { s.close(); }
});

test("withheld archives are historical detail, never presented as the current app score", async () => {
  const s = await setup(baseline, (value) => {
    value.games[0].archived = { score: 9, eligible: false };
    return value;
  });
  try {
    const d = s.w.document;
    assert.equal(d.querySelectorAll('#games td')[2].textContent, '—');
    assert.equal(d.querySelectorAll('#games td')[3].textContent, '—');
    assert.equal(d.querySelectorAll('.metric strong')[1].textContent, '—');
    assert.match(d.querySelectorAll('.metric')[1].textContent, /withheld/);
    assert.match(d.getElementById('calculation-check').textContent, /Stored rating: 9.00/);
    assert.match(d.getElementById('formula').textContent, /drama only with this legacy formula/);
  } finally { s.close(); }
});

test("player magnitude and game-score contributions carry different scales", async () => {
  const s = await setup(enrichedConfig, (value) => {
    const game = value.games[0];
    game.experiment = { ...metric, drama_score: 3.2, player_bonus: 1, pattern_bonus: 0,
      cap_adjustment: 0, rounding_adjustment: 0, score: 4.2, coverage: 'complete' };
    game.enrichment = {
      candidate_eligible: true, measurement_version: 'fixture', rarity_status: 'Fixture',
      players: [{ name: 'Fixture Player', team: 'BOS', severity: .25,
        statistics: {PTS:7, REB:3, AST:11, STL:0, BLK:0, TO:0}, true_shooting: .318,
        axes: [{signal:'assists', raw:11, floor:8, peak:20, normalized:.25}],
        terms: { strongest_axis:.25 }, before_clamp:.25, efficiency_normalized:0,
        minutes:29, minutes_precision:'rounded_minute', box_reference:'fixture' }],
      player_bonus: { cap:4, strongest:.25, runner_up_weight:.25, runner_up:0, points:1 },
      patterns: null, pattern_errors: ['fixture unavailable']
    };
    return value;
  });
  try {
    const d = s.w.document;
    assert.match(d.getElementById('detail').textContent, /How the proposed score adds up/);
    assert.match(d.getElementById('detail').textContent, /Performance magnitude \(0–1\)/);
    assert.match(d.getElementById('detail').textContent, /top player magnitude 0.2500/);
    assert.match(d.getElementById('detail').textContent, /= 1.0000 game-score points/);
    assert.doesNotMatch(d.getElementById('detail').textContent, /Severity|Candidate total/);
  } finally { s.close(); }
});

test("v3 importance controls round-trip percentages and old configs drop context settings", async () => {
  const s = await setup(contextConfig, value => {
    value.games[0].context = {status:'missing', reason:'Fixture missing history', entering_day:'2025-11-10',
      basis:'Reconstructed later', included_in_proposal: value.experiment_config.schema_version===3,
      provenance:[{day:'<img src=x onerror=unsafe()>', observed_at:'Fixture'}], missing_days:['2025-10-21']};
    return value;
  });
  try {
    const d=s.w.document;
    assert.equal(d.getElementById('context-win_pct_floor').value,'50');
    input(s.w,'context-win_pct_floor','55');
    input(s.w,'context-max_bonus','1.5');
    d.getElementById('preview').click();
    await new Promise(resolve => setImmediate(resolve));
    const sent=JSON.parse(s.requests.at(-1).options.body).config;
    assert.equal(sent.schema_version,3);
    assert.equal(sent.context.win_pct_floor,.55);
    assert.equal(sent.context.max_bonus,1.5);
    assert.match(d.getElementById('detail').textContent,/Game importance · entering 2025-11-10/);
    assert.equal(d.querySelectorAll('#detail img').length,0);
    const field=d.getElementById('import');
    Object.defineProperty(field,'files',{value:[{size:100,text:async()=>JSON.stringify(enrichedConfig)}]});
    field.dispatchEvent(new s.w.Event('change',{bubbles:true}));
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(d.getElementById('context-max_bonus'),null);
    assert.equal(JSON.parse(s.requests.at(-1).options.body).config.context,undefined);
  } finally {s.close();}
});


test("v4 uses game records, shows the subtraction and sends no history settings", async () => {
  const config = JSON.parse(fs.readFileSync(path.join(root,"config/ranking/entertainment-records-v4.json")));
  const s=await setup(config,value=>{
    const record={name:'Fixture Team',conference:'East',wins:6,losses:4,games_played:10,win_pct:.6,
      conference_rank:null,league_rank:null,provider_after_wins:7,provider_after_losses:4,removed_result:'win'};
    value.games[0].context={status:'available',source_method:'game_records',entering_day:'2025-11-10',
      home:record,away:{...record,name:'Other Fixture'},standings:[],basis:'Game-specific totals',reason:'Fixture',
      bonus:0,included_in_proposal:true,ranking_note:'Ranks and playoff stakes unavailable',provenance:[],
      calculation:{home_smoothed_win_pct:.55,away_smoothed_win_pct:.55,home_strength_magnitude:.2,
        away_strength_magnitude:.2,strength_magnitude:.2,sample_games:10,sample_confidence:.5,
        matchup_magnitude:.1,combined_magnitude:.1,max_bonus:2}};
    return value;
  });
  try {
    const d=s.w.document;
    assert.equal(d.getElementById('context-leader_rank_limit'),null);
    assert.equal(d.getElementById('context-win_pct_floor').value,'50');
    assert.match(d.getElementById('detail').textContent,/Provider record after game/);
    assert.match(d.getElementById('detail').textContent,/Record entering game/);
    assert.doesNotMatch(d.getElementById('detail').textContent,/All 30 teams|147 earlier|Race proxy/);
    input(s.w,'context-max_bonus','1.5');d.getElementById('preview').click();
    await new Promise(resolve=>setImmediate(resolve));
    const sent=JSON.parse(s.requests.at(-1).options.body).config;
    assert.equal(sent.schema_version,4);assert.equal(sent.importance.max_bonus,1.5);assert.equal(sent.context,undefined);
  } finally{s.close();}
});

test("v5 star settings round trip, missing coverage, and provenance are readable", async () => {
  const starConfig = JSON.parse(fs.readFileSync(path.join(root, "config/ranking/entertainment-stars-v5.json")));
  const s = await setup(starConfig, value => {
    value.games[0].star_power = {status:"unavailable", reason:"No pre-tip snapshot", metric:null, bonus:null,
      included_in_proposal:true, snapshot:{status:"unavailable",reason:"Missing"}, teams:[], settings:starConfig.star,
      unranked_note:"Injury exclusions are possible.", unresolved_identities:[]};
    value.games[0].experiment.star_bonus=null;
    value.games[0].experiment.coverage="partial";
    value.games[0].experiment.missing_families=["star power"];
    return value;
  });
  try {
    assert.match(s.w.document.getElementById("detail").textContent, /Star Power.*established status/);
    assert.match(s.w.document.getElementById("games").textContent, /Incomplete: star power/);
    input(s.w,"star-max_bonus","1.2");input(s.w,"star-top20_end","22");
    s.w.document.getElementById("preview").click();
    await new Promise(resolve => setImmediate(resolve));
    const payload=JSON.parse(s.requests.at(-1).options.body);
    assert.equal(payload.config.star.max_bonus,1.2);
    assert.equal(payload.config.star.top20_end,22);
    assert.deepEqual(payload.config.importance,starConfig.importance);
    assert.equal(payload.config.schema_version,5);
  } finally { s.close(); }
});

test("star details render ranked participation, team contributions and untrusted names safely", async () => {
  const s=await setup();
  try {
    const target=s.w.document.createElement("div");
    s.w.WorkbenchStars.render(target,{star_power:{status:"available",reason:"Fixture",metric:.5,bonus:.75,included_in_proposal:true,
      unranked_note:"Not a quality judgment",settings:{},snapshot:{fact_id:"fixture",provider:"The Ringer",ranking_version:"fixture",published_date:null,available_at:"2026-01-01",coverage:{matched:100}},
      teams:[{team:"BOS",coverage:"complete",errors:[],raw_total:1,normalized:.5,observed_team_minutes:240,expected_team_minutes:240,
        players:[{espn_id:"1",name:"<img src=x onerror=bad()>",rank:1,participation:"played",minutes:30,minutes_precision:"second",rank_value:1,minutes_factor:1,raw_contribution:1,slot_weight:1,contribution:1}]}]}});
    assert.equal(target.querySelector("img"),null);
    assert.match(target.textContent,/Published rank/);assert.match(target.textContent,/Team total: 1.0000/);
    assert.match(target.textContent,/0.7500 game-score points/);
  } finally { s.close(); }
});

test("fetch action saves evidence explicitly then previews current edits with a fresh cutoff", async () => {
  const s = await setup();
  try {
    input(s.w, "weights-clutch", "48");
    const calls = [];
    s.w.setTimeout = (fn) => { setImmediate(fn); return 1; };
    s.w.fetch = async (url, options) => {
      calls.push({ url, options });
      let result;
      if (url === "/api/verify" && options) result = { state: "running", day: "2026-10-14", job_id: "fixture" };
      else if (url === "/api/verify?job_id=fixture") result = {
        state: "finished", day: "2026-10-14", requests: 1, captures_written: 0,
        run_id: "fixture", finished_at: "now", discovery: "espn", errors: [], attempts: [],
        games: [{ home: "BOS", away: "NYK", status: "pending", errors: [], pbp_provider: null, box_provider: null }],
      };
      else result = report(JSON.parse(options.body).config);
      return { ok: true, json: async () => result };
    };
    s.w.document.getElementById("verify").click();
    assert.equal(s.w.document.getElementById("verify").disabled, true);
    for (let i = 0; i < 8; i++) await new Promise(setImmediate);
    assert.equal(calls[0].options.headers["X-Workbench-Action"], "collect-day");
    const preview = JSON.parse(calls.at(-1).options.body);
    assert.equal(preview.config.weights.clutch, 48);
    assert.equal(calls.at(-1).url, "/api/preview");
    assert.ok(new Date(preview.as_of) > new Date("2026-10-15T04:00:00Z"));
    assert.match(s.w.document.getElementById("verification").textContent, /postgame verification pending/);
    assert.equal(s.w.document.getElementById("verify").disabled, false);
  } finally { s.close(); }
});

test("failed collection stays visible without claiming a fresh score", async () => {
  const s = await setup();
  try {
    let calls = 0;
    s.w.fetch = async () => { calls++; return { ok: true, json: async () => ({ state: "failed", error: "morning_source_policy_not_ready" }) }; };
    s.w.document.getElementById("verify").click();
    await new Promise(setImmediate);
    assert.equal(calls, 1);
    assert.match(s.w.document.getElementById("verification").textContent, /does not enable sources/);
    assert.match(s.w.document.getElementById("status").textContent, /did not finish/);
  } finally { s.close(); }
});

test("Ringer readiness shows real coverage, cutoff and next allowed check safely", async () => {
  const s = await setup();
  try {
    s.w.fetch = async (url) => ({ ok: true, json: async () => url === '/api/ringer-status' ? {
      state:'verified', snapshot_coverage:{matched:100}, snapshot_known_at:'2026-10-16T08:00:00Z',
      last_attempt_at:'2026-10-16T07:46:41Z',next_check_at:'2026-10-30T07:46:41Z',
      latest_run:{code:'<script>unsafe()</script>'},
    } : report() });
    s.w.document.getElementById('load').click();
    for(let i=0;i<4;i++) await new Promise(setImmediate);
    const text=s.w.document.getElementById('ringer-status').textContent;
    assert.match(text,/100\/100 ESPN identities matched/);
    assert.match(text,/2026-10-30/);
    assert.match(text,/no publisher license claimed/);
    assert.equal(s.w.document.getElementById('ringer-status').querySelector('script'),null);
  } finally { s.close(); }
});

test("v6 retrospective policy round-trips and labels every assumed ranking", async () => {
  const v6=JSON.parse(fs.readFileSync(path.join(root,'config/ranking/entertainment-stars-backfill-v6.json')));
  const s=await setup(v6,r => {
    r.games[0].star_power={status:'available',reason:'Synthetic retrospectively applied ranking',metric:.5,bonus:.75,included_in_proposal:true,
      teams:[],settings:v6.star,unranked_note:'Absent does not mean low quality.',
      snapshot:{retrospective:true,selection_mode:'first_snapshot_backfill',available_at:'2026-10-16T07:55:13Z',season:'2026-2027',game_season:'2025-2026',cross_season_assumption:true}};
    return r;
  });
  try {
    const policy=s.w.document.getElementById('star-snapshot-policy');
    assert.equal(policy.value,'first_snapshot_backfill');
    assert.match(s.w.document.getElementById('games').textContent,/Retrospective first-snapshot assumption/);
    assert.match(s.w.document.getElementById('detail').textContent,/RETROSPECTIVE RANKING/);
    assert.match(s.w.document.getElementById('detail').textContent,/Cross-season assumption: 2026-2027 ranking used for 2025-2026/);
    policy.value='strict_pre_tip';policy.dispatchEvent(new s.w.Event('change',{bubbles:true}));
    s.w.document.getElementById('preview').click();await new Promise(setImmediate);
    const request=JSON.parse(s.requests.at(-1).options.body);
    assert.equal(request.config.schema_version,6);
    assert.equal(request.config.star_snapshot_policy,'strict_pre_tip');
    assert.deepEqual(request.config.star,v6.star);
  } finally {s.close();}
});


test("collection gaps explain each provider and reconstructed scores are labeled", async () => {
  const s = await setup(baseline, (r) => {
    const g = r.games[0];
    g.baseline = null;
    g.experiment = null;
    g.diagnostics = ["ranking_withheld: incomplete"];
    g.provider_coverage = [
      { provider: "espn", pbp_usable: false, box_usable: true,
        pbp_errors: ["period_end_mismatch"], box_errors: [] },
      { provider: "cbs", pbp_usable: false, box_usable: false,
        pbp_errors: ["missing_play_ids"], box_errors: ["unknown_participation"] },
    ];
    return r;
  });
  try {
    assert.match(s.w.document.getElementById("games").textContent, /Play-by-play disagrees with quarter totals/);
    const detail = s.w.document.getElementById("detail").textContent;
    assert.match(detail, /ESPN · Play-by-play: Play-by-play disagrees with quarter totals · Player box: Validated/);
    assert.match(detail, /Backup has no stable play IDs/);
    assert.match(detail, /Player participation is unknown/);
  } finally { s.close(); }
  const recovered = await setup(baseline, (r) => {
    r.games[0].provenance = { trajectory_basis: "scoring_actions_v1" };
    return r;
  });
  try {
    assert.match(recovered.w.document.getElementById("games").textContent, /Reconciled scoring actions/);
    assert.match(recovered.w.document.getElementById("detail").textContent, /Original provider scores remain in the evidence export/);
  } finally { recovered.close(); }
});

test("cross-provider correction is explicitly labeled as a local preview", async () => {
  const s = await setup(baseline, (r) => {
    r.games[0].recovery = { player: "Synthetic Player", interpretation: "Corroborated surplus free throw." };
    return r;
  });
  try {
    assert.match(s.w.document.getElementById("games").textContent, /CBS-corroborated correction · preview/);
    assert.match(s.w.document.getElementById("detail").textContent, /local proposal only/);
    assert.match(s.w.document.getElementById("detail").textContent, /Both input fact IDs/);
  } finally { s.close(); }
});
