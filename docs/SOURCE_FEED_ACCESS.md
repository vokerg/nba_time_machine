# NBA feed-access research (Issue #9)

## Scope and evidence (2026-10-11)

This is an **access-method investigation**, not collector activation or a
successful ingest. A browser/web-reading client inspected the public source
URLs below on 2026-10-11. No project collector, PostgreSQL ingestion,
automated polling, or raw-item archival was performed.

| Surface | Observed result | Operational conclusion |
| --- | --- | --- |
| [Celtics historic RSS announcement](https://www.nba.com/celtics/news/rss-news-feedhtml) | 2006 team article advertises `https://www.nba.com/celtics/rss.xml` | This is **historical documentation**, not a modern feed guarantee |
| [Celtics legacy RSS URL](https://www.nba.com/celtics/rss.xml) | Public web reader followed a redirect to generic `https://www.nba.com/`, returned HTML | **Not an RSS feed** for the project's no-redirect collector; no activation |
| [Celtics news page](https://www.nba.com/celtics/news) | Public HTML reader shows an iframe/JavaScript shell, not enumerable article entries | Do not assume single-page web capture can collect article history |
| [NBA Communications feed](https://pr.nba.com/feed/) | Direct read reached a response reported as `application/rss+xml`; web reader refused to render XML (unsupported content type) | **RSS transport candidate only**, not proven parseable or legally approved |
| [NBA Communications robots.txt](https://pr.nba.com/robots.txt) | User-agent `*`: disallows selected paths and `/*?*`, declares `Crawl-Delay: 1`; no explicit `/feed/` disallow seen | Not a license, permission grant or all-clear for automation; avoid query-string workarounds |
| [NBA Terms of Use](https://www.nba.com/termsofuse) | Restricts reuse of NBA content and describes rules for RSS/modular content | Retention, republishing and intended use need independent approval |

## Registry decision

Added one **separate league-level** registry candidate:
`nba-communications-feed` -> `https://pr.nba.com/feed/`.

- `kind=web`, `adapter=rss`, categories
  `official / league_news / press_releases` (not a Celtics/team source).
- `requires_auth=false` for the inspected public URL only; this does not
  establish an unrestricted API or future access guarantee.
- Proposed cadence: **60 minutes**, subject to explicit rate/robots review.
- `retention_policy=metadata_only` is a conservative *maximum if approved*,
  not an assertion that this much retention or presentation is authorized.
- `verification_status=unverified` and `enabled=false`. No scheduled
  network requests, persisted captures, source health successes or new UI
  disclosures are created by this change.
- `nba-official-news` remains a different league news surface. Cross-source
  article identities would need URL/external-ID deduplication.

Do **not** change any source to verified merely because an HTTP response
advertises XML; the RSS body and timestamp semantics were not inspected.
Do not derive spoiler-safe time from the publisher's `pubDate` alone:
discovered/available/captured times remain separate.

## Missing verification and exact next action

1. Independently confirm that `https://pr.nba.com/feed/` returns valid,
   bounded RSS/Atom with actual article entries, stable GUID/canonical URLs,
   parseable publisher timestamps and a defensible observed-at timestamp.
   Inspect HTTP status, redirects, declared MIME, response bytes, item count
   and parse outcome without storing article bodies in the source registry
   or logs.
2. Review NBA terms and applicable RSS usage rights, the source's
   `robots.txt`, permissible access rate and whether metadata-only
   retention/public links are allowed. If not approved, leave disabled
   and record the reason.
3. With explicit access approval, run **one** bounded smoke using the
   repository's adapter/collector and a migrated test PostgreSQL, checking
   first-discovery availability, deduplication, errors and stored retention.
   Do not use `--force` to bypass eligibility checks.
4. Only with passing smoke and rights review, mark this particular source
   verified; enabling it is a separate deliberate action. Record the result.
5. Separately discover a **team-specific** officially supported article-list
   or RSS endpoint. The Celtics' old URL is not one; team coverage remains
   **0/30 collector verified**.

## Offline checks

`cd backend && python scripts/sync_sources.py --validate-only`
and `pytest tests/test_source_registry.py` should confirm the candidate's
registry identity, low-retention status and disabled/unverified gating.
These offline checks cannot prove external feed or rights compliance.
