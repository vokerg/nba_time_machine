"use strict";
window.WorkbenchStars = (() => {
  const names = {
    top5_value: "Elite band rank value (0–1)", top20_value: "Strong band endpoint value (0–1)",
    top50_value: "Moderate band endpoint value (0–1)", top100_value: "Rank 100 value (0–1)",
    top5_end: "Elite band ends at rank", top20_end: "Strong band ends at rank", top50_end: "Moderate band ends at rank",
    full_minutes: "Full participation at (minutes)", minutes_exponent: "Minutes factor exponent",
    second_weight: "Second participating star multiplier", third_weight: "Third participating star multiplier",
    team_normalizer: "Team total divided by (then capped at 1)", both_teams_weight: "Both-team matchup share (0–1)",
    max_bonus: "Maximum Star Power bonus (game-score points)",
  };
  const node = (tag, text) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; };
  const fmt = v => v === null || v === undefined ? "Unavailable" : Number(v).toFixed(4);
  function controls(config, changed) {
    const section = node("details"), grid = node("div"); grid.className = "enrichment-controls";
    section.append(node("summary", "Star Power settings · experimental"));
    if (config.schema_version === 6) {
      const label = node("label", "Ranking snapshot policy"), select = node("select");
      select.id = "star-snapshot-policy";
      for (const [value, text] of [["first_snapshot_backfill", "Use first snapshot for earlier games · retrospective"], ["strict_pre_tip", "Strict: snapshot must be known before tipoff"]]) {
        const option = node("option", text); option.value = value; select.append(option);
      }
      select.value = config.star_snapshot_policy; select.addEventListener("change", changed);
      label.append(select); section.append(label);
    }
    for (const [key, value] of Object.entries(config.star)) {
      const label = node("label", names[key]), input = node("input");
      input.id = "star-" + key; input.type = "number"; input.min = "0";
      input.step = key.endsWith("_end") ? "1" : "any"; input.value = value;
      input.addEventListener("input", changed); label.append(input); grid.append(label);
    }
    section.append(grid, node("p", "Rank values interpolate between band endpoints. These initial values are experimental, not calibrated. The snapshot policy is an explicit tuning assumption; source timestamps and identity checks remain intact."));
    return section;
  }
  function read(config) { return Object.fromEntries(Object.keys(config.star).map(k => [k, Number(document.getElementById("star-" + k).value)])); }
  function table(headers, rows) {
    const wrap = node("div"), t = node("table"), head = node("thead"), tr = node("tr"), body = node("tbody");
    wrap.className = "table-wrap"; headers.forEach(h => tr.append(node("th", h))); head.append(tr); t.append(head);
    rows.forEach(values => { const row = node("tr"); values.forEach(v => row.append(node("td", String(v)))); body.append(row); });
    t.append(body); wrap.append(t); return wrap;
  }
  function render(target, game) {
    const s = game.star_power; if (!s) return;
    target.append(node("h3", "Star Power · established status × actual participation"));
    target.append(node("p", `${s.status === "available" ? "Available" : "Unavailable"}: ${s.reason}`));
    target.append(node("p", `Star Power (0–1): ${fmt(s.metric)}. ${s.bonus === null ? "Bonus unavailable; no Star Power points included." : `${s.included_in_proposal ? "Bonus added" : "Inspectable bonus · not added"}: ${fmt(s.bonus)} game-score points.`}`));
    target.append(node("p", s.unranked_note));
    const snap = s.snapshot;
    if (snap?.retrospective) target.append(node("p", `RETROSPECTIVE RANKING · First snapshot applied to this earlier game. Captured ${snap.available_at}; it was not known at tipoff.${snap.cross_season_assumption ? ` Cross-season assumption: ${snap.season} ranking used for ${snap.game_season}.` : ""}`));
    if (snap?.fact_id) target.append(node("p", `${snap.provider} · ${snap.ranking_version} · published ${snap.published_date || "unknown"} (date only) · known ${snap.available_at} · ${snap.coverage.matched}/100 identities matched.`));
    for (const team of s.teams) {
      target.append(node("h4", `${team.team} · ${team.coverage} participation coverage`));
      if (team.errors.length) target.append(node("p", team.errors.join(" · ")));
      if (!team.players.length) target.append(node("p", s.status === "available" ? "No ranked participants in the complete snapshot." : "Ranked participants cannot be established without a complete eligible snapshot."));
      target.append(table(["Player · ESPN ID", "Published rank", "Participation", "Actual minutes", "Rank value", "Minutes factor", "Raw contribution", "Top-three multiplier", "Team contribution"], team.players.map(p => [
        `${p.name} · ${p.espn_id}`, p.rank, p.participation, p.minutes === null ? "Unknown" : `${p.minutes} (${p.minutes_precision})`,
        fmt(p.rank_value), fmt(p.minutes_factor), fmt(p.raw_contribution), fmt(p.slot_weight), fmt(p.contribution),
      ])));
      target.append(node("p", `Team total: ${fmt(team.raw_total)}; normalized: ${fmt(team.normalized)}. Observed player minutes: ${fmt(team.observed_team_minutes)} / ${team.expected_team_minutes} expected.`));
    }
    target.append(node("p", "Minutes factor = min(1, actual minutes ÷ full-participation minutes) raised to the configured exponent. Top three participating players by published rank receive diminishing multipliers. Team magnitude = min(1, team total ÷ normalizer). Game magnitude = (1 − both-team share) × stronger team + both-team share × √(home × away). Bonus = magnitude × maximum bonus. DNP contributes zero; missing data produces no combined bonus."));
    if (s.unresolved_identities?.length) {
      const unresolved = node("details"); unresolved.append(node("summary", `${s.unresolved_identities.length} unresolved ranking identities`), node("pre", JSON.stringify(s.unresolved_identities, null, 2))); target.append(unresolved);
    }
    const provenance = node("details");
    // Ranking table is not included in every exported public artifact; workbench is private.
    const {players, ...metadata} = snap || {};
    provenance.append(node("summary", "Star Power snapshot provenance & settings"), node("pre", JSON.stringify({snapshot: metadata, settings: s.settings, measurement_version: s.measurement_version}, null, 2))); target.append(provenance);
  }
  return {controls, read, render};
})();
