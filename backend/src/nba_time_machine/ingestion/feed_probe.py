"""Research-only feed diagnostics with no persistence or source activation.

The network path requires a deliberate operator acknowledgement that access,
robots and rights have already been reviewed. It must not be run automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from nba_time_machine.ingestion.adapters import (
    MAX_BYTES,
    MAX_ITEMS,
    CollectionFailure,
    _request,
    parse_feed,
)
from nba_time_machine.ingestion.contracts import SourceDefinition

FEED_ADAPTERS = frozenset({"rss", "atom"})


def inspect_feed(
    source: SourceDefinition, body: str, *, mime: str | None = None
) -> dict[str, str | int | bool | None]:
    """Describe *structure only*. Never return article IDs, titles or content."""
    if source.adapter not in FEED_ADAPTERS:
        raise CollectionFailure("skipped_config", "not_a_feed_source")
    if len(body.encode("utf-8")) > MAX_BYTES:
        raise CollectionFailure("blocked", "max_bytes")

    # Reuse the exact production parser, including its unsafe XML checks.
    parsed = parse_feed(source, body, datetime.now(timezone.utc))
    root = ET.fromstring(body)
    root_name = root.tag.rsplit("}", 1)[-1].lower()
    parent = (
        next((n for n in root if n.tag.rsplit("}", 1)[-1] == "channel"), None)
        if root_name == "rss"
        else root
    )
    entry_name = "item" if root_name == "rss" else "entry"
    entries = [] if parent is None else [
        n for n in parent if n.tag.rsplit("}", 1)[-1] == entry_name
    ]
    examined = entries[:MAX_ITEMS]
    explicit_ids = sum(
        any(
            n.tag.rsplit("}", 1)[-1] in {"guid", "id"}
            and "".join(n.itertext()).strip()
            for n in entry
        )
        for entry in examined
    )
    captures = parsed.captures
    return {
        "source_id": source.id,
        "feed_kind": root_name,
        "declared_mime": mime,
        "parse_status": parsed.status,
        "entry_count": len(entries),
        "examined_count": len(examined),
        "accepted_unique_count": len(captures),
        "entries_with_explicit_id": explicit_ids,
        "accepted_with_canonical_url": sum(c.canonical_url is not None for c in captures),
        "accepted_with_published_at": sum(c.published_at is not None for c in captures),
        "items_truncated": len(entries) > MAX_ITEMS,
        "collection_enabled": False,
        "source_verified_by_probe": False,
    }


async def probe_live(
    source: SourceDefinition,
    *,
    access_reviewed: bool = False,
    client: httpx.AsyncClient | None = None,
) -> dict[str, str | int | bool | None]:
    """One bounded, no-redirect feed read after explicit human policy review.

    This bypasses the collector's enabled/verified gating *only for diagnostics*.
    It never writes to the registry, database, logs or files.
    """
    if not access_reviewed:
        raise CollectionFailure("skipped_config", "access_review_required")
    if source.adapter not in FEED_ADAPTERS or source.requires_auth:
        raise CollectionFailure("skipped_config", "unsupported_probe_source")
    if not source.locator.startswith("https://"):
        raise CollectionFailure("skipped_config", "https_required")

    if client is None:
        async with httpx.AsyncClient() as owned:
            body, mime = await _request(owned, source.locator, tries=1)
    else:
        body, mime = await _request(client, source.locator, tries=1)
    result = inspect_feed(source, body, mime=mime)
    return {**result, "transport": "http_200_no_redirect"}


def inspect_file(source: SourceDefinition, path: Path) -> dict[str, str | int | bool | None]:
    """Analyze a local XML fixture without emitting or retaining the payload."""
    with path.open("rb") as handle:
        payload = handle.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise CollectionFailure("blocked", "max_bytes")
    result = inspect_feed(source, payload.decode("utf-8-sig", errors="replace"))
    return {**result, "transport": "offline_fixture"}
