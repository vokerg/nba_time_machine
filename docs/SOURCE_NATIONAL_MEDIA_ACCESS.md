# National NBA media landing-page discovery (Issue #9)

**Inspection date: 2026-10-12.** This checkpoint identifies four
publisher-owned NBA news/coverage sections, **not** working ingestion feeds or
approved extraction sources. All four seed records remain disabled and
unverified. The generic `rss_or_web` adapter value is still a discovery
placeholder; it does not indicate a successfully tested RSS or web adapter.

| Stable source ID | Public section inspected | Text-browser observation | Access status |
| --- | --- | --- | --- |
| `cbs-sports-nba` | https://www.cbssports.com/nba/ | NBA index rendered article headlines and bylines | Identity located; unverified |
| `nbc-sports-nba` | https://www.nbcsports.com/nba/news | NBA News page rendered linked news items and authors | Identity located; unverified |
| `bleacher-report-nba` | https://bleacherreport.com/nba | NBA section rendered headlines, rankings/buzz, and embedded third-party/X references | Identity located; unverified |
| `the-ringer-nba` | https://www.theringer.com/topic/nba | NBA topic page rendered articles together with podcasts and video listings | Identity located; unverified |

## What inspection established

The listed links resolved to relevant NBA editorial section pages in a
public text-reading client on the research date. This establishes a
**canonical source landing-page locator**, not a stable item feed, legal
authorization to collect, or usable as-of historical coverage. A homepage
rendering text in a browser reader does not prove that the project's
single-URL collector extracts distinct articles; no project adapter was run.
The observed pages did not require a login for **section-page inspection**.
Individual stories, archives, embedded posts and APIs may have different
authentication, paywall, robot or rate-limit restrictions.

Each existing source keeps its stable identity, proposed polling cadence and
publisher category. `verification_status=unverified`, `enabled=false` and
`retention_policy=metadata_only` are deliberate: proposed visits are not
running, full articles/excerpts are not approved for retention, and there is
no evidence for item-level canonical IDs, publication/updated times,
availability timestamps or functioning RSS/Atom endpoints.

## Identity, overlap and time model

- CBS Sports and NBC Sports are publisher sections; their editorial pieces
  might cite NBA.com or syndicate reports. Preserve the original publisher
  source ID and separately deduplicate canonical article URLs after access is
  authorized.
- Bleacher Report's NBA section may embed social/X posts and syndicated
  material. A third-party embedded post is **not** automatically a verified
  Bleacher Report observation or a separately licensed X record.
- The Ringer's NBA topic intermixes articles, podcasts and video. The existing
  `the-ringer-nba` entry is a **publisher/topic locator**, not a verified
  podcast RSS adapter or a new identity for each episode. Cross-platform
  deduplication remains open.

A date displayed on a landing page is a **publisher claim**, not evidence
that a mutable headline, ranking, image or article was available at an earlier
timeline cursor. Once collection is approved, preserve independently
recorded first observation and defensible `available_at` and retain edits
as revisions. Pregame and postgame facts must still be filtered by the
spoiler-policy layer before any UI, ranking or AI use.

## Before any record can be marked verified or enabled

1. Review each publisher's robots, terms, access/licensing and rate limits;
   distinguish page viewing from machine extraction and storage permission.
2. Find and inspect a bounded item-level HTML/RSS/API path; select the actual
   supported adapter and document redirects, item identity, article vs
   media boundaries, publication time and corrections. Do not invent feeds.
3. Run a live **project-adapter smoke** with safe size/time limits and record
   date, response status/content type, item count, deduplication and
   timestamp behavior, without retaining restricted content.
4. Approve rights and retention independently. Only then consider a reviewed
   source verification change and a separate explicit activation decision.

This is a partial #9 discovery improvement, **not** a complete national-media
inventory, complete-source verification, rights clearance, a collector launch,
or real historical article ingest.
