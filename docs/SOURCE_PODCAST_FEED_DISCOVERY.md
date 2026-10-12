# Podcast RSS locator discovery (Issue #9; 2026-10-12)

This is **locator and transport-content-type discovery**, not a verified
podcast collector, approved rights determination or completed ingestion smoke.
A public web-reading client opened three candidate RSS URLs on 2026-10-12.
The client reported unsupported XML/RSS MIME and **did not expose the XML
body or episode elements**. The project's `podcast_rss` adapter, `probe_feed.py`,
PostgreSQL collection runtime and external publisher terms were **not**
executed or approved in this investigation.

| Registry source | Candidate locator and identity evidence | Reader observation |
| --- | --- | --- |
| `pod-no-dunks` | [Omny Content RSS](https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/170a762b-6e4b-4cb5-a181-b36a00f64617/64cb7714-6ad9-4029-887f-b36a00f64628/podcast.rss); [No Dunks distribution listing](https://ms.podbean.com/podcast-detail/pvs54-9572b/No-Dunks-Podcast), [iHeart show page](https://www.iheart.com/podcast/1119-no-dunks-154862494/) | URL read reached a response reported as `application/xml`; XML not rendered |
| `pod-duncd-on` | [Simplecast RSS](https://feeds.simplecast.com/JGGpY1xu); [Dunc'd On podcast listing](https://plinkhq.com/i/986901174/e/1000721959022), [producer website](https://nateduncannba.com/) | URL read reached a response reported as `application/xml`; XML not rendered |
| `pod-thinking-basketball` | [Spotify/Anchor RSS](https://anchor.fm/s/86b2b318/podcast/rss); [Thinking Basketball RSS listing](https://podstatus.com/podcasts/thinking-basketball-13186), [Apple podcast listing](https://podcasts.apple.com/dk/podcast/thinking-basketball/id1428290303) | URL read reached a response reported as `application/rss+xml`; XML not rendered |

All three independent podcast show identities already existed in the source
seed. The URLs above are **candidate direct-feed locators**, not generic web
landing pages. Podcast platform hosting and the publisher/creator are distinct
identity layers; do not create duplicate source IDs for the same show merely
because it appears in Apple Podcasts, Spotify, iHeart, Podbean or another
directory. The feed URLs were linked by distribution listings; ownership,
canonical GUID behavior and continuity must be verified before ingesting.

## Conservative seed decisions

For these three rows only, retain their stable source IDs, category, kind
`podcast`, adapter `podcast_rss`, `requires_auth=false` as an
**observed request assumption**, and existing proposed cadences (60, 120
and 120 minutes respectively). Replace discovery placeholders with the
candidate feed URLs; use `verification_status=unverified`,
`enabled=false` and `retention_policy=metadata_only`.

These settings authorize **zero scheduled fetches**. The absence of an auth
challenge in this web-reading check does not establish anonymous API usage
rights, a durable public feed, permissible archival, automated polling or
future response stability. Metadata-only is a conservative intended maximum
*if permission is subsequently obtained*, not a claim that retention is
already allowed. Audio/transcripts, episode bodies and even headlines can
contain postgame spoilers; nothing in this PR clears any item for timeline
projection or AI context.

## Required verification before changing source state

1. Review each publisher's current terms, RSS permissions, robots/automation
   rules, redirects and acceptable rate. Verify that displaying URLs/metadata
   to the intended audience is permitted. Record exact approval evidence;
   do not bypass subscriber-only feeds or use another host to evade blocks.
2. With access approval, run one bounded direct-feed probe using
   `cd backend && python scripts/probe_feed.py --source-id <id> --live --access-reviewed`
   for each candidate separately. Capture only aggregate item counts and
   structural diagnostics; check response HTTP status, content type, size,
   redirects, GUID/episode permalinks, and publication-time coverage.
3. Independently compare two permissible observations across time to confirm
   GUID stability, edits/duplicates and conservative
   `published_at` / `discovered_at` / `available_at` semantics. A
   publisher `pubDate` is not trustworthy historical first-availability
   evidence by itself.
4. Only after review, perform an approved, bounded **project-adapter plus
   PostgreSQL** smoke to verify immutable revisions, source isolation,
   metadata-only persistence and spoiler-safe read separation.
5. Promote a source to `verified` only with source-specific evidence and
   keep actual activation a separate explicit decision. Other podcast rows
   still have discovery placeholders and are not implied to be verified.

## Validation scope

Offline seed parsing and `backend/tests/test_source_seed.py` pin the three
locators, adapter type, disabled/unverified state and metadata-only policy.
Run `cd backend && python scripts/sync_sources.py --validate-only`.
This validates desired-state shape, **not** a live HTTP/XML feed or right to
collect. This slice is partial #9 and does not complete the source universe.
