# Subscription-gated NBA source identities (Issue #9)

**Discovery date:** 2026-10-12. These records are **publisher/site identity discoveries**, not successful collectors, available licenses, or confirmations of historical item coverage.

| Stable seed ID | Discovered official source locator | Access assessment | Seed decision |
| --- | --- | --- | --- |
| `the-athletic-nba` | https://www.nytimes.com/athletic/nba/ | The Athletic NBA editorial section; The New York Times explicitly says The Athletic is accessed through `nytimes.com/athletic` and journalism requires a qualifying login/subscription. The target NBA section was identified through indexed page metadata, but direct public text-reader opening of the NBA URL returned an internal error. | `rss_or_web` discovery placeholder; **disabled, unverified, auth-gated, metadata-only** |
| `cleaning-the-glass` | https://cleaningtheglass.com/ | Official public landing page for NBA analytics. Its main navigation includes Stats and Login; the company documents subscription-supported advanced stats. Public marketing pages do **not** establish access to a stats endpoint, a redistribution license, or an API. | `provider_specific` placeholder; **disabled, unverified, auth-gated, metadata-only** |

## Evidence and source identity

- **The Athletic:** [New York Times subscription and access help](https://thenewyorktimeshelpcenter.helpjuice.com/4418858416276-The-Athletic-Subscription) states that subscribers access The Athletic at `nytimes.com/athletic`, including premium NBA journalism. NBA-specific section path `/athletic/nba/` appeared in external search/index listings with NBA headlines and NBA navigation on 2026-10-12, but **the direct site could not be independently read by this inspection client**. This is section URL discovery, not an authenticated page/read or feed verification.
- **Cleaning the Glass:** The site's [official homepage](https://cleaningtheglass.com/) describes its NBA statistical product and links to Stats and Login. Its [about page](https://cleaningtheglass.com/about/) attributes the site to Ben Falk and includes a link labeled “RSS for articles.” That **articles feed is not the advanced statistics product** and should not silently replace this `stats_site` seed identity. The [terms of service](https://cleaningtheglass.com/terms-of-service/) document account/payment and intellectual-property boundaries; they provide no blanket permission for automated data collection or re-publication.

## Conservative registry configuration

For both entries, the stable source ID, kind, category, adapter placeholder and planned polling cadence (The Athletic **15 minutes**, Cleaning the Glass **60 minutes**) are unchanged. Their `locator` fields now contain official addressable HTTPS identity URLs; `verification_status` moves from `discovery_required` to **`unverified`** because the source identity is located, **not** because a collector has worked.

Both stay `enabled=false`, `requires_auth=true`, `retention_policy=metadata_only`. The `requires_auth` flag reflects anticipated access to the **actual paid journalism/stats**, not a claim that visiting the public index page itself required login. `metadata_only` is a strict technical ceiling if and when collection is authorized; it does not grant rights to gather or store metadata.

The Athletic's `rss_or_web` and Cleaning the Glass's `provider_specific` are planned access methods. Neither is a verified ingestion pathway in the current runtime. A third-party directory advertises a potential The Athletic NBA RSS URL, but direct publisher XML identity, item IDs, access and rights were **not** confirmed here, so the seed deliberately records the publisher section instead of treating an RSS claim as operational.

## Known blockers and exact next actions

1. **Permissions:** Confirm publisher-specific terms, robots, authentication/API access, permitted metadata extraction/retention, rate limits, and historical replay rights. No paywall bypass, session-cookie replay, or HTML scraping of subscriber content without authorization.
2. **Access pathway:** For The Athletic, validate an approved NBA-specific RSS or publication metadata endpoint; for Cleaning the Glass, seek a supported licensed statistics feed/API or other explicitly permitted method. Keep article RSS separate from the paid stats product.
3. **Bounded smoke:** Only after operator authorization, test the chosen approved adapter with strict request limits. Record HTTP/content type, redirects, item IDs/canonical URLs, duplicate behavior, actual source health outcome, and separate `published_at` / first-observed `available_at` / `captured_at` values. Never infer historical knowability from indexed or publisher dates alone.
4. **Activation decision:** Review rights and persisted field inventory, then propose explicit source-specific changes under a separate issue/PR. Do not mark either `verified` without a successful collector smoke; do not enable either by default. Spoiler policy must clear even permitted metadata before it reaches a user or AI context.

Offline contract checks: `cd backend && pytest -q tests/test_source_seed.py` and `python scripts/sync_sources.py --validate-only`. These checks validate configuration only; there was no authenticated source access, feed XML parse, live collector, database sync, or Neon smoke in this discovery change. Parent issue #9 remains open.
