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


## Read-only parser-level diagnostic command (Issue #9 follow-up)

An operator can now compare a **locally acquired XML fixture** with the
repository's production RSS/Atom parser, without changing source status or
writing article text to the source registry, database or terminal:

```bash
cd backend
python scripts/probe_feed.py --source-id nba-communications-feed --file /path/to/reviewed-feed.xml
```

For a **single live check only after independently reviewing the publisher's
access terms, robots policy, permitted request rate and metadata handling**:

```bash
cd backend
python scripts/probe_feed.py --source-id nba-communications-feed --live --access-reviewed
```

The operator's `--access-reviewed` flag is an explicit prerequisite, **not**
automated rights/robots compliance checking or a grant of permission. Live
mode performs at most one bounded HTTPS GET: no redirect following, 10-second
timeout, 512 KB response limit, no retries, and no source activation. It is a
manual research probe, not a scheduled collector or a collection-run record.
In both modes the output contains only aggregate structural fields: declared
MIME (live only), RSS/Atom kind, total/examined/accepted item counts, explicit
GUID/ID count, canonical URL count, parsed publication-time count and whether
the first 50-item window was truncated. No URLs, article titles, GUIDs,
text, bodies, authentication values or feed payloads are printed. A successful
parse **does not verify access rights, identifier stability across fetches,
publish-time trust or team collection coverage**.

The live probe has not been executed against `pr.nba.com` in this slice;
the XML body remains unverified. Source `nba-communications-feed` stays
disabled/unverified. Only an approved, documented end-to-end source smoke
(including temporal availability, deduplication and retention checks) can
support later verification. Keep parent #9 open.
