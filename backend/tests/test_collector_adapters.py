"""Offline, deterministic RSS/Atom/web adapter and network boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from nba_time_machine.ingestion.adapters import (
    CollectionFailure,
    canonical_url,
    collect_source,
    parse_feed,
    parse_page,
)
from nba_time_machine.ingestion.contracts import SourceDefinition


NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)


def source(adapter: str = "rss", **overrides: object) -> SourceDefinition:
    data: dict[str, object] = {
        "id": "feed-fixture",
        "name": "Fixture feed",
        "kind": "media",
        "adapter": adapter,
        "locator": "https://example.com/feed.xml",
        "enabled": True,
        "verification_status": "verified",
        "cadence_minutes": 10,
        "requires_auth": False,
        "retention_policy": "metadata_excerpt",
    }
    data.update(overrides)
    return SourceDefinition.model_validate(data)


RSS = """<rss version="2.0"><channel><title>NBA</title>
<item><guid>nba-story-7</guid><link>https://example.com/nba/7?utm_source=x&amp;id=2#frag</link>
<title>Game preview</title><description><![CDATA[<p>Safe <b>preview</b> details</p>]]></description>
<pubDate>Thu, 08 Oct 2026 08:30:00 GMT</pubDate></item>
<item><guid>nba-story-7</guid><title>duplicate</title></item>
<item><link>https://example.com/nba/8</link><title>Another</title></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>tag:example.com,2026:42</id><title>NBA Update</title>
<link rel="alternate" href="https://example.com/story/42" />
<published>2026-10-08T08:00:00Z</published>
<author><name>Reporter</name></author><summary>Pregame update</summary></entry>
</feed>"""


def test_rss_extracts_identity_and_keeps_publication_separate() -> None:
    result = parse_feed(source(), RSS, NOW)
    assert result.status == "ok"
    assert len(result.captures) == 2
    capture = result.captures[0]
    assert capture.external_id == "nba-story-7"
    assert capture.canonical_url == "https://example.com/nba/7?id=2"
    assert capture.title == "Game preview"
    assert capture.text == "Safe preview details"
    assert capture.published_at == datetime(2026, 10, 8, 8, 30, tzinfo=timezone.utc)
    assert capture.discovered_at == NOW
    assert capture.captured_at == NOW
    assert capture.content_hash


def test_atom_extracts_author_and_permalink() -> None:
    capture = parse_feed(source("atom"), ATOM, NOW).captures[0]
    assert capture.external_id == "tag:example.com,2026:42"
    assert capture.author == "Reporter"
    assert capture.canonical_url == "https://example.com/story/42"
    assert capture.published_at.hour == 8


@pytest.mark.parametrize("xml,code", [
    ("not xml", "invalid_xml"),
    ("<!DOCTYPE foo><rss/>", "unsafe_xml"),
    ("<html/>", "not_rss_or_atom"),
])
def test_invalid_feed_fails_closed(xml: str, code: str) -> None:
    with pytest.raises(CollectionFailure) as error:
        parse_feed(source(), xml, NOW)
    assert error.value.status == "parse_error"
    assert error.value.code == code


def test_empty_feed_is_idle() -> None:
    assert parse_feed(source(), "<rss><channel/></rss>", NOW).status == "idle"


def test_html_is_single_page_and_strips_active_elements() -> None:
    result = parse_page(
        source("web", locator="https://example.com/nba/article"),
        '<html><head><title>Preview</title><meta name="author" content="A"></head>'
        '<body><p>Body text</p><script>secret_score=99</script></body></html>',
        NOW,
    )
    capture = result.captures[0]
    assert capture.title == "Preview"
    assert capture.author == "A"
    assert "Body text" in (capture.text or "")
    assert "secret_score" not in (capture.text or "")
    assert capture.canonical_url == "https://example.com/nba/article"


@pytest.mark.parametrize("url", [
    "http://localhost/admin", "http://127.0.0.1/", "http://10.0.0.2/",
    "file:///etc/passwd", "https://user:secret@example.com/page", "https://a.local/",
])
def test_refuses_nonpublic_urls(url: str) -> None:
    assert canonical_url(url) is None


@pytest.mark.asyncio
async def test_transport_collects_rss_and_rejects_redirects() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/feed.xml"
        return httpx.Response(200, text=RSS, headers={"Content-Type": "application/rss+xml"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await collect_source(source("rss_or_web"), client, NOW)
    assert len(result.captures) == 2

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(302, headers={"Location": "https://other.com/"}))
    ) as client:
        with pytest.raises(CollectionFailure) as failure:
            await collect_source(source(), client, NOW)
    assert failure.value.status == "blocked"


@pytest.mark.asyncio
async def test_bad_http_responses_have_distinct_statuses() -> None:
    for code, expected in [
        (401, "auth_error"), (403, "blocked"), (429, "rate_limited"),
        (500, "network_error"),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda req: httpx.Response(code))
        ) as client:
            with pytest.raises(CollectionFailure) as failure:
                await collect_source(source(), client, NOW)
        assert failure.value.status == expected


@pytest.mark.asyncio
async def test_caps_response_size_and_skips_missing_auth() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"a" * 512_100))
    ) as client:
        with pytest.raises(CollectionFailure) as large:
            await collect_source(source(), client, NOW)
        with pytest.raises(CollectionFailure) as auth:
            await collect_source(source(requires_auth=True), client, NOW)
    assert large.value.code == "max_bytes"
    assert auth.value.status == "skipped_config"
