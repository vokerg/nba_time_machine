"use strict";
const $ = id => document.getElementById(id);
let report, selected, busy = false;
const number = value => value == null ? "—" : Number(value).toFixed(2);
function node(tag, text) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  return n;
}
function table(headers, rows) {
  const wrap = node("div"), t = node("table"), head = node("thead"), body = node("tbody"), row = node("tr");
  wrap.className = "table-wrap";
  for (const title of headers) row.append(node("th", title));
  head.append(row);
  for (const values of rows) {
    const r = node("tr");
    for (const value of values) r.append(node("td", String(value ?? "—")));
    body.append(r);
  }
  t.append(head, body); wrap.append(t); return wrap;
}
async function request(url, options) {
  const r = await fetch(url, options);
  if (!r.ok) throw new Error(r.status === 409 ? "An update is already running. Reload after it finishes." : "Dashboard request failed. Check the local server.");
  return r.json();
}
function status(text) { $("status").textContent = text; }
function setBusy(value) {
  busy = value;
  for (const id of ["load", "verify", "publish", "day", "asof"]) $(id).disabled = value;
}
async function load() {
  setBusy(true);
  try {
    const stamp = $("asof").value ? new Date($("asof").value + "Z").toISOString() : new Date().toISOString();
    report = await request(`/api/slate?date=${encodeURIComponent($("day").value)}&as_of=${encodeURIComponent(stamp)}`);
    selected = report.games.some(g => g.game_id === selected) ? selected : report.games[0]?.game_id;
    const url = new URL(window.location.href);
    url.searchParams.set("date", report.slate_date); window.history.replaceState(null, "", url);
    $("coverage").textContent = `${report.games.filter(g => g.rating).length} rated / ${report.games.length} stored`;
    render();
    status(`${report.slate_date} · Evidence cutoff ${report.as_of} · ${report.coverage}`);
  } catch (error) { status(error.message); }
  finally { setBusy(false); }
}
function render() {
  $("games").replaceChildren();
  for (const g of report.games) {
    const row = node("tr"), name = node("td"), button = node("button", `${g.away} at ${g.home}`);
    button.className = "game-link";
    button.append(node("span", g.status));
    button.addEventListener("click", () => { selected = g.game_id; render(); });
    name.append(button); row.className = selected === g.game_id ? "selected" : "";
    row.append(name, node("td", number(g.rating?.score)), node("td", !g.rating ? "Unavailable" : g.published ? "Published" : "Update needed"),
      node("td", !g.rating ? "Insufficient validated evidence" : g.missing_families.length ? `Missing: ${g.missing_families.join(", ")}` : "Complete"));
    $("games").append(row);
  }
  if (!report.games.length) {
    const row = node("tr"), cell = node("td", "No stored games for this date and cutoff.");
    cell.colSpan = 4; row.append(cell); $("games").append(row);
  }
  renderDetail();
}
function renderDetail() {
  const target = $("detail"), g = report.games.find(g => g.game_id === selected);
  target.replaceChildren(node("h2", g ? `${g.away} at ${g.home}` : "Choose a game"));
  if (!g) return;
  if (g.rating) {
    target.append(node("h3", `Watchability ${number(g.rating.score)} / 10`),
      node("p", g.published ? "Published to the viewing guide." : "Update ratings from stored evidence to publish this calculation."),
      table(["Contribution", "Rating points (after cap)", "Magnitude"], g.rating.components.map(p => [p.label, number(p.points), number(p.normalized)])),
      node("p", `Formula: ${g.rating.version}. Contributions are proportionally reduced when the total exceeds 10.`));
    if (g.calculated_at) target.append(node("p", `Saved calculation: ${g.calculated_at}. Use Recalculate saved ratings to replace it.`));
  } else target.append(node("p", "Rating unavailable: no saved calculation at this cutoff. Use Recalculate saved ratings to calculate from stored evidence."));
  if (g.diagnostics.length) target.append(node("p", g.diagnostics.join(" · ")));
  if (g.enrichment?.players) {
    const details = node("details"); details.append(node("summary", "Player performances · all participants"));
    details.append(table(["Player", "PTS", "AST", "REB", "STL + BLK", "TS%", "TO", "Exceptional magnitude"],
      g.enrichment.players.map(p => [p.name, p.statistics.PTS, p.statistics.AST, p.statistics.REB,
        p.statistics.STL + p.statistics.BLK, p.true_shooting == null ? "—" : number(p.true_shooting * 100), p.statistics.TO, number(p.severity)])));
    target.append(details);
  }
  if (g.star_power) {
    const d = node("details"); d.append(node("summary", "Star Power · rank and actual participation"), node("p", g.star_power.reason));
    for (const team of g.star_power.teams) d.append(node("h3", team.team), table(["Player", "Rank", "Minutes", "Participation", "Contribution"],
      team.players.map(p => [p.name, p.rank, p.minutes, p.participation, number(p.contribution)])));
    target.append(d);
  }
  for (const [title, value] of [["Game magnitude measurements", g.enrichment?.patterns], ["Record strength", g.context],
    ["Component provenance and settings", {components:g.rating?.components, settings:g.settings}]]) {
    const d = node("details"); d.append(node("summary", title), node("pre", JSON.stringify(value, null, 2))); target.append(d);
  }
  if (g.rating) {
    const d = node("details"), body = node("pre", "Open to load stored source evidence.");
    d.append(node("summary", "Stored source evidence"), body);
    let requested = false;
    const cutoff = g.rating.as_of || report.as_of;
    d.addEventListener("toggle", async () => {
      if (!d.open || requested) return;
      requested = true;
      body.textContent = "Loading saved evidence…";
      try {
        const value = g.evidence || await request(`/api/evidence/${encodeURIComponent(g.game_id)}?as_of=${encodeURIComponent(cutoff)}`);
        body.textContent = JSON.stringify(value, null, 2);
      } catch {
        body.textContent = "Saved source evidence unavailable. The saved rating is retained.";
        requested = false;
      }
    });
    target.append(d);
  }
}
async function update(fetchEvidence) {
  if (busy) return;
  setBusy(true);
  try {
    let result = await request(fetchEvidence ? "/api/verify" : "/api/publish", {method:"POST",
      headers:{"Content-Type":"application/json", "X-Workbench-Action":"collect-day"}, body:JSON.stringify({slate_date:$("day").value})});
    $("verification").hidden = false;
    const jobId = result.job_id;
    while (result.state === "running") {
      $("verification").textContent = "Updating game ratings…";
      await new Promise(resolve => setTimeout(resolve, 1000));
      result = await request(`/api/verify?job_id=${encodeURIComponent(jobId)}`);
    }
    $("verification").textContent = result.state === "finished"
      ? `Ratings updated: ${result.ratings?.eligible ?? 0} published, ${result.ratings?.unavailable ?? 0} unavailable, ${result.ratings?.failed ?? 0} failed.`
      : `Update failed: ${result.error}. Reload to inspect any completed work.`;
    $("asof").value = new Date().toISOString().slice(0,19);
    await load();
  } catch (error) { status(error.message); }
  finally { setBusy(false); }
}
$("load").addEventListener("click", load);
$("verify").addEventListener("click", () => update(true));
$("publish").addEventListener("click", () => update(false));
const day = new Intl.DateTimeFormat("en-CA", {timeZone:"America/New_York", year:"numeric", month:"2-digit", day:"2-digit"}).formatToParts(new Date());
const param = new URLSearchParams(window.location.search).get("date");
$("day").value = param && /^\d{4}-\d{2}-\d{2}$/.test(param) ? param : ["year","month","day"].map(t => day.find(p => p.type === t).value).join("-");
$("asof").value = new Date().toISOString().slice(0,19);
request("/api/ringer-status").then(r => {
  $("ringer-status").textContent = `Ringer Top 100 · ${r.state} · Snapshot known ${r.snapshot_known_at || "unknown"} · Next check ${r.next_check_at || "when configured"}`;
}).catch(() => { $("ringer-status").textContent = "Ringer source status unavailable."; });
load();
