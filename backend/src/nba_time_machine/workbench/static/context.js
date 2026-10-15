"use strict";
window.WorkbenchContext = (() => {
  const names = {
    prior_games: "Win% smoothing: prior games at 50%",
    minimum_games: "Minimum earlier games per team",
    confidence_games: "Full sample confidence at (games)",
    win_pct_floor: "Strong-team credit starts above (win %)",
    win_pct_peak: "Strong-team full credit at (win %)",
    leader_rank_limit: "Leader credit starts above conference rank (1 = best)",
    close_games: "Standings race: no proximity credit at gap (games)",
    boundary_games: "Standings race: no cutoff credit at distance (games)",
    late_games_floor: "Late-season credit starts after (games played)",
    late_games_peak: "Late-season full credit at (games played)",
    max_bonus: "Maximum importance bonus (game-score points)",
  };
  const node = (tag, text) => {
    const value = document.createElement(tag);
    if (text !== undefined) value.textContent = text;
    return value;
  };
  const fmt = (value) => value === null || value === undefined ? "Unavailable" : Number(value).toFixed(4);
  const percentage = (value) => value === null || value === undefined ? "Unavailable" : (value * 100).toFixed(1) + "%";
  function controls(config, changed) {
    const section = node("details");
    section.append(node("summary", "Game-importance settings"));
    const grid = node("div");
    grid.className = "enrichment-controls";
    for (const [key, value] of Object.entries(config.context)) {
      const label = node("label", names[key]);
      const input = node("input");
      input.id = "context-" + key;
      input.type = "number";
      input.min = "0";
      input.step = key === "minimum_games" ? "1" : "any";
      input.value = key.startsWith("win_pct_") ? value * 100 : value;
      input.addEventListener("input", changed);
      label.append(input);
      grid.append(label);
    }
    section.append(grid, node("p", "Importance uses earlier records, shared ranks and a late-season race proxy. Exact tiebreakers and playoff consequences are not calculated."));
    return section;
  }
  function read(config) {
    return Object.fromEntries(Object.keys(config.context).map(key => [key,
      Number(document.getElementById("context-" + key).value) / (key.startsWith("win_pct_") ? 100 : 1)]));
  }
  function table(headers, rows) {
    const wrap = node("div"), table = node("table"), head = node("thead"), row = node("tr");
    wrap.className = "table-wrap";
    headers.forEach(label => row.append(node("th", label)));
    head.append(row); table.append(head);
    const body = node("tbody");
    rows.forEach(values => {
      const row = node("tr");
      values.forEach(value => row.append(node("td", String(value))));
      body.append(row);
    });
    table.append(body); wrap.append(table); return wrap;
  }
  const record = row => [row.name, row.conference, `${row.wins}–${row.losses}`, row.games_played,
    percentage(row.win_pct), row.conference_rank ?? "Unavailable", row.league_rank ?? "Unavailable"];
  function render(target, game) {
    const context = game.context;
    if (!context) return;
    target.append(node("h3", `Game importance · entering ${context.entering_day}`));
    target.append(node("p", context.basis), node("p", context.reason));
    if (!context.included_in_proposal)
      target.append(node("p", "Inspection only: importance is not added to the proposed score with this legacy formula or unavailable game trajectory."));
    if (context.home && context.away) {
      const headers = ["Team", "Conference", "Earlier W–L", "Games played", "Win %", "Conference rank · ties shared", "League rank · ties shared"];
      target.append(table(headers, [record(context.home), record(context.away)]));
      target.append(node("p", `${context.games_used} earlier regular-season games used. Target-day and later results are excluded. ${context.ranking_note}`));
      const all = node("details");
      all.append(node("summary", "All 30 teams · reconstructed opening-day standings"), table(headers, context.standings.map(record)));
      target.append(all);
    }
    const c = context.calculation;
    if (c) {
      target.append(table(["Importance calculation", "Value"], [
        ["Home win % after 50% prior smoothing", percentage(c.home_smoothed_win_pct)],
        ["Away win % after 50% prior smoothing", percentage(c.away_smoothed_win_pct)],
        ["Both teams strong · weaker normalized win %", fmt(c.strength_magnitude)],
        ["Both teams high in conference · weaker rank magnitude", fmt(c.leaders_magnitude)],
        ["Earlier games · smaller sample", c.sample_games],
        ["Sample confidence (0–1)", fmt(c.sample_confidence)],
        ["Matchup magnitude · max(strength, leaders) × confidence", fmt(c.matchup_magnitude)],
        ["Same conference", c.same_conference ? "Yes" : "No"],
        ["Standings gap between teams (games)", fmt(c.games_gap)],
        ["Closeness (0–1)", fmt(c.closeness)],
        ["Late-season progress (0–1)", fmt(c.late_season)],
        ["Distance to tied 6th/10th boundary (games)", fmt(c.boundary_gap)],
        ["Boundary proximity (0–1)", fmt(c.boundary_proximity)],
        ["Race proxy · same conference × closeness × late season × boundary", fmt(c.race_magnitude)],
        ["Importance magnitude · max(matchup, race)", fmt(c.combined_magnitude)],
        ["Maximum importance bonus (game-score points)", fmt(c.max_bonus)],
        [context.included_in_proposal ? "Importance bonus added (game-score points)" : "Inspectable bonus · not added", fmt(context.bonus)],
      ]));
      target.append(node("p", "Win% smoothing = (wins + prior games ÷ 2) ÷ (games played + prior games). Both-team measurements use the weaker team's value. Leader magnitude = (rank limit − shared conference rank) ÷ (rank limit − 1), limited to 0–1. Confidence = smaller sample ÷ full-confidence games, limited to 1. Importance uses the stronger of matchup and race to avoid adding correlated signals twice."));
    }
    if (context.missing_days?.length)
      target.append(node("p", "Missing or invalid history days: " + context.missing_days.join(", ")));
    const provenance = node("details");
    provenance.append(node("summary", "Importance source evidence · days, timestamps & earlier results"),
      node("pre", JSON.stringify(context.provenance, null, 2)));
    target.append(provenance);
  }
  return {controls, read, render};
})();
