"""Research probe: offline and mocked-transport tests, never live network."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from nba_time_machine.ingestion.adapters import CollectionFailure, MAX_BYTES
from nba_time_machine.ingestion.contracts import SourceDefinition
from nba_time_machine.ingestion.feed_probe import inspect_feed, inspect_file, probe_live


def candidate(**changes: object) -> SourceDefinition:
    values: dict[str, object] = {
        "id": "nba-communications-feed",
        "name": "NBA Communications candidate",
        "kind": "web",
        "adapter": "rss",
        "locator": "https://pr.nba.com/feed/",
        "enabled": False,
        "verification_status": "unverified",
        "cadence_minutes": 60,
        "requires_auth": False,
        "retention_policy": "metadata_only",
    }
    values.update(changes)
    return SourceDefinition.model_validate(values)


RSS = """<rss version="2.0"><channel><title>Untrusted title</title>
<item><guid>guid-1</guid><link>https://example.org/a</link>
<title>DO NOT PRINT ARTICLE TITLE</title><description>DO NOT PRINT ARTICLE BODY</description>
<pubDate>Sun, 11 Oct 2026 10:00:00 GMT</pubDate></item>
<item><guid>guid-1</guid><link>https://example.org/b</link></item>
<item><link>https://example.org/c</link></item>
<item><title>No identity</title></item>
</channel></rss>"""


def test_structural_summary_does_not_disclose_items() -> None:
    info = inspect_feed(candidate(), RSS, mime="application/rss+xml")
    assert info["source_id"] == "nba-communications-feed"
    assert info["feed_kind"] == "rss"
    assert info["parse_status"] == "ok"
    assert info["entry_count"] == 4
    assert info["examined_count"] == 4
    assert info["accepted_unique_count"] == 2
    assert info["entries_with_explicit_id"] == 2
    assert info["accepted_with_canonical_url"] == 2
    assert info["accepted_with_published_at"] == 1
    assert info["items_truncated"] is False
    assert info["collection_enabled"] is False
    assert info["source_verified_by_probe"] is False
    rendered = json.dumps(info)
    assert "guid-1" not in rendered
    assert "DO NOT PRINT" not in rendered
    assert "https://example.org" not in rendered


def test_atom_and_truncation() -> None:
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
    <entry><id>x</id><title>Hidden</title><published>2026-10-11T09:00:00Z</published></entry>
    </feed>"""
    info = inspect_feed(candidate(adapter="atom"), atom)
    assert info["feed_kind"] == "feed"
    assert info["accepted_with_canonical_url"] == 0
    assert info["accepted_with_published_at"] == 1

    long_feed = "<rss><channel>" + "<item><guid>%s</guid></item>" * 0
    long_feed = "<rss><channel>" + "".join(
        f"<item><guid>{i}</guid></item>" for i in range(54)
    ) + "</channel></rss>"
    capped = inspect_feed(candidate(), long_feed)
    assert capped["entry_count"] == 54
    assert capped["examined_count"] == 50
    assert capped["accepted_unique_count"] == 50
    assert capped["items_truncated"] is True


@pytest.mark.parametrize("body, code", [
    ("<html/>", "not_rss_or_atom"),
    ("<!DOCTYPE rss><rss/>", "unsafe_xml"),
    ("<rss>", "invalid_xml"),
])
def test_malformed_content_fails_closed(body: str, code: str) -> None:
    with pytest.raises(CollectionFailure) as error:
        inspect_feed(candidate(), body)
    assert error.value.code == code


def test_offline_fixture_enforces_size_and_never_emits_body(tmp_path: Path) -> None:
    file = tmp_path / "sample.xml"
    file.write_text(RSS)
    info = inspect_file(candidate(), file)
    assert info["transport"] == "offline_fixture"
    assert "DO NOT PRINT" not in json.dumps(info)

    file.write_bytes(b"x" * (MAX_BYTES + 1))
    with pytest.raises(CollectionFailure) as error:
        inspect_file(candidate(), file)
    assert error.value.code == "max_bytes"


@pytest.mark.asyncio
async def test_live_probe_requires_prior_policy_review_and_never_follows_redirects() -> None:
    requests = []

    def handler(req: httpx.Request) -> httpx.Response:
        requests.append(req)
        return httpx.Response(200, text=RSS, headers={"Content-Type": "application/rss+xml"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(CollectionFailure) as error:
            await probe_live(candidate(), client=client)
        assert error.value.code == "access_review_required"
        assert requests == []
        info = await probe_live(candidate(), client=client, access_reviewed=True)
    assert len(requests) == 1
    assert info["transport"] == "http_200_no_redirect"
    assert info["declared_mime"] == "application/rss+xml"
    assert info["source_verified_by_probe"] is False

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(302, headers={"Location": "https://other.org/"})
        )
    ) as client:
        with pytest.raises(CollectionFailure) as error:
            await probe_live(candidate(), client=client, access_reviewed=True)
    assert error.value.code == "http_blocked_or_redirect"


@pytest.mark.asyncio
async def test_live_probe_refuses_auth_nonfeed_and_http_even_after_review() -> None:
    for source in (
        candidate(requires_auth=True),
        candidate(adapter="web"),
        candidate(locator="http://example.org/feed/"),
    ):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: pytest.fail("must not request"))
        ) as client:
            with pytest.raises(CollectionFailure) as error:
                await probe_live(source, client=client, access_reviewed=True)
        assert error.value.status == "skipped_config"
