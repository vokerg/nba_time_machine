# Additional podcast RSS locator discovery (Issue #9; 2026-10-12)

This follow-up to [the first podcast feed pass](SOURCE_PODCAST_FEED_DISCOVERY.md)
locates **three more candidate direct RSS URLs**. This is source identity and
MIME-level transport research **only**. None of these shows was verified by
the project's `podcast_rss` parser, `probe_feed.py`, collector, PostgreSQL
persistence, or any licensed/approved production workflow.

| Existing source ID | Publisher/show evidence | Candidate direct-feed URL | Limited browser-reader observation |
| --- | --- | --- | --- |
| `pod-locked-on-nba` | [Locked On NBA show listing](https://podbay.fm/p/locked-on-nba-daily-podcast-on-the-national-basketball-association/about), which links RSS to Simplecast | [Simplecast RSS](https://feeds.simplecast.com/XThpxTzR) | Direct feed read reported `application/xml` but did not expose XML or episodes |
| `pod-hoop-collective` | [Brian Windhorst & The Hoop Collective distribution listing](https://plinkhq.com/i/293376147?to=page), attributed to ESPN/Omaha Productions/Brian Windhorst, links the specific feed | [Megaphone RSS](https://feeds.megaphone.fm/ESP4033296397) | Direct feed read reported `application/xml` but did not expose XML or episodes |
| `pod-bill-simmons` | [The Bill Simmons Podcast distribution listing](https://plinkhq.com/i/1043699613/e/1000789905754) attributes the show to The Ringer and links RSS | [Megaphone RSS](https://feeds.megaphone.fm/the-bill-simmons-podcast) | Direct feed read reported `application/xml` but did not expose XML or episodes |

The public text-reading client was consulted on **2026-10-12**. Its
"unsupported content-type" response shows that its reader could not render
the feed; it is **not** a successful project HTTP/parser smoke test. The
listings and links establish plausible show-to-feed associations, not feed
ownership, continuity, format validity, GUID stability, archival completeness,
permission to fetch automatically, or current publication timestamps.

## Conservative registry update

The three records already existed in `config/sources.seed.json`. Their
canonical IDs, proposed cadences (60 / 120 / 120 minutes) and podcast
classification remain unchanged. Only discovery placeholders become the
URLs above, `verification_status` becomes `unverified` and
`retention_policy` becomes `metadata_only`. All remain
`enabled=false`; `requires_auth=false` is only a tentative public-feed
access assumption, not a promise of unrestricted access.

**No scheduled collection is authorized.** Podcast directory, hosting
platform, show publisher and episode permalink are different identity
layers. Do not create duplicate podcast identities from Apple/Spotify,
Podbay/Plink or Megaphone/Simplecast aliases. The Bill Simmons Podcast is a
**general sports** show, not NBA-only: NBA relevance must be classified per
episode using permitted metadata before appearing in any NBA feed. A title,
show note, thumbnail, runtime, episode order, or linked media item may reveal
games after the selected time cursor; none of these feeds is spoiler-cleared.

`metadata_only` is a conservative proposed maximum once terms and
permissions have been evaluated; it does not imply that retaining even
metadata has already been approved. Audio files, transcripts, enclosure
URLs and linked articles must not be fetched or retained under this
research checkpoint.

## Outstanding gates before verification or activation

1. Review current publisher and host terms, automation/robots policies,
   redirects, feed licensing, acceptable polling rate, and permitted display
   and storage of metadata separately. Subscriber-only or gated feeds must
   not be bypassed.
2. Once access is approved, run each bounded project probe separately:
   `cd backend && python scripts/probe_feed.py --source-id <id> --live --access-reviewed`.
   Record status, content type, bounded response size, actual parsed episode
   count, GUID/permalink, and presence/precision of publication timestamps
   without collecting restricted body text.
3. Verify the same feed across permitted observations for stable episode IDs,
   updates, duplicates, removals and redirects. Publisher `pubDate` cannot
   backdate the earliest *observed* availability for a historical timeline.
4. Verify per-item scope classification (especially the multi-sport Simmons
   feed), policy-enforced metadata-only retention, source isolation, and
   spoiler-safe read separation with the real adapter and PostgreSQL. Do not
   promote `verification_status=verified` or set `enabled=true` before
   reviewed, source-specific evidence exists.

## Offline validation

`backend/tests/test_source_seed.py` pins these three stable IDs, exact
locators, `podcast_rss` adapter, disabled/unverified state and retention
policy. `cd backend && python scripts/sync_sources.py --validate-only`
checks desired-state schema only. Neither check demonstrates live feed
operation or acceptable rights. This is partial #9; the broader podcast
and league-wide source universe still needs verification.
