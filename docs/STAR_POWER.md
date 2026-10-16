# Experimental ranking-based Star Power (#98)

Star Power measures established player status multiplied by actual participation.
An unexpected exceptional performance still belongs exclusively to Player
Performance. This schema-5 workbench proposal preserves drama, player production,
extreme patterns, record-based importance and the overall ten-point cap. No
production score, archive, consumer endpoint, spoiler gate or scheduler changes.

## Source review and limits (October 16, 2026)

The [Ringer Top 100](https://www.theringer.com/nba-ranked/top-100) is readable as
an ordered list of 100 linked player cards. The page observed during this review
labels an October 14, 2026 update and describes monthly in-season updates. It
explicitly excludes long-term injured players until they play. Individual profile
URLs use name slugs; these are not ESPN IDs. Names, ranks and optional published
team/source identity can be imported; prose, images and full publisher HTML are
neither needed nor retained by this implementation. No documented licensed ranking
API or stable machine interface was established. This is page discovery and
format inspection, not a successful licensed ingestion smoke.

The site's footer links to [Spotify terms](https://www.spotify.com/us/legal/end-user-agreement/),
which limit access and content use and restrict redistribution. Public readability
does not establish permission to retain/reuse a whole ranking. The source seed
therefore remains **disabled, unverified, metadata-only**, without a permission
reference. There is no network collector. Manual import is an input mechanism,
not a way around these restrictions: obtain authorization covering private
normalized retention and use before reviewing the registry policy. Do not commit
or redistribute a publisher's full list or private permission records.

[ESPN NBArank](https://www.espn.com.sg/nba/story/_/id/46306892/nba-rank-2025-rankings-top-10-players-jokic-durant-lebron)
is a reference only. Its 2025 edition describes predicted contributions for a
single season and is split across ranked-range articles; no ongoing in-season
update promise was verified. The US article did not provide usable ranking text
in the reader; the regional ESPN reference did. [Disney terms](https://disneytermsofuse.com/english/)
restrict automated extraction and copying. No ESPN ranking importer or automatic
fallback is enabled, and the two editorial lists are never silently mixed.
Existing reviewed ESPN **game evidence** access remains a separate source policy.
Robots availability could not be established with the reader; no robots inference
or undocumented endpoint probing was used to grant access.

## Manual normalized snapshot import

The explicit entry point is `backend/scripts/import_player_rankings.py`. It reads
at most 256 KB of local JSON and never fetches a URL, changes source policy or
accepts observation/availability timestamp overrides. From `backend/`:

```bash
.venv/bin/python scripts/import_player_rankings.py /private/authorized-snapshot.json
.venv/bin/python scripts/import_player_rankings.py /private/authorized-snapshot.json --write
```

Default is validation/mapping diagnostics only. Both modes require an existing
`ringer-nba-top100-manual` registry source with the exact reviewed URL,
`manual_player_rankings` adapter, `verified` status, `normalized_full` (or `full`)
retention and nonempty `adapter_settings.permission_reference`. That reference
must match the file. `automated_access` must remain false. The importer is manual
and can run while the source is disabled; it cannot activate the generic scheduler.
Review policy using the existing registry workflow, not an importer flag.
A weekly manual review is recommended (seed cadence 10,080 minutes); no weekly
poller, due-check request or automatic schedule is installed.

The schema is `RankingImport` in `ranking/player_rankings.py`:

```json
{
  "schema_version": 1,
  "provider": "The Ringer",
  "ranking_version": "publisher-edition-label",
  "season": "2026-2027",
  "source_url": "https://www.theringer.com/nba-ranked/top-100",
  "publication_status": "publisher_date_only",
  "published_date": "2026-10-14",
  "publication_reference": "reviewed page or authorized edition reference",
  "permission_reference": "private authorization reference matching registry policy",
  "players": []
}
```

`players` must actually contain exactly 100 rows with unique ranks 1–100. Each
row requires integer `rank` and `name`, optionally `team` (canonical abbreviation),
`source_player_id`, `espn_id`, `espn_name_alias`, `alias_review`. The empty list
above is a schema illustration and intentionally cannot be imported. Unknown
publication uses `publication_status: "unknown"` and no date. Date-only publisher
claims are stored separately and **never establish historical availability**.
Future publication dates are rejected. No preexisting observation history is
asserted by importing an old edition today.

Identity matching uses namespaced ESPN IDs from retained, policy-approved game
box facts, bounded to 5,000 facts (overflow fails explicitly). The catalog retains
supporting fact IDs. Unicode accent/punctuation normalization supports e.g.
Jokić/Jokic; it does not remove generational suffixes, guess initials or perform
fuzzy matching. Unique normalized name plus published team disambiguates candidates;
without a published team, the name must be globally unique in the catalog.
An explicit ID must already have a matching observed name or an explicitly
reviewed alias. An ID validated this way survives a trade without claiming the
ranking's team is current. Team disagreements without an explicit ID stay
unmatched. Duplicate names/ID collisions remain ambiguous, never silently mapped.
Missing identities remain visible; all 100 must resolve before a combined bonus
is available. This conservative rule avoids assuming an unmatched player cannot
be relevant to either team. Expand approved game evidence or review an alias,
then import a mapping revision; never edit a prior fact.

## Persistence and temporal eligibility

No new tables or parallel store. Imports use existing collection runs, outcomes,
policy-limited normalized captures, source items and season-linked temporal facts
(`player_rankings.ringer-v1`). The captured payload is normalized source fields
plus reproducible identity mapping and proof references. Publication date/precision
are retained in the payload; capture/observation/availability use actual server
import time. A publisher content hash and a separate source-plus-mapping revision
hash distinguish changes. Supporting-proof growth alone does not duplicate an
identical mapping. Latest-identical imports record idle/no new capture; A→B→A
preserves three revisions, including the newly observed return to A. Old captures
and temporal facts remain intact. Writes are atomic under a dedicated advisory
transaction lock and a locked registry row. Outcomes expose coverage and validation.

Reads select the latest version with both actual observation and availability
**strictly before scheduled tipoff** and no later than the workbench cutoff, in
the same NBA season. Actual tip is not currently trusted/available, so scheduled
tip is the conservative existing boundary; a delayed game does not extend it.
Invalid, expired or ambiguous latest facts mask older versions. Reader integrity,
coverage and permission checks fail closed; current policy revocation also
withholds a snapshot. A new ranking after a game cannot change that game's chosen
pre-tip version. In particular, the loaded November 10, 2025 games cannot receive
Star Power from a ranking imported in October 2026. No retrospective preview
bypass exists. Source retention/review is not an assertion of a verified publication
history. This task does not support attested historical capture backfills.

## Participation and formula

ESPN `didNotPlay`, actual `MIN`, precision, team and player ID are reused. New
parsing retains independent team diagnostics and preserves the other team's rows
when one team is malformed. Unknown participation is retained as unknown; it is
not DNP. Existing old captures with global structural box errors fail closed.
Star Power requires final ESPN evidence. It checks each team independently:
unique IDs, valid team affiliation, explicit participation, nonconflicting DNP,
minutes within game length and full team-minute coverage. Minute reconciliation allows half a minute per participating row with rounded
minutes, or half a second per row with second precision. Unknown precision is
unavailable. This detects missing minutes beyond source rounding, not an
independently audited roster; tiny omissions within rounding tolerance cannot be
ruled out. No missing minutes are extrapolated. A zero-minute appearance earns no participation credit.
Statistical production is not an input to reputation.

All following settings are explicit/editable in
`config/ranking/entertainment-stars-v5.json` and the workbench:

| Setting | Initial value |
| --- | --- |
| Elite band ends at rank / value | 5 / 1.0 |
| Strong band endpoint rank / value | 20 / 0.65 |
| Moderate band endpoint rank / value | 50 / 0.30 |
| Rank 100 value | 0.05 |
| Full-participation minutes / exponent | 30 / 1 |
| Second / third star multiplier | 0.40 / 0.15 |
| Team normalization divisor | 1.55 |
| Both-team matchup share | 0.60 |
| Maximum game-score bonus | 1.5 |

Ranks 1–5 share the highest value; later values interpolate continuously between
the three declining band endpoints and rank 100. This piecewise curve gives elite
players substantially more credit than ordinary Top 100 players. Slot multipliers
are fixed to three participating players by **published rank**, not game points;
DNP, zero-minute and unknown rows consume no slot. Additional ranked participants
remain visible with zero slot weight.

`minutes_factor = min(1, actual_minutes / full_minutes) ** minutes_exponent`.
Individual raw contribution = rank value × minutes factor. Team total = weighted
sum of its three stars; team magnitude = min(1, total / normalization divisor).
Game magnitude = `(1 − both_team_share) × max(home, away) + both_team_share × sqrt(home × away)`.
Thus one star-heavy team earns some credit, and a two-sided matchup earns more.
The metric is 0–1; bonus is metric × configured maximum, rounded to four decimals.
The proposed total adds this bonus before the unchanged cap of 10. Uncapped score,
cap and rounding adjustments remain inspectable. All values are experimental,
not calibrated percentiles. Absences earn zero, without a second absence penalty.
No ranked participants yields measured zero only with a valid complete snapshot
and complete participation evidence; unavailable evidence yields null.

## Workbench and compatibility

The loopback-only workbench defaults to schema 5. It shows source edition and
actual availability, ranked player IDs/ranks, minutes/precision, explicit status,
rank values, minutes factors, slot weights, contributions, team totals, combined
magnitude, score bonus, unresolved identities and provenance. Controls expose all
formula weights, band boundaries and normalization. Source eligibility cannot be
loosened in formula controls. Preview sessions remain PostgreSQL READ ONLY /
REPEATABLE READ. Exported reviews contain private spoiler-bearing evidence and
may include licensed ranking data; keep them private under the applicable grant.

Schema 1–4 config imports and schema-1 review envelopes keep their existing
arithmetic; schema 5 requires explicit `star` plus the existing `importance`,
`player` and `pattern` settings. No legacy file silently acquires a star term.
Missing Star Power marks schema-5 previews incomplete and adds no invented bonus.
Consumer scores continue using the original production formula.

## Verification limits

Synthetic fixtures use invented player ordering, never a copied publisher Top
100. They verify parsing, all-100 validation, source/mapping revisions, duplicate
updates, A→B→A, temporal cutoffs, revoked/invalid source versions, normalized names,
aliases, trades, ambiguity, injury-exclusion semantics, full/limited/zero/DNP/unknown
participation, independent teams, top-three diminishing contributions, both-team
matchups, no stars, caps, reproducibility, old configs and read-only HTTP previews.
DOM tests verify controls, labels, contributions and safe text rendering.

Real verification reads existing ESPN evidence and the owner-database workbench;
no publisher list, fake permission or backdated snapshot is written there. A
legitimately authorized full ranking snapshot is **not available in this session**,
so end-to-end live ranked scoring is blocked on obtaining one and observing it
before an eligible game. Public page access does not satisfy that requirement.
Exact validation results and sanitized real-data checks accompany the PR and
`docs/evidence/star-power-2026-10-16.json`.

Verified locally: **453 backend tests**, **11 workbench DOM tests**, **38 frontend
tests**, frontend build and Alembic schema check passed. Real November 10 reads
found nine games/eighteen complete team participation families and 363 distinct
ESPN IDs in the stored mapping catalog. Eight existing proposed values were
preserved, all nine Star Power results were unavailable and canonical fact,
capture and score counts were unchanged.
