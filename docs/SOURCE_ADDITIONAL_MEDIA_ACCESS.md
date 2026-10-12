# Yahoo Sports and SB Nation NBA source-locator discovery (Issue #9)

**Inspection date: 2026-10-12.** This checkpoint resolves two existing
national-media **publisher-section identities**. It does not verify a
feed, working collector, collection rights or archival history.

| Stable source ID | Canonical section | Observed public access | Decision |
| --- | --- | --- | --- |
| `yahoo-sports-nba` | https://sports.yahoo.com/nba/news/ | Search/web-reading results displayed Yahoo Sports NBA News articles and links; a separate direct text-reader opening returned an internal error, so item extraction from the configured URL was **not** established | Locator identified; collection unverified |
| `sb-nation-nba` | https://www.sbnation.com/nba | Direct text-reader opening displayed the SB Nation NBA section, NBA-labeled dated article links and author bylines on 2026-10-12 | Locator identified; collection unverified |

Both records keep their stable source IDs, `kind=media`, preexisting
category labels, proposed cadences (15 minutes for Yahoo, 30 minutes for
SB Nation), `requires_auth=false` for the observed public section
surfaces, and placeholder `adapter=rss_or_web`. Both stay
`enabled=false`, `verification_status=unverified` and
`retention_policy=metadata_only`.

## Boundaries and provenance

- Public indexed headlines and a browsable HTML section are **not** evidence
  that the project's RSS or single-page web adapter can enumerate item
  identities, retrieve canonical article URLs, or capture publication and
  correction timestamps. A text-reader failure on Yahoo is not a validated
  project-collector failure; it must be investigated independently.
- `rss_or_web` is a **discovery placeholder**, not a tested access method.
  No feed URL was discovered, no live project collector or persistence smoke
  was performed, and no source health success or active polling is claimed.
- Yahoo's NBA navigation mixes news, podcasts and sports/score surfaces.
  SB Nation links to a distinct network of team-community blogs. Articles
  syndicated or linked across publisher or team sites must retain their
  actual origin, be deduplicated using reviewed canonical item identities,
  and not automatically generate separate licensed observations.
- Neither a publisher's displayed date nor a changing page index can
  establish that a headline, game result, image, ranking or timestamp was
  knowable before the user's time cursor. Historical first observation,
  `published_at`, `available_at` and `captured_at` must remain distinct;
  spoiler policy filters media before any display or model context.
- Viewing these public sections does **not** approve scraping, caching,
  article retention or redistribution. Per-publisher robots, terms,
  paywalls, rate limits, redirects, item-level access and storage rights
  remain unknown and must be reviewed. The metadata-only policy is a
  conservative configuration ceiling, not a legal authorization.

## Exact next verification steps

1. Review Yahoo Sports and SB Nation publisher-specific terms, robots,
   reasonable polling budgets and permitted metadata retention. Do not
   bypass access controls, paywalls or redirects.
2. Find one stable article-list or genuine RSS/Atom endpoint per publisher,
   verify the endpoint's response type and item IDs, and distinguish
   publisher bylines from third-party syndicated or community posts.
3. With access approval, perform a **bounded** smoke through the configured
   project adapter. Record status, content type, item count, deduplication,
   publication/observation time treatment and safe error outcome **without
   printing or storing restricted article text**.
4. Review historical reproducibility and rights. Only after the actual
   access method and item handling are verified should one source be
   considered for `verified`. Activation (`enabled=true`) is a separate
   approval. Do not enable either source in this research PR.

The Athletic's unresolved section/access path and other source families
remain separate work. Issue #9 stays open. For the seed invariant check:
`cd backend && pytest -q tests/test_source_seed.py`. Offline validation
cannot establish live access or publisher permissions.
