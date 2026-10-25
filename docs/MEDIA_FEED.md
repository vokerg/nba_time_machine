# Reviewed News & Buzz feed (#91)

## Contract

`GET /profiles/{profile_id}/media?time_cursor=<UTC ISO timestamp>&limit=10[&page=<opaque key>]`
uses the **saved** profile timeline. Mismatches return HTTP 409, unknown
profiles return 404 and malformed requests/page keys return 422. Limits are
1–25, ordered by reviewed-as-known UTC time descending, then immutable item
UUID descending. Pages carry a cursor-bound key; changing the timeline
invalidates the key, and the browser must start from the first page.
These are keyset pages, not a frozen materialized snapshot; an operator
adding reviews while browsing can change eligibility. Clients must not
treat the presence/count of headlines or page boundaries as a proxy for
unreviewed game outcomes.

Every page is built from the latest captured revision no later than the
persisted cursor and a review of **that specific capture**. A later unreviewed
revision suppresses the item rather than replaying an earlier headline.
The review's timestamp must be no earlier than capture and cannot exceed
the cursor. The required observed/discovered/available/captured timestamps
must all be timezone-aware and within the cursor. Publisher-supplied
`published_at` never backdates the visibility of a record.

Review rows (`media_reviews`) are a deliberate **operator/rights clearance**
boundary; no collector, LLM or automatic classifier writes them.
The operator must independently verify:
- the exact captured headline/excerpt, version and publication provenance;
- the source-specific right to display the title/excerpt/link and applicable
  access restrictions, captured explicitly with `rights_cleared`;
- a complete set of related games and the item's spoiler classification
  (`general` unlinked, `pregame` with verified pre-tip game linkage or
  `outcome_dependent` with verified game linkage);
- whether the canonical HTTPS link is safe and publishable (`link_cleared`).

Absence of review, incomplete/contradictory game association, an unexpected
content type, unverified source status or incomplete temporal evidence
**means omission of the entire item**. Candidate entity links can only
veto a reviewed association; they do not authorize media by themselves.
Each linked game requires a tip observation already known at the cursor;
a future-only schedule never authorizes an earlier pregame headline.
Outcome-dependent items additionally require all linked games unsealed or
explicitly acknowledged, with `project_general_media` enforcing the
global timeline *independently* of game-specific result disclosure.
Headlines and excerpts are policy-projected; thumbnails and runtimes are
not supplied. Only HTTPS link metadata is exposed if explicitly cleared,
and excerpts cannot exceed the source retention limit. No raw capture
payload, unreviewed timestamp, numeric score or sealed game result is
transmitted to the client.

The connected UI shows up to three reviewed items on the dashboard, with
a News & Buzz expansion, pagination and honest empty/error/loading states.
An individual result reveal neither refetches media nor moves the saved
cursor. No runtime fallback to demo/fabricated headlines exists.

## Collection and verification limits (2026-10-15)

- The repository's public RSS registry remains **a research backlog**.
  No source has been enabled by this PR. In particular, the NBA
  Communications candidate in `docs/SOURCE_FEED_ACCESS.md` remains
  `unverified` / `enabled=false`.
- A collector can ingest metadata/captures only when its source registry
  configuration, access and retention policy have been separately approved.
  Captured records alone never create a reviewed item.
- GitHub CI uses a disposable PostgreSQL database and synthetic, clearly
  labelled source rows to test the full API, revision and spoiler boundary.
  **This is not an authorized live-source or Neon production smoke test.**
- The operator must separately complete publisher terms/robots/rate-limit
  review, bounded live RSS parser and collector smoke, stable identity and
  rights verification, then individually clear eligible capture revisions
  before production content will appear. Do not manually backdate review
  timestamps or bypass source config gates.

Frontend: `npm test && npm run build`. Backend: PostgreSQL migrations,
`alembic check`, and `pytest` in CI. Source activation remains a separate
operational decision; report an empty feed as coverage unavailable, never
as proof no news existed.


## Registered media source kinds

The source registry's `kind=media` entries (such as national NBA publisher
feeds) are accepted as **article** media alongside `kind=web`; `kind=podcast`
uses the podcast presentation. The internal read-model does **not** treat the
unregistered `kind=video` alias or `kind=youtube` as an authorized article
source. Video metadata needs a separate validated adapter and typed clearance
before its source kind may be exposed.

Recognizing a source kind never verifies or enables a feed: the latest capture
revision still needs a human review, complete linkages, rights clearance,
actual observation times, verified source status and all existing global
cursor/spoiler gates. The national publisher sources in the seed remain
`enabled=false` and `unverified`. This change does not claim live RSS or
Neon coverage, does not authorize publisher reuse and does not bypass review.


## Local operator review queue (partial #91, October 25, 2026)

The operator now has an explicit, local-only path from **already collected**
captures to the existing review-gated feed. This is **not** a publicly exposed
review API, a classifier, an ingest scheduler or publisher authorization.

After running Alembic migrations and setting `DATABASE_URL`, from `backend/`:

```bash
python scripts/review_media.py pending --source-id SOURCE_ID
python scripts/review_media.py inspect CAPTURE_UUID
# Only after checking exact source license/terms, title/excerpt, age,
# publication provenance, all related NBA games, and the safe destination:
python scripts/review_media.py approve CAPTURE_UUID \
  --hash EXACT_CONTENT_HASH_FROM_INSPECT \
  --sensitivity general \
  --rights-cleared --complete-links-reviewed
# For an actual game-specific item, choose pregame or outcome_dependent and
# repeat --game-id GAME_UUID for the complete set. To publish the HTTPS link,
# additionally give --link-cleared after separately reviewing the link.
```

`pending` returns only source/capture IDs, observed timestamps and hashes;
it intentionally does **not** broadcast unreviewed spoilers in bulk.
`inspect` displays one specifically requested capture's title, limited
excerpt and original timestamps *in the local terminal*; treat it as
spoiler-bearing operator material. Do not paste its output into public logs.
`approve` is a transaction that requires an exact capture hash, independent
rights approval, explicit classification, complete reviewed game association
and proven temporal/source facts. It locks the normalized item and only
permits the latest capture revision; a new unreviewed capture after approval
will suppress the older headline in the feed. Reviews use actual approval
wall-clock time, never a manually chosen/backdated time. Repeated approvals
are rejected; this CLI does not revoke or change earlier review records.

Reviewing a capture does not verify, enable or poll any source. The collector
and existing media API still require their own approval gates, and a
reviewed but sealed or post-cursor article is still hidden. **Nothing here
demonstrates an authorized live source, a populated Neon database or a
production Buzz feed.** Those #91 obligations remain open. Source access,
redistribution and deep-link permissions must be determined on an
individual publisher basis; `--rights-cleared` is the operator's explicit
attestation, not an automated legal conclusion.
