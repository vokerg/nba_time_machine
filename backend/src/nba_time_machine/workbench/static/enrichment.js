"use strict";
window.WorkbenchEnrichment = (() => {
  const node = (tag, text, cls) => {
    const e = document.createElement(tag);
    if (text !== undefined) e.textContent = text;
    if (cls) e.className = cls;
    return e;
  };
  const fmt = (value) =>
    value === null || value === undefined
      ? "Unavailable"
      : Number(value).toFixed(4);
  const names = {
    points: "Points",
    assists: "Assists",
    rebounds: "Rebounds",
    stocks: "Steals + blocks",
    efficiency: "True shooting",
    max_lead: "Largest lead",
    first_half_lead: "First-half lead",
    quarter_margin: "Quarter margin",
    high_quarter: "High-scoring quarter",
    scoring_drought: "Scoring drought",
  };
  function title(key) {
    if (key === "low_quarter_ceiling")
      return "Low quarter: starts below (points)";
    if (key === "max_bonus") return "Maximum bonus (score points)";
    if (key === "secondary_weight") return "Secondary player axes multiplier";
    if (key === "runner_up_weight") return "Second player multiplier";
    if (key === "second_group_weight") return "Second anomaly group multiplier";
    for (const [prefix, label] of Object.entries(names)) {
      if (key === prefix + "_floor" || key === prefix + "_peak")
        return (
          label +
          (key.endsWith("_floor") ? ": starts above" : ": full credit at") +
          (prefix === "scoring_drought"
            ? " (min)"
            : prefix === "efficiency"
              ? " (%)"
              : "")
        );
    }
    return key.replaceAll("_", " ");
  }
  function factor(key) {
    return key.startsWith("scoring_drought_")
      ? 60000
      : key.startsWith("efficiency_") && !key.endsWith("weight")
        ? 0.01
        : 1;
  }
  function controls(config, changed) {
    const holder = node("div");
    for (const group of ["player", "pattern"]) {
      const section = node("details");
      section.append(
        node(
          "summary",
          group === "player"
            ? "Player-performance settings"
            : "Extreme-pattern settings",
        ),
      );
      const grid = node("div", undefined, "enrichment-controls");
      for (const [key, value] of Object.entries(config[group])) {
        const label = node("label", title(key));
        const input = node("input");
        input.type = "number";
        input.min = "0";
        input.step = "any";
        input.value = value / factor(key);
        input.id = `${group}-${key}`;
        input.addEventListener("input", changed);
        label.append(input);
        grid.append(label);
      }
      section.append(grid);
      holder.append(section);
    }
    holder.append(
      node(
        "p",
        "Heuristic magnitude, not historical percentiles. Thresholds and bonuses are provisional.",
        "muted",
      ),
    );
    return holder;
  }
  function read(config) {
    const result = {};
    for (const group of ["player", "pattern"]) {
      result[group] = {};
      for (const key of Object.keys(config[group]))
        result[group][key] =
          Number(document.getElementById(`${group}-${key}`).value) *
          factor(key);
    }
    return result;
  }
  function table(headers, rows) {
    const wrap = node("div", undefined, "table-wrap"),
      t = node("table"),
      head = node("thead"),
      hr = node("tr");
    for (const h of headers) hr.append(node("th", h));
    head.append(hr);
    t.append(head);
    const body = node("tbody");
    for (const values of rows) {
      const tr = node("tr");
      for (const value of values) {
        const cell = node("td");
        if (value instanceof Node) cell.append(value);
        else cell.textContent = String(value);
        tr.append(cell);
      }
      body.append(tr);
    }
    t.append(body);
    wrap.append(t);
    return wrap;
  }
  function render(target, game) {
    const e = game.enrichment;
    if (!e) return;
    target.append(node("h3", "Player performances & unusual game patterns"));
    if (!e.candidate_eligible)
      target.append(
        node(
          "p",
          "Measurements below are inspectable, but do not contribute to a combined candidate score for this evidence/configuration.",
          "notice",
        ),
      );
    if (game.experiment?.drama_score !== undefined) {
      const c = game.experiment;
      target.append(
        table(
          ["Candidate component", "Points / 10"],
          [
            ["Game drama", fmt(c.drama_score)],
            ["Player-performance bonus", fmt(c.player_bonus)],
            ["Extreme-pattern bonus", fmt(c.pattern_bonus)],
            ["10-point cap adjustment", fmt(c.cap_adjustment)],
            ["Final rounding", fmt(c.rounding_adjustment)],
            ["Candidate total", fmt(c.score)],
          ],
        ),
      );
      target.append(
        node(
          "p",
          `Candidate = min(10, drama + player bonus + pattern bonus). Coverage: ${c.coverage}. Missing families contribute no estimated value. Saved ratings remain unchanged.`,
          "formula",
        ),
      );
    }
    const players = node("details");
    players.open = true;
    players.append(node("summary", "Individual box-score performances"));
    if (e.players === null)
      players.append(
        node("p", "Unavailable: " + e.player_errors.join(" · "), "notice"),
      );
    else {
      const b = e.player_bonus;
      players.append(
        node(
          "p",
          `Bonus = ${fmt(b.cap)} × min(1, strongest ${fmt(b.strongest)} + ${fmt(b.runner_up_weight)} × runner-up ${fmt(b.runner_up)}) = ${fmt(b.points)}. Players from either team qualify.`,
          "formula",
        ),
      );
      const allLabel = node("label", undefined, "inline-check"),
        all = node("input");
      all.type = "checkbox";
      allLabel.append(
        all,
        document.createTextNode(
          `Show all ${e.players.length} participating players`,
        ),
      );
      players.append(allLabel);
      const list = node("div"),
        detail = node("div");
      players.append(list, detail);
      function show(p) {
        detail.replaceChildren(
          node("h3", `${p.name} · ${p.team} · production breakdown`),
        );
        detail.append(
          table(
            [
              "Axis",
              "Measured",
              "Starts above",
              "Full credit at",
              "Normalized",
            ],
            p.axes.map((a) => [
              a.signal,
              a.raw,
              a.floor,
              a.peak,
              fmt(a.normalized),
            ]),
          ),
        );
        detail.append(
          table(
            ["Severity calculation", "Value"],
            [
              ...Object.entries(p.terms).map(([key, value]) => [
                key.replaceAll("_", " "),
                fmt(value),
              ]),
              ["Before clamp", fmt(p.before_clamp)],
              ["After clamp to 0–1", fmt(p.severity)],
            ],
          ),
        );
        detail.append(
          node(
            "p",
            `Strongest axis + weighted next two axes + scoring-efficiency support + triple-double credit − turnover penalty. True shooting: ${p.true_shooting === null ? "undefined (no attempts)" : (p.true_shooting * 100).toFixed(2) + "%"}; efficiency normalization: ${fmt(p.efficiency_normalized)}. Minutes: ${p.minutes} (${p.minutes_precision}); no per-minute extrapolation. Source box: ${p.box_reference}.`,
            "muted",
          ),
        );
      }
      function draw() {
        list.replaceChildren(
          table(
            [
              "Player / team",
              "PTS",
              "REB",
              "AST",
              "STL",
              "BLK",
              "TO",
              "TS%",
              "Severity",
            ],
            (all.checked ? e.players : e.players.slice(0, 8)).map((p) => {
              const link = node("button", `${p.name} · ${p.team}`, "game-link");
              link.addEventListener("click", () => show(p));
              const s = p.statistics;
              return [
                link,
                s.PTS,
                s.REB,
                s.AST,
                s.STL,
                s.BLK,
                s.TO,
                p.true_shooting === null
                  ? "—"
                  : (p.true_shooting * 100).toFixed(1),
                fmt(p.severity),
              ];
            }),
          ),
        );
      }
      all.addEventListener("change", draw);
      draw();
      if (e.players.length) show(e.players[0]);
    }
    target.append(players);
    const patterns = node("details");
    patterns.open = true;
    patterns.append(
      node("summary", "Extreme game patterns · measurements & evidence"),
    );
    if (e.patterns === null)
      patterns.append(
        node("p", "Unavailable: " + e.pattern_errors.join(" · "), "notice"),
      );
    else {
      const b = e.pattern_bonus;
      patterns.append(
        node(
          "p",
          `Dominance group = max(lead, first-half lead, quarter margin) = ${fmt(b.groups.dominance)}. Scoring-extremes group = max(low quarter, high quarter, drought) = ${fmt(b.groups.scoring_extremes)}. Bonus = ${fmt(b.cap)} × min(1, strongest group + ${fmt(b.second_group_weight)} × second group) = ${fmt(b.points)}.`,
          "formula",
        ),
      );
      patterns.append(
        table(
          [
            "Measurement",
            "Value / context",
            "Starts at",
            "Full credit at",
            "Normalized",
            "Group",
            "Source play IDs",
          ],
          e.patterns.map((p) => {
            const time = p.unit === "milliseconds",
              raw = time
                ? (p.raw / 60000).toFixed(2) + " min"
                : p.raw + " " + p.unit;
            const evidence =
              p.source_play_ids.join(" → ") +
              (p.start_elapsed_ms !== undefined
                ? ` (elapsed ${(p.start_elapsed_ms / 60000).toFixed(2)}–${(p.end_elapsed_ms / 60000).toFixed(2)} min)`
                : "");
            return [
              p.label,
              `${raw} · ${p.team} · period ${p.period}`,
              time ? p.floor / 60000 : p.floor,
              time ? p.peak / 60000 : p.peak,
              fmt(p.normalized),
              p.group,
              evidence,
            ];
          }),
        ),
      );
      patterns.append(
        node(
          "p",
          "Quarter measurements use full regulation quarters, never shorter overtime periods. Droughts count game-clock time across periods, excluding breaks. These are extremity heuristics, not claims of historical rarity.",
          "muted",
        ),
      );
    }
    target.append(
      patterns,
      node(
        "p",
        `Measurement version: ${e.measurement_version}. ${e.rarity_status}`,
        "muted",
      ),
    );
  }
  return { controls, read, render };
})();
