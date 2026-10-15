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
    const settingNames = {
      efficiency_weight: "Scoring-efficiency bonus multiplier",
      triple_double_weight: "Triple-double bonus multiplier",
      turnover_penalty: "Maximum turnover penalty (magnitude units)",
      turnover_scale: "Full turnover penalty at (turnovers)",
    };
    if (settingNames[key]) return settingNames[key];
    if (key === "low_quarter_ceiling")
      return "Low quarter: starts below (points)";
    if (key === "max_bonus") return "Maximum bonus (game-score points)";
    if (key === "secondary_weight") return "Other stat categories: bonus multiplier";
    if (key === "runner_up_weight") return "Second-best player: bonus multiplier";
    if (key === "second_group_weight") return "Second pattern group: bonus multiplier";
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
        "Magnitude runs from 0 (no credit under these settings) to 1 (full credit). Start and full-credit values are provisional, not historical percentiles.",
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
  function renderTotals(target, game) {
    if (game.experiment?.drama_score !== undefined) {
      const c = game.experiment;
      target.append(node("h3", "How the proposed score adds up"));
      target.append(
        table(
          ["Proposed-score component", "Game-score points"],
          [
            ["Drama · clutch, lead changes, comeback & overtime", fmt(c.drama_score)],
            ["Player-performance bonus", fmt(c.player_bonus)],
            ["Extreme-pattern bonus", fmt(c.pattern_bonus)],
            ["10-point cap adjustment", fmt(c.cap_adjustment)],
            ["Final rounding", fmt(c.rounding_adjustment)],
            ["Proposed score · out of 10", fmt(c.score)],
          ],
        ),
      );
      target.append(
        node(
          "p",
          `Proposed score = min(10, drama + player bonus + extreme-pattern bonus). ${c.coverage === "partial" ? "Incomplete: player data is missing; the total includes only available contributions." : "All required data is available."} Current app score stays unchanged.`,
          "formula",
        ),
      );
    }
  }
  function render(target, game) {
    const e = game.enrichment;
    if (!e) return;
    target.append(node("h3", "Player performances & extreme game patterns"));
    if (!e.candidate_eligible)
      target.append(
        node(
          "p",
          "These measurements are shown for inspection. They are not included in the proposed score with the selected data or legacy formula.",
          "notice",
        ),
      );
    target.append(node("p", "Performance magnitude is a 0–1 measure of a player’s stats under this formula. The top two magnitudes determine the player bonus added to the game score. Click a player to see the calculation.", "muted"));
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
          `Player bonus = ${fmt(b.cap)} game-score points × min(1, top player magnitude ${fmt(b.strongest)} + ${fmt(b.runner_up_weight)} × second player magnitude ${fmt(b.runner_up)}) = ${fmt(b.points)} game-score points. Players from either team qualify.`,
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
          node("h3", `${p.name} · ${p.team} · performance calculation`),
        );
        detail.append(node("p", "Each stat category: (measured − start value) ÷ (full-credit value − start value), limited to 0–1.", "muted"));
        detail.append(
          table(
            [
              "Stat category",
              "Measured",
              "Starts above",
              "Full credit at",
              "Magnitude (0–1)",
            ],
            p.axes.map((a) => [
              names[a.signal] || a.signal,
              a.raw,
              a.floor,
              a.peak,
              fmt(a.normalized),
            ]),
          ),
        );
        detail.append(
          table(
            ["Performance magnitude calculation", "Magnitude units"],
            [
              ...Object.entries(p.terms).map(([key, value]) => [
                ({strongest_axis: "Strongest stat category", secondary_axes: "Other stat categories bonus", efficiency_bonus: "Scoring-efficiency bonus", triple_double_bonus: "Triple-double bonus", turnover_penalty: "Turnover penalty"})[key] || key.replaceAll("_", " "),
                fmt(value),
              ]),
              ["Before 0–1 limit", fmt(p.before_clamp)],
              ["Performance magnitude · limited to 0–1", fmt(p.severity)],
            ],
          ),
        );
        detail.append(
          node(
            "p",
            `Strongest stat category + weighted next two categories + scoring-efficiency bonus + triple-double bonus − turnover penalty. True shooting: ${p.true_shooting === null ? "undefined (no attempts)" : (p.true_shooting * 100).toFixed(2) + "%"}; shooting-efficiency magnitude (0–1): ${fmt(p.efficiency_normalized)}. Minutes: ${p.minutes} (${p.minutes_precision}); no per-minute extrapolation. Source box: ${p.box_reference}.`,
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
              "True shooting %",
              "Performance magnitude (0–1)",
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
          `Large leads / margins magnitude = max(overall lead, first-half lead, quarter margin) = ${fmt(b.groups.dominance)}. Scoring-extremes magnitude = max(low quarter, high quarter, drought) = ${fmt(b.groups.scoring_extremes)}. Extreme-pattern bonus = ${fmt(b.cap)} game-score points × min(1, stronger group + ${fmt(b.second_group_weight)} × other group) = ${fmt(b.points)} game-score points. Related patterns share one group to avoid counting the same stretch repeatedly.`,
          "formula",
        ),
      );
      patterns.append(
        table(
          [
            "Measurement",
            "Value / context",
            "Credit starts at",
            "Full credit at",
            "Magnitude (0–1)",
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
              p.group === "dominance" ? "Large leads / margins" : "Scoring extremes",
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
  return { controls, read, render, renderTotals };
})();
