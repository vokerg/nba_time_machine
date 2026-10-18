"use strict";
const $ = (id) => document.getElementById(id);
const labels = {
  clutch: ["Clutch time", "Full credit at · minutes"],
  lead_changes: ["Lead changes", "Full credit at · changes"],
  comeback: ["Winner’s largest deficit", "Full credit at · points"],
  overtime: ["Overtime", "Full credit at · periods"],
};
let report = null,
  selected = null,
  config = null,
  reviews = {},
  busy = false,
  dirty = false;
const number = (value) =>
  value === null || value === undefined ? "—" : Number(value).toFixed(2);
function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}
function status(text, error = false) {
  $("status").textContent = text;
  $("status").className = error ? "error" : "";
}
function setBusy(value) {
  busy = value;
  for (const id of [
    "load",
    "verify",
    "preview",
    "reset",
    "export-config",
    "export-session",
  ])
    $(id).disabled = value || (!report && !["load", "verify"].includes(id));
  $("import").disabled = value || !report;
  for (const id of ["day", "asof", "version", "medium", "high"])
    $(id).disabled = value;
  for (const input of $("controls").querySelectorAll("input, select"))
    input.disabled = value;
  if (dirty) {
    $("export-config").disabled = true;
    $("export-session").disabled = true;
  }
}
function markDirty(event) {
  if (
    !["day", "asof"].includes(event?.target?.id) &&
    [$("version").value].some(
      (v) =>
        v === report?.baseline_config.version ||
        v === report?.default_candidate_config?.version,
    )
  )
    $("version").value = "experiment-v1";
  dirty = true;
  $("export-config").disabled = true;
  $("export-session").disabled = true;
  status("Settings changed. Recalculate proposed scores before exporting. Scores below still use the last calculated settings.");
}
function fillConfig(value) {
  config = structuredClone(value);
  $("version").value = value.version;
  $("medium").value = value.medium_from;
  $("high").value = value.high_from;
  $("controls").replaceChildren();
  for (const [key, [label, unit]] of Object.entries(labels)) {
    const block = el("div", undefined, "control");
    block.append(el("div", label, "control-name"));
    const fields = el("div", undefined, "control-fields");
    for (const [type, title] of [
      ["weights", "Weight"],
      ["scales", unit],
    ]) {
      const holder = el("label", title);
      const input = el("input");
      input.type = "number";
      input.min = type === "weights" ? "0" : "0.000001";
      input.max = type === "weights" ? "1000" : "1000000000";
      input.step = "any";
      input.value =
        type === "scales" && key === "clutch"
          ? value[type][key] / 60000
          : value[type][key];
      input.id = `${type}-${key}`;
      input.addEventListener("input", () => {
        if (
          [$("version").value].some(
            (v) =>
              v === report?.baseline_config.version ||
              v === report?.default_candidate_config?.version,
          )
        )
          $("version").value = "experiment-v1";
        markDirty();
      });
      holder.append(input);
      fields.append(holder);
    }
    block.append(fields);
    $("controls").append(block);
  }
  if (value.schema_version >= 2)
    $("controls").append(WorkbenchEnrichment.controls(value, markDirty));
  if (value.schema_version >= 3)
    $("controls").append(WorkbenchContext.controls(value, markDirty));
  if (value.schema_version >= 5)
    $("controls").append(WorkbenchStars.controls(value, markDirty));
  $("formula").textContent =
    value.schema_version >= 2
      ? "Proposed score = drama + player bonus + extreme-pattern bonus" + (value.schema_version >= 3 ? " + game-importance bonus" : "") + (value.schema_version >= 5 ? " + Star Power bonus" : "") + ", capped at 10. Includes clutch time, lead changes, comeback size and overtime."
      : "Proposed score uses drama only with this legacy formula: clutch time, lead changes, comeback size and overtime. Player and extreme-pattern bonuses are not included.";
}
function readConfig() {
  const next = {
    schema_version: config?.schema_version || 1,
    version: $("version").value,
    weights: {},
    scales: {},
    medium_from: Number($("medium").value),
    high_from: Number($("high").value),
  };
  for (const key of Object.keys(labels)) {
    next.weights[key] = Number($(`weights-${key}`).value);
    next.scales[key] =
      Number($(`scales-${key}`).value) * (key === "clutch" ? 60000 : 1);
  }
  if (next.schema_version >= 2)
    Object.assign(next, WorkbenchEnrichment.read(config));
  if (next.schema_version === 3) next.context = WorkbenchContext.read(config);
  if (next.schema_version >= 4) next.importance = WorkbenchContext.read(config);
  if (next.schema_version >= 5) next.star = WorkbenchStars.read(config);
  if (next.schema_version === 6) next.star_snapshot_policy = $("star-snapshot-policy").value;
  return next;
}
async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok)
    throw new Error(
      response.status === 422
        ? "Invalid formula settings. Check the version, positive full-credit values, active weights, bonus limits and ordered start/full-credit thresholds."
        : response.status === 503
          ? "Database inspection is unavailable. Check the local workbench terminal."
          : response.status === 409
            ? "Another verification is running, the result was replaced, or the server restarted. Load stored games or try again after the run finishes."
            : "Request failed. Check the date and local workbench.",
    );
  return response.json();
}
function acceptReport(next) {
  report = next;
  dirty = false;
  const url = new URL(window.location.href);
  url.searchParams.set("date", next.slate_date);
  window.history.replaceState(null, "", url);
  config = structuredClone(next.experiment_config);
  if (!next.games.some((game) => game.game_id === selected))
    selected = next.games[0]?.game_id;
  $("coverage").textContent =
    `${next.games.filter((game) => game.baseline).length} scorable / ${next.games.length} stored`;
  $("missing").replaceChildren();
  for (const missing of next.missing_criteria) {
    const row = el("div", undefined, "missing-item");
    row.append(
      el("strong", missing.label + " · Not connected"),
      el("p", missing.reason),
    );
    $("missing").append(row);
  }
  renderGames();
  renderDetail();
  status(
    `${next.slate_date} · ${next.games.length} stored games · Evidence cutoff ${next.as_of} · ${next.coverage}`,
  );
}
async function load() {
  setBusy(true);
  status("Reading stored slate and revalidating scoring evidence…");
  try {
    const stamp = $("asof").value
      ? new Date($("asof").value + "Z").toISOString()
      : new Date().toISOString();
    const next = await request(
      `/api/slate?date=${encodeURIComponent($("day").value)}&as_of=${encodeURIComponent(stamp)}`,
    );
    acceptReport(next);
    fillConfig(next.experiment_config);
    await loadRingerStatus();
  } catch (error) {
    status(error.message, true);
  } finally {
    setBusy(false);
  }
}
async function loadRingerStatus() {
  try {
    const r = await request('/api/ringer-status');
    const coverage = r.snapshot_coverage;
    $('ringer-status').textContent = r.state === 'not_configured'
      ? 'Ringer Top 100: automatic collection is not configured.'
      : `Ringer Top 100 · ${r.state} · ${coverage ? coverage.matched + '/100 ESPN identities matched' : 'No validated snapshot yet'} · Snapshot known ${r.snapshot_known_at || 'unknown'} · Last check ${r.last_attempt_at || 'never'} · Next allowed check ${r.next_check_at || 'when configured'} · ${r.latest_run?.code || ''}. Private hobby access; no publisher license claimed. Earlier games can use the first snapshot only under the explicit retrospective policy.`;
  } catch (_) {
    $('ringer-status').textContent = 'Ringer source status unavailable.';
  }
}
function showVerification(result) {
  const panel = $("verification");
  panel.hidden = false;
  panel.replaceChildren(el("h2", `Day verification · ${result.day || ""}`));
  if (result.state === "running") {
    panel.append(el("p", "Fetching and validating ESPN game evidence, with CBS fallback. One bounded run; this can take up to three minutes."));
    return;
  }
  if (result.state === "failed") {
    const message = {
      morning_source_policy_not_ready: "Source policy is not ready. Collection requires reviewed ESPN/CBS registry policies; this button does not enable sources or grant permissions.",
      sports_collection_already_running: "Another sports collection is running. Try again after it finishes.",
      collection_time_limit: "Collection reached its time limit. Some evidence may have been saved; load stored games to inspect it.",
      collection_interrupted: "Collection was interrupted. Load stored games to inspect any evidence already saved.",
    }[result.error] || "Collection failed. Check database/source configuration. Some evidence may already have been saved.";
    panel.append(el("p", message, "error"));
    return;
  }
  panel.append(el("p", `${result.games.length} discovered games · ${result.requests} requests · ${result.captures_written} new evidence captures · Run ${result.run_id || "unknown"} · Finished ${result.finished_at}`));
  if (!result.games.length) panel.append(el("p", result.discovery && !result.errors.length
    ? "Provider returned an empty slate for this Eastern day."
    : "Could not verify the slate. Zero stored games does not establish that no games occurred."));
  for (const game of result.games) {
    panel.append(el("p", `${game.away} at ${game.home} · ${game.status === "pending" ? "Not final — postgame verification pending (no live box fetched)" : game.status} · Play-by-play: ${game.pbp_provider || "unavailable"} · Player box: ${game.box_provider || "unavailable"}${game.errors.length ? " · " + game.errors.join(", ") : ""}`));
  }
  if (result.errors.length) panel.append(el("p", result.errors.join(" · "), "error"));
  for (const attempt of result.attempts.filter((a) => a.status !== "ok"))
    panel.append(el("p", `${attempt.provider} ${attempt.stage}: ${attempt.status}`));
}
async function verifyDay() {
  if (busy) return;
  const day = $("day").value;
  const settings = report ? readConfig() : null;
  setBusy(true);
  try {
    let result = await request("/api/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Workbench-Action": "collect-day" },
      body: JSON.stringify({ slate_date: day }),
    });
    showVerification(result);
    status("Collecting fresh evidence. Proposed scores will refresh when verification finishes…");
    const jobId = result.job_id;
    while (result.state === "running") {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      result = await request(`/api/verify?job_id=${encodeURIComponent(jobId)}`);
      showVerification(result);
    }
    if (result.state !== "finished") {
      status("Verification did not finish. See collection details above.", true);
      return;
    }
    const stamp = new Date().toISOString();
    $("asof").value = stamp.slice(0, 19);
    const next = settings ? await request("/api/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slate_date: day, as_of: stamp, config: settings }),
    }) : await request(`/api/slate?date=${encodeURIComponent(day)}&as_of=${encodeURIComponent(stamp)}`);
    acceptReport(next);
    fillConfig(next.experiment_config);
  } catch (error) {
    status(error.message, true);
  } finally {
    setBusy(false);
  }
}
async function compare(imported) {
  if (!report || busy) return;
  setBusy(true);
  status("Recalculating proposed scores from stored evidence…");
  try {
    const next = await request("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slate_date: $("day").value,
        as_of: new Date($("asof").value + "Z").toISOString(),
        config: imported || readConfig(),
      }),
    });
    acceptReport(next);
    if (imported) fillConfig(imported);
  } catch (error) {
    status(error.message, true);
  } finally {
    setBusy(false);
  }
}
function renderGames() {
  $("games").replaceChildren();
  if (!report.games.length) {
    const row = el("tr");
    const cell = el(
      "td",
      "No stored games at this date and cutoff. Use Fetch & verify this day to collect evidence.",
    );
    cell.colSpan = 5;
    row.append(cell);
    $("games").append(row);
  }
  for (const game of report.games) {
    const row = el(
      "tr",
      undefined,
      selected === game.game_id ? "selected" : "",
    );
    const name = el("td");
    const link = el("button", `${game.away} at ${game.home}`, "game-link");
    link.append(
      el(
        "span",
        `${game.status} · ${new Date(game.tip).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" })} ET`,
      ),
    );
    if (game.context?.source_method === "game_records" && game.context.home && game.context.away) {
      const {home, away} = game.context;
      link.append(el("span", `Entering records: ${away.team} ${away.wins}–${away.losses} · ${home.team} ${home.wins}–${home.losses}`));
    }
    link.addEventListener("click", () => {
      selected = game.game_id;
      renderGames();
      renderDetail();
    });
    name.append(link);
    const appScore = game.archived?.eligible ? game.archived.score : null;
    const change = appScore !== null && game.experiment
      ? game.experiment.score - appScore : null;
    row.append(
      name,
      el("td", number(game.experiment?.score), "proposed-score"),
      el("td", number(appScore)),
      el("td", change === null ? "—" : (change > 0 ? "+" : "") + number(change)),
    );
    const state = el("td");
    state.append(
      el(
        "span",
        game.experiment?.coverage === "partial"
          ? "Incomplete: " + (game.experiment.missing_families || ["player performance"]).join(", ")
          : game.baseline
            ? "Complete for this formula"
            : "Unavailable",
        "badge" +
          (game.baseline && game.experiment?.coverage !== "partial"
            ? ""
            : " partial"),
      ),
    );
    if (game.star_power?.snapshot?.retrospective)
      state.append(el("span", "Retrospective first-snapshot assumption", "badge partial"));
    if (!game.baseline) {
      const primary = game.provider_coverage?.find((p) => p.provider === "espn");
      const reasons = primary?.pbp_errors?.length ? primary.pbp_errors : game.diagnostics;
      state.append(el("small", reasons.filter((reason) => !reason.startsWith("ranking_withheld:")).map(evidenceReason).join(" · ")));
    }
    if (game.provenance?.trajectory_basis === "scoring_actions_v1")
      state.append(el("span", "Reconciled scoring actions", "badge partial"));
    row.append(state);
    $("games").append(row);
  }
}
function evidenceReason(code) {
  return ({
    score_regression: "Provider running score goes backwards",
    invalid_score_transition: "Inconsistent score change",
    scoring_event_mismatch: "Running score disagrees with scoring action",
    period_end_mismatch: "Play-by-play disagrees with quarter totals",
    terminal_mismatch: "Play-by-play disagrees with final score",
    missing_play_ids: "Backup has no stable play IDs",
    clock_order: "Events are out of clock order",
    unknown_participation: "Player participation is unknown",
    missing_player_minutes_or_points: "Player minutes or points are missing",
    partial_team_box: "Incomplete player box score",
    no_stored_provider_game_evidence_at_this_as_of: "No evidence stored by this cutoff",
  })[code] || code.replaceAll("_", " ");
}
function renderDetail() {
  const target = $("detail");
  target.replaceChildren();
  const game = report?.games.find((item) => item.game_id === selected);
  if (!game) {
    target.append(el("h2", "Choose a game"));
    return;
  }
  const top = el("div", undefined, "detail-top");
  top.append(
    el("h2", `${game.away} at ${game.home}`),
    el("span", game.status, "badge"),
  );
  target.append(top, el("p", `Canonical game ${game.game_id}`, "muted"));
  const metrics = el("div", undefined, "metrics");
  const appScore = game.archived?.eligible ? game.archived.score : null;
  const proposal = game.experiment;
  for (const [label, value, description] of [
    [
      "Proposed score · out of 10",
      proposal?.score,
      proposal ? proposal.verdict + (proposal.coverage === "partial" ? " · Incomplete: " + (proposal.missing_families || ["player performance"]).join(", ") : " · For tuning") : "Unavailable: insufficient validated data",
    ],
    [
      "Current app score · out of 10",
      appScore,
      appScore !== null ? "Stored score used for consumer hints" : game.archived ? "Stored score withheld: evidence no longer matches" : "No stored app score at this cutoff",
    ],
  ]) {
    const tile = el("div", undefined, "metric");
    tile.append(el("span", label), el("strong", number(value)), el("small", description));
    metrics.append(tile);
  }
  target.append(metrics);
  target.append(el("p", "Proposed score is the game score being tuned with the selected formula. Current app score remains in use until a new formula is adopted.", "muted"));
  if (proposal) {
    const settings = report.experiment_config;
    target.append(el("p", `Proposed-score verdicts: below ${settings.medium_from} = Lower priority; ${settings.medium_from} to below ${settings.high_from} = Worth considering; ${settings.high_from}–10 = Worth watching.`, "muted"));
  }
  const verification = el("details");
  verification.id = "calculation-check";
  verification.append(el("summary", "Check current app calculation · technical details"));
  verification.append(el("p", `Recalculated original formula: ${number(game.baseline?.score)} / 10. Stored rating: ${number(game.archived?.score)} / 10. ${game.archived?.eligible ? "Stored rating matches current validated evidence." : "A matching, eligible stored rating has not been established."}`));
  verification.append(el("p", "This checks the original drama-only formula against the stored rating. It is a verification step, not an additional proposed score."));
  target.append(verification);
  WorkbenchEnrichment.renderTotals(target, game);
  if (game.diagnostics.length)
    target.append(el("div", game.diagnostics.join(" · "), "notice"));
  if (game.provenance?.trajectory_basis === "scoring_actions_v1")
    target.append(el("p", "Running scores reconstructed from explicit scoring actions and checked against every period and final total. Original provider scores remain in the evidence export.", "notice"));
  for (const provider of game.provider_coverage || []) {
    const describe = (usable, errors) => usable ? "Validated" : (errors || []).map(evidenceReason).join("; ") || "Not available";
    target.append(el("p", `${provider.provider.toUpperCase()} · Play-by-play: ${describe(provider.pbp_usable, provider.pbp_errors)} · Player box: ${describe(provider.box_usable, provider.box_errors)}${provider.source_approved === false ? " · Source policy not approved" : ""}`, "notice"));
  }
  if (game.experiment) {
    target.append(el("h3", "Drama contribution · clutch, lead changes, comeback & overtime"));
    const wrap = el("div", undefined, "table-wrap"),
      table = el("table"),
      head = el("thead"),
      hrow = el("tr");
    for (const name of [
      "Signal",
      "Measured",
      "Full credit at",
      "Magnitude (0–1)",
      "Weight",
      "Share of drama",
      "Game-score points",
    ])
      hrow.append(el("th", name));
    head.append(hrow);
    table.append(head);
    const body = el("tbody");
    for (const part of game.experiment.signals) {
      const row = el("tr");
      for (const value of [
        part.label,
        part.signal === "clutch"
          ? `${number(part.raw / 60000)} min (${part.raw} ms)`
          : `${part.raw} ${part.unit}`,
        part.signal === "clutch"
          ? `${number(part.scale / 60000)} min`
          : part.scale,
        part.normalized.toFixed(4),
        part.weight,
        number(part.effective_weight_percent) + "%",
        part.score_contribution.toFixed(4),
      ])
        row.append(el("td", String(value)));
      body.append(row);
    }
    table.append(body);
    wrap.append(table);
    target.append(
      wrap,
      el(
        "p",
        `Magnitude = measured ÷ full-credit value, limited to 1. Drama contribution: ${(game.experiment.drama_score ?? game.experiment.score).toFixed(4)} game-score points. Weight total: ${game.experiment.weight_denominator}; each share is its weight divided by this total. Formula: ${game.experiment.version}.`,
        "formula",
      ),
    );
  }
  WorkbenchContext.render(target, game);
  if (game.star_power) WorkbenchStars.render(target, game);
  WorkbenchEnrichment.render(target, game);
  const review = reviews[game.game_id] || { rating: "", notes: "" };
  const fields = el("div", undefined, "review"),
    ratingLabel = el("label", "Your target game score · 0–10"),
    rating = el("input");
  rating.type = "number";
  rating.min = "0";
  rating.max = "10";
  rating.step = "0.5";
  rating.value = review.rating;
  rating.id = "review-rating";
  ratingLabel.append(rating);
  const notesLabel = el("label", "Why would you score this game differently?"),
    notes = el("textarea");
  notes.maxLength = 5000;
  notes.value = review.notes;
  notes.placeholder =
    "For example: great matchup, but this formula underweights its context.";
  notes.id = "review-notes";
  notesLabel.append(notes);
  function saveReview() {
    reviews[game.game_id] = { rating: rating.value, notes: notes.value };
  }
  rating.addEventListener("input", saveReview);
  notes.addEventListener("input", saveReview);
  fields.append(ratingLabel, notesLabel);
  target.append(
    el("h3", "Assess the proposed score"),
    fields,
    el(
      "p",
      "Drafts stay in this tab. Export a review session to save them; importing recomputes against stored evidence.",
      "muted",
    ),
  );
  const provenance = el("details");
  provenance.append(el("summary", "Source evidence & data coverage"));
  const info = {
    ...game.provenance,
    archived_snapshot: game.archived?.as_of || null,
    model: game.archived?.model_version || null,
    box_diagnostics: game.box_diagnostics || [],
  };
  provenance.append(el("pre", JSON.stringify(info, null, 2), "meta"));
  if (game.provenance?.source_url) {
    const link = el("a", "Open provider evidence endpoint");
    link.href = game.provenance.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    provenance.append(link);
  }
  target.append(provenance);
  if (game.supporting_plays.length) {
    const support = el("details");
    support.append(
      el(
        "summary",
        `Supporting plays · ${game.supporting_plays.length} events`,
      ),
    );
    const filter = el("select");
    filter.id = "play-filter";
    for (const [value, label] of [
      ["all", "All supporting events"],
      ...Object.entries(labels).map(([key, [name]]) => [key, name]),
    ]) {
      const option = el("option", label);
      option.value = value;
      filter.append(option);
    }
    support.append(filter);
    const wrap = el("div", undefined, "table-wrap");
    function draw() {
      wrap.replaceChildren();
      const table = el("table"),
        head = el("thead"),
        tr = el("tr");
      for (const name of [
        "Source play ID",
        "Period / clock",
        "Score H–A",
        "Supports",
        "Clutch seconds",
      ])
        tr.append(el("th", name));
      head.append(tr);
      table.append(head);
      const body = el("tbody");
      for (const play of game.supporting_plays.filter(
        (play) => filter.value === "all" || play.tags.includes(filter.value),
      )) {
        const row = el("tr");
        const seconds = play.remaining_ms / 1000;
        for (const value of [
          play.source_play_id || "No source ID",
          `${play.period} / ${Math.floor(seconds / 60)}:${(seconds % 60).toFixed(1).padStart(4, "0")}`,
          `${play.home}–${play.away}`,
          play.tags.map((tag) => labels[tag]?.[0] || tag).join(", "),
          number(play.clutch_ms / 1000),
        ])
          row.append(el("td", String(value)));
        body.append(row);
      }
      table.append(body);
      wrap.append(table);
    }
    filter.addEventListener("change", draw);
    draw();
    support.append(wrap);
    target.append(support);
  }
  const raw = el("details");
  raw.append(
    el("summary", "Stored source evidence · technical JSON"),
    el("pre", JSON.stringify(game.evidence, null, 2)),
  );
  target.append(raw);
}
function download(name, value) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const anchor = el("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("load").addEventListener("click", load);
$("verify").addEventListener("click", verifyDay);
$("preview").addEventListener("click", () => compare());
$("reset").addEventListener("click", () => {
  fillConfig(report.default_candidate_config || report.baseline_config);
  compare(report.default_candidate_config || report.baseline_config);
});
$("export-config").addEventListener("click", () =>
  download(config.version + ".json", config),
);
$("export-session").addEventListener("click", () => {
  for (const review of Object.values(reviews)) {
    if (
      review.rating !== "" &&
      (!Number.isFinite(Number(review.rating)) ||
        Number(review.rating) < 0 ||
        Number(review.rating) > 10)
    ) {
      status(
        "Your review ratings must be between 0 and 10 before export.",
        true,
      );
      return;
    }
  }
  download(`nba-review-${report.slate_date}.json`, {
    schema_version: 1,
    kind: "nba-scoring-review",
    report,
    reviews,
  });
});
$("import").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > 5000000) throw new Error("Import is limited to 5 MB.");
    const value = JSON.parse(await file.text());
    if (value.kind === "nba-scoring-review") {
      if (
        value.schema_version !== 1 ||
        !value.report?.experiment_config ||
        !/^\d{4}-\d{2}-\d{2}$/.test(value.report.slate_date) ||
        !Number.isFinite(Date.parse(value.report.as_of))
      )
        throw new Error("Invalid review session.");
      const imported = {};
      for (const [id, review] of Object.entries(value.reviews || {})) {
        if (
          !/^[0-9a-f-]{36}$/i.test(id) ||
          typeof review.notes !== "string" ||
          review.notes.length > 5000 ||
          !(
            review.rating === "" ||
            (Number.isFinite(Number(review.rating)) &&
              Number(review.rating) >= 0 &&
              Number(review.rating) <= 10)
          )
        )
          throw new Error("Invalid review notes.");
        imported[id] = { rating: review.rating, notes: review.notes };
      }
      reviews = imported;
      $("day").value = value.report.slate_date;
      $("asof").value = new Date(value.report.as_of).toISOString().slice(0, 19);
      await compare(value.report.experiment_config);
    } else {
      await compare(value);
    }
  } catch (error) {
    status(error.message, true);
  } finally {
    event.target.value = "";
  }
});
for (const id of ["version", "medium", "high", "day", "asof"])
  $(id).addEventListener("input", markDirty);
const parts = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
}).formatToParts(new Date());
$("day").value = ["year", "month", "day"]
  .map((type) => parts.find((part) => part.type === type).value)
  .join("-");
const dateParam = new URLSearchParams(window.location.search).get("date");
if (dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam))
  $("day").value = dateParam;
$("asof").value = new Date().toISOString().slice(0, 19);
load();
