"use strict";
// All data is inserted as text nodes; never trust source titles or diagnostics as HTML.
const byId = (id) => document.getElementById(id);
let active = null;
const display = (v) => v === null || v === undefined || v === "" ? "unknown" : String(v);
function row(table, fields) {
  const tr = document.createElement("tr");
  for (const value of fields) {
    const td = document.createElement("td");
    td.textContent = display(value);
    tr.appendChild(td);
  }
  table.querySelector("tbody").appendChild(tr);
}
function replace(table, records, map) {
  table.querySelector("tbody").replaceChildren();
  for (const record of records) row(table, map(record));
}
function params() {
  const query = new URLSearchParams();
  for (const name of ["day", "season", "source", "status"]) {
    const value = byId(name).value.trim();
    if (value) query.set(name, value);
  }
  return query;
}
function family(value) {
  return value.status + (value.source ? " · " + value.source : "");
}
function show(data) {
  active = data;
  byId("day").value = data.day;
  replace(byId("sources"), data.sources, (s) => [
    s.name + " (" + s.id + ")", s.configured, s.verified, s.enabled, s.requires_auth, s.cadence_minutes + " min",
    s.last_attempt_at, s.last_success_at, s.last_outcome, s.freshness, s.last_error_code
  ]);
  replace(byId("games"), data.games, (g) => [
    g.away + " at " + g.home, g.season, g.status, g.observation_source,
    g.scheduled_tip_at, g.last_observed_at, family(g.play_by_play),
    family(g.player_box), family(g.team_box), g.latest_evidence_observed_at
  ]);
  replace(byId("outcomes"), data.outcomes, (o) => [
    o.run_id, o.source_id, o.status, o.items_seen, o.captures_written, o.finished_at, o.error_code
  ]);
  replace(byId("runs"), data.runs, (r) => [r.id, r.collector, r.started_at, r.finished_at]);
  const notes = byId("notes");
  notes.replaceChildren();
  for (const note of data.notes) {
    const li = document.createElement("li");
    li.textContent = note;
    notes.appendChild(li);
  }
  byId("state").textContent = data.day + " · " + data.games.length + " stored games · " +
    data.sources.length + " registered sources · observation metadata only";
}
async function inspect() {
  byId("state").textContent = "Reading stored operational metadata…";
  try {
    const response = await fetch("/api/report?" + params().toString(), {cache:"no-store"});
    if (!response.ok) throw Error("Inspection failed (" + response.status + "). Check the date, filters or database.");
    show(await response.json());
  } catch (err) {
    byId("state").textContent = err.message;
  }
}
byId("filters").addEventListener("submit", (event) => { event.preventDefault(); inspect(); });
for (const format of ["json", "csv"]) {
  byId(format).addEventListener("click", () => {
    // Only the server's already-sanitized metadata projection is exportable.
    const query = params();
    query.set("format", format);
    window.location.assign("/api/export?" + query.toString());
  });
}
inspect();
