# NBA official team-source coverage (Issue #9)

## Identity research — 2026-10-11

On **2026-10-11**, the [NBA's All Teams directory](https://www.nba.com/teams)
listed all 30 NBA teams and linked their official team websites. Each entry
below was followed through that directory and its official destination
inspected via a public web-reading client. These are **verified canonical team
identities and homepage links**, **not verified working collectors**. The seed
represents them as 30 distinct `nba-team-*-site` source IDs.

| Scope | Official team | NBA-directory-linked homepage |
| --- | --- | --- |
| ATL | Atlanta Hawks | https://www.nba.com/hawks/ |
| BOS | Boston Celtics | https://www.nba.com/celtics/ |
| BKN | Brooklyn Nets | https://www.nba.com/nets/ |
| CHA | Charlotte Hornets | https://www.nba.com/hornets/ |
| CHI | Chicago Bulls | https://www.nba.com/bulls/ |
| CLE | Cleveland Cavaliers | https://www.nba.com/cavaliers/ |
| DAL | Dallas Mavericks | https://www.nba.com/mavs/ |
| DEN | Denver Nuggets | https://www.nba.com/nuggets/ |
| DET | Detroit Pistons | https://www.nba.com/pistons/ |
| GSW | Golden State Warriors | https://www.nba.com/warriors/ |
| HOU | Houston Rockets | https://www.nba.com/rockets/ |
| IND | Indiana Pacers | https://www.nba.com/pacers/ |
| LAC | LA Clippers | https://www.nba.com/clippers/ |
| LAL | Los Angeles Lakers | https://www.nba.com/lakers/ |
| MEM | Memphis Grizzlies | https://www.nba.com/grizzlies/ |
| MIA | Miami Heat | https://www.nba.com/heat/ |
| MIL | Milwaukee Bucks | https://www.nba.com/bucks/ |
| MIN | Minnesota Timberwolves | https://www.nba.com/timberwolves/ |
| NOP | New Orleans Pelicans | https://www.nba.com/pelicans/ |
| NYK | New York Knicks | https://www.nba.com/knicks/ |
| OKC | Oklahoma City Thunder | https://www.nba.com/thunder/ |
| ORL | Orlando Magic | https://www.nba.com/magic/ |
| PHI | Philadelphia 76ers | https://www.nba.com/sixers/ |
| PHX | Phoenix Suns | https://www.nba.com/suns/ |
| POR | Portland Trail Blazers | https://www.nba.com/blazers/ |
| SAC | Sacramento Kings | https://www.nba.com/kings/ |
| SAS | San Antonio Spurs | https://www.nba.com/spurs/ |
| TOR | Toronto Raptors | https://www.nba.com/raptors/ |
| UTA | Utah Jazz | https://www.nba.com/jazz/ |
| WAS | Washington Wizards | https://www.nba.com/wizards/ |

Every row has the same **collection-access assessment dated 2026-10-11**:

- **Identity / discovery:** official website linked from NBA.com's current
  30-team directory; no ambiguity with the league-wide `nba-official-news`
  source. `team:XXX` in `category` records scope, not an authorization to
  associate arbitrary scraped articles with that team.
- **Access method / status:** browser-visible public HTTPS homepage; no
  authentication was needed to visit the indexed page in the research client.
  The actual project's `web` collector was **not run** against these URLs.
  Many team sites return mostly JavaScript shells, placeholders or cookie/UI
  markup to a text-only HTTP client; browsing a homepage does **not** prove
  that its latest articles are extractable. Status remains **unverified**;
  `enabled=false` for all 30 entries. In particular, `/sixers/` is the
  official Philadelphia directory link, not an assumed `/76ers/` URL;
  not every team exposes a working `/news` convention.
- **Cadence:** proposed 60-minute revisit only *after* collection is approved;
  currently no HTTP requests are scheduled from these sources.
- **Authorization / rate limits / robots:** publicly viewable homepage does
  not establish crawling permission, a stable RSS endpoint, an API license,
  robots allowances, or a rate-limit budget. These restrictions remain to be
  checked source-by-source before activation. Do not scrape around blocking,
  redirects or paywalls.
- **Retention:** conservative `metadata_only` until publication rights and
  permitted data retention are independently reviewed. No full HTML, article
  text, or postgame headline is approved for durable storage by this research.
- **Provenance:** these links are **source identities**, not timestamped news
  observations. Any eventual captures must independently record observed,
  available and publication timestamps, and must pass the spoiler-policy
  firewall before ever reaching client/AI views.

## Known overlap and coverage gaps

The official `nba-official-news` league source and the team roots above may
link to the **same article**. Canonicalize eventual article URLs and match
source-external IDs before treating one article as distinct news. Team site,
team X account, YouTube channel and a syndicated national-media story are
**separate collection identities**, even when the publisher or headline
matches; cross-platform aliases will require a reviewed identity map.

This slice establishes an official **30/30 team homepage inventory**, but
**0/30 team-specific ingestion pathways are live or collector-verified**.
It does not add authenticated reporters, local beat sources, injury feeds,
RSS/Atom candidates, podcasts, YouTube channels, or newspaper newsletters.
The existing starter records for those families remain separate research
backlog. Team-site homepages alone do not satisfy ongoing news coverage or
historic replay requirements.

## Next reviewable verification slice

1. Discover one **explicit article-list or RSS/Atom URL** for a team, rather
   than assuming the homepage exposes reliably extractable items.
2. Review that endpoint's access permissions, robots/terms, redirect behavior,
   size/rate limits, stable item IDs, timestamps and suitable retention.
3. Perform a **bounded live adapter smoke** using the project's collector and
   record date, HTTP/content type, a non-sensitive item count, deduplication
   behavior and explicit outcome. Do not log unpublished content or secrets.
4. Only after the above, change that specific source's
   `verification_status` to `verified`. Keep it disabled until activation
   is deliberately approved; verify coverage without claiming a live feed.

Seed validation can be run offline with
`cd backend && python scripts/sync_sources.py --validate-only`.
The regression test `test_official_team_site_seed_covers_every_nba_team`
protects the 30 canonical identity mappings, uniqueness, conservative policy
and disabled/unverified state. Full #9 source verification remains open.

## Targeted feed-access follow-up (2026-10-11)

A historical [Celtics RSS announcement](https://www.nba.com/celtics/news/rss-news-feedhtml)
linked `https://www.nba.com/celtics/rss.xml`, but checking that URL now
redirects to the generic NBA homepage rather than exposing an XML feed.
The currently linked [Celtics news page](https://www.nba.com/celtics/news)
returns only an iframe/JavaScript shell to the text-based web reader.
Neither endpoint qualifies as a team-news collector; `nba-team-bos-site`
stays **disabled and unverified**. This is a negative access observation, not
proof that no other official Celtics feed exists.

A separate league-wide RSS candidate was found on NBA Communications. It
must **not** be mistaken for a team-specific source or count toward the
0/30 verified team collectors. See [SOURCE_FEED_ACCESS.md](SOURCE_FEED_ACCESS.md)
for the response observation, robots/terms restrictions and exact next probe.
