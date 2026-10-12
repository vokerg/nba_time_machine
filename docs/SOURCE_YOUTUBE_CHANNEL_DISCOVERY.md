# YouTube channel identity discovery (Issue #9; 2026-10-12)

This research-only checkpoint resolves two **existing** desired-state seed
placeholders to channel-ID URLs. Channel identity is **not** an approved API
integration, successful metadata read, permission to archive media, or
proof of historical availability. Both sources remain disabled/unverified.

| Stable seed ID | Channel-ID locator | Proposed cadence | Evidence |
| --- | --- | --- | --- |
| `youtube-nba` | [NBA](https://www.youtube.com/channel/UCWJ2lWNubArHWmf3FIHbfcQ) | 15 minutes (inactive) | [NBA Communications](https://pr.nba.com/nba-youtube-one-billion/) identifies the league's official `youtube.com/nba` channel; the [NBA official link list](https://linktr.ee/nba) links NBA YouTube; [Social Blade](https://socialblade.com/youtube/channel/UCWJ2lWNubArHWmf3FIHbfcQ) and [Wikidata](https://www.wikidata.org/wiki/Q155223) associate the channel ID with `@nba`. |
| `youtube-thinking-basketball` | [Thinking Basketball](https://www.youtube.com/channel/UC3HPbvB6f58X_7SMIp6OPYw) | 60 minutes (inactive) | [Published creator video description](https://www.spotsports.com/videos/9feb8050f6) identifies the channel's `/join` path using this ID; the [channel-directory listing](https://www.spotsports.com/channels/thinking-basketball), [NBA.com collection](https://www.nba.com/watch/list/collection/thinking-basketball), and [YouTube handle](https://www.youtube.com/@ThinkingBasketball) identify the Ben Taylor analysis brand. |

The public web reader could open both YouTube channel URLs on 2026-10-12
and identified their page titles but rendered only generic YouTube chrome.
It did **not** expose or independently validate channel owner metadata,
uploads, API response, playlist pagination, per-video IDs, publication
timestamps, region availability, or access entitlements. The ID associations
above are supported by publisher and third-party references; they must still
be verified via an approved project access method.

## Identity, scope, and duplicate handling

- The source ID stays canonical for each publisher channel. `@NBA`,
  `youtube.com/nba`, and NBA's ID-based URL are possible aliases for **one**
  channel, not three sources. Likewise `@ThinkingBasketball` and the
  channel-ID URL are aliases, not new source identities.
- Thinking Basketball has a separate podcast seed
  (`pod-thinking-basketball`). Episodes, YouTube uploads and clips syndicated
  into NBA-owned surfaces should not be silently conflated: deduplicate
  YouTube publications by stable platform video ID *within a channel* and
  separately flag possible cross-channel/cross-platform syndicated content
  for review. Never assume the same upload timestamp across platforms.
- NBA's channel includes league, team and player media; a publisher channel
  is not a team account. Video titles, descriptions, playlist order,
  thumbnails, runtime and metadata can expose final outcomes and game
  significance, so no item may bypass timeline and game disclosure policy.

## Proposed access, timestamps, and retention (not yet tested)

The seed's `adapter="youtube"` is a **planned** interface, not a working
collector. Proposed primary access is an explicitly authorized YouTube Data
API v3 metadata client using an appropriately provisioned API credential
(`requires_auth=true` remains unchanged); investigate API quotas, channel
uploads playlist and pagination, terms, deleted/private/restricted videos,
rate-limit handling and permitted polling cadence before implementation.
Do not scrape HTML as an undocumented fallback or bypass member-only content.

The proposed item identity is `channel_id + video_id`, with `video_id`
identifying the platform upload. Preserve platform `publishedAt` as publisher
metadata, the first *actual system observation* as `discovered_at` and a
defensible `available_at` no earlier than that observation unless supported
by separately reviewed evidence. Snapshot changed titles/descriptions and
visibility only within approved retention limits; a changed publisher date
must not rewrite past observations.

Both seeds retain `enabled=false`, `verification_status=unverified`,
`requires_auth=true`, and `retention_policy=metadata_only`. This is a
conservative proposed storage ceiling, **not rights clearance**. No video,
audio, transcript, caption, full description, thumbnail binary or comments
were captured or approved for capture. A video listing becoming visible
today does not establish its historical visibility at the user's cursor.

## Remaining gates

1. Confirm channel IDs and aliases via authorized owner/API metadata (not
   generic YouTube browser chrome); review platform licensing, Data API
   terms, quota, regional access and allowed display/retention.
2. Obtain approved credential/configuration and implement or select a
   bounded, quota-aware YouTube metadata adapter in the appropriate issue;
   reject credentials in URLs or committed files. Document timeouts,
   pagination caps, retry/rate-limit behavior, access failures, and safe
   errors separately per source.
3. Run a source-specific operator smoke with stable video IDs, distinct
   platform publish/first-observed timestamps, edits/deletions, allowed
   metadata-only PostgreSQL persistence and accurate source-health output.
   Verify no full media/transcripts are fetched, no post-cursor entries
   reach spoiler-safe projections, and rechecks reject revoked access.
4. Only after that evidence, independently decide whether each entry may
   be marked verified and/or enabled. Neither change is made here.

## Static verification

`backend/tests/test_source_seed.py` pins both channel-ID locators and
their conservative policy state. `cd backend && python scripts/sync_sources.py
--validate-only` is a schema check, not live source verification. This
PR resolves identity placeholders only; it does **not** complete issue #9
or the YouTube adapter work under issue #11.
