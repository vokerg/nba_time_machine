# The Mismatch podcast feed candidate (Issue #9; 2026-10-12)

This research resolves the existing `pod-the-mismatch` **discovery locator**
to a candidate feed address. It does **not** establish that the feed can be
used for scheduled collection, that its episodes were successfully parsed, or
that publisher terms permit metadata retention.

## Identity and observed access surface

| Layer | Evidence on 2026-10-12 | Interpretation |
| --- | --- | --- |
| Publisher and show | [The Ringer's *The Mismatch* show page](https://www.theringer.com/podcasts/the-mismatch) identifies an active NBA podcast hosted by Chris Vernon and David Jacoby, and lists an October 8, 2026 episode | Canonical show identity is The Ringer / The Mismatch; this is **not** a general Ringer-NBA feed |
| Platform distribution | [Apple Podcasts catalog](https://podcasts.apple.com/us/podcast/the-mismatch/id1317853625) associates the show with The Ringer and the same hosts | An Apple show ID is a distribution identity, **not** an RSS URL |
| Feed locator | [RSS Amplifier's *The Mismatch* directory page](https://rssamplifier.com/the-mismatch) links its **Source feed** to `https://feeds.megaphone.fm/the-jj-redick-podcast` and lists a recent October 8 episode under The Mismatch | This is an independently listed **candidate direct RSS URL**; the directory's episode list is not a successful run of our own parser |
| Historical alias | A [historical public podcast OPML export](https://chrisabraham.com/opml/view) independently labels that same Megaphone URL as “The Mismatch”; an [older directory title](https://ivy.fm/podcast/the-jj-redick-podcast-617001) instead labels its content “The JJ Redick Podcast” while listing recent *Mismatch* episodes | **Identity collision / legacy URL slug:** do not infer a distinct JJ Redick source or use the URL slug as the show's canonical name |

A public web reader attempted to open the direct feed on 2026-10-12 and
reported an unsupported `application/xml` content type, **without exposing
the XML body**. That observation is at most transport/MIME evidence, not
successful XML parsing, valid RSS structure, stable GUIDs, episode count,
redirect semantics, publisher ownership, episode publication times or rights.
The directory's episode excerpts include outcome-dependent NBA commentary and
must never be treated as spoiler-safe content.

## Conservative registry decision

Update only the existing `pod-the-mismatch` entry:

- Locator: `https://feeds.megaphone.fm/the-jj-redick-podcast` (candidate).
- Preserve stable source ID, The Mismatch title, `podcast_rss` adapter, category
  and **120-minute proposed cadence**.
- Set `verification_status=unverified` and
  `retention_policy=metadata_only`; preserve `enabled=false`.
- Leave `requires_auth=false` as an unproven assumption for a public candidate
  URL; it does **not** authorize repeated access or grant metadata rights.

The URL's legacy slug must not become a source ID, a second podcast record, or
evidence of a current JJ Redick show. If the feed changes ownership or channel
identity, reject this candidate rather than aliasing unrelated programs. If
older episode identities migrated from a previous program, deduplication must
be based on verified current show/channel identity and stable episode GUIDs,
not on URL slug or overlapping timestamps alone.

These seed changes do not schedule a collector, download audio, access
transcripts/enclosures, write a capture to PostgreSQL or relax the spoiler
firewall. Even title, publication date, duration, thumbnail and description
can reveal a game result; any eventual episode must pass the **global
time-cursor** gate before AI or frontend projection. Publisher `pubDate` is
distinct from first discovery and trusted `available_at`.

## Required follow-up before source verification

1. Review current The Ringer/Megaphone license, terms, robots/automation
   restrictions, allowed access cadence and whether **metadata-only**
   capture/display is permitted. Do not bypass gated or subscriber feeds.
2. With specific access approval, run the repository's one-request bounded
   diagnostic from `backend/`:
   `python scripts/probe_feed.py --source-id pod-the-mismatch --live --access-reviewed`.
   Record only non-content-bearing status, MIME, parse totals, GUID/URL and
   timestamp counts; no titles, GUID values, payloads or secrets in logs.
3. Independently inspect permitted feed channel metadata for **The Mismatch**
   / The Ringer / Vernon-Jacoby, not merely the legacy slug. Verify that current
   episode identities actually correspond to this podcast, follow redirects
   only if separately reviewed, and check GUID, timestamp and episode
   continuity across permitted observations.
4. Once rights and bounded transport are reviewed, conduct a controlled
   project `podcast_rss` adapter and PostgreSQL smoke for deduplication,
   source isolation, conservative first-observed availability and enforced
   retention. Verify public spoiler projection remains sealed.
5. Only after per-source evidence passes, consider marking it `verified`.
   Deliberate activation (`enabled=true`) is a **separate** decision.

No live approved feed, adapter, PostgreSQL/Neon, or publication-rights smoke
was performed here. Parent issue #9 remains open. Offline seed regression:
`cd backend && pytest -q tests/test_source_seed.py`.
