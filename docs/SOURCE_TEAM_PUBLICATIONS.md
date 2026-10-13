# Independent NBA team-publication identity discovery (Issue #9)

**Research date: 2026-10-13.** This is a source-identity and homepage
discovery slice, **not** collector verification, ingestion authorization,
publication-rights clearance, or a historical data backfill.

## Five team-specific editorial sources

The public web reader opened or indexed each publisher's own homepage with
recent, team-specific bylined articles. These are editorial/community
publications, **not** official NBA team sources and **not** individually
authenticated reporter social accounts.

| Source ID | Team scope | Publisher / homepage | Evidence on research date |
| --- | --- | --- | --- |
| `celticsblog-bos` | BOS | [CelticsBlog](https://www.celticsblog.com/) | Boston Celtics community, bylined news, analysis and dated articles |
| `golden-state-of-mind-gsw` | GSW | [Golden State of Mind](https://www.goldenstateofmind.com/) | Golden State Warriors community with dated analysis and game coverage |
| `mavs-moneyball-dal` | DAL | [Mavs Moneyball](https://www.mavsmoneyball.com/) | Dallas Mavericks community with dated news, previews and coverage |
| `posting-and-toasting-nyk` | NYK | [Posting and Toasting](https://www.postingandtoasting.com/) | New York Knicks community with dated analysis, news and articles |
| `raptors-republic-tor` | TOR | [Raptors Republic](https://raptorsrepublic.com/) | Toronto Raptors-specific editorial articles, bylines and podcasts |

These publisher homepages were publicly readable in the research client. For
the four SB Nation community publications, an individual article may also be
linked by the league-wide `sb-nation-nba` discovery source. Raptors Republic
operates a separate team-focused editorial homepage and includes podcast
content; its podcasts are **not** implicitly approved or represented as RSS
episodes by this web identity.

## Registry decisions

All five new source IDs are stable publisher identities, distinct from the
existing `nba-team-*-site` official NBA team homepages and the broad
`sb-nation-nba` national hub.

- `kind=media`, `adapter=rss_or_web` (discovery placeholder; **no actual
  feed URL or parsed article-list adapter has been approved**).
- Categories are `media`, `team_publication` and one `team:XXX` scope.
  These tags do not prove a specific article concerns a particular game and
  do not authorize game-linked disclosure.
- `requires_auth=false` reflects only viewing the publisher homepage with
  the research client. No API keys or paywall access were tested.
- Proposed `cadence_minutes=60`; **no periodic fetching occurs**.
- `verification_status=unverified`, `enabled=false`, and
  `retention_policy=metadata_only` for every new source. These are
  conservative configuration limits, **not legal approval** to retain or
  republish even metadata.

The five homepages increase **team-focused editorial identities** from
zero to five distinct team scopes in this group. They do not change the
separate **0/30 officially collector-verified team-news endpoints**
reported in [SOURCE_TEAM_COVERAGE.md](SOURCE_TEAM_COVERAGE.md).

## Access, identity and time-machine risks

- **Extraction and HTTP access:** A web reader being able to display a page
  is not evidence that the project's bounded `rss_or_web` source will
  retrieve a feed, enumerate article identifiers, parse timestamps or avoid
  pagination duplicates. No project parser or PostgreSQL smoke was run.
- **Permissions / rate limits:** Publisher robots directives, terms,
  article-specific access controls, acceptable crawl rate, and metadata
  storage/redistribution rights need independent review. The 60-minute
  cadence is not a permission claim. No collection or workaround is enabled.
- **Deduplication:** Do not count one community article again when syndicated,
  quoted, embedded or linked from `sb-nation-nba` or official league/team
  pages. Discover stable article canonical URLs or IDs per publisher, and
  distinguish authored posts from community/user posts and outbound links.
  Different platform identities remain separate records until an explicit
  cross-source link establishes equivalence.
- **Historical integrity:** A publisher's displayed article date is not
  necessarily when the system learned the content. Keep `published_at`,
  first `discovered_at`, `captured_at` and defensible `available_at`
  separate; corrections and re-edits must create revisions. Game results,
  thumbnails and headlines remain potentially spoiler-bearing and must not
  bypass deterministic disclosure policy or enter an AI prompt unchecked.
- **Coverage:** Five team scopes do not imply five live sources or substitute
  for locally employed beat reporters. Editorial provenance and newsroom
  coverage can change, so identities must be revisited.

## Exact next verification step

For **one** publisher at a time: inspect current robots/terms and rights for
metadata capture; identify a single bounded article-list endpoint or real
RSS/Atom feed; confirm status, redirects, content type, item count, stable
canonical IDs and timestamps; and run a reviewed one-source project adapter
plus PostgreSQL persistence smoke. Record the date and error/health result
without logging article bodies or spoiler-bearing content. Only after these
checks may a **specific** source be marked verified; enabling it still
requires deliberate activation. Parent Issue #9 remains open.

Offline validation:

```bash
cd backend
python scripts/sync_sources.py --validate-only
pytest -q tests/test_source_seed.py
```

Offline tests protect the conservative registry mapping; they **cannot**
establish publication rights, extraction feasibility or live-source health.
