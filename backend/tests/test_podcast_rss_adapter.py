"""Offline podcast RSS metadata-contract and policy-gate regressions (issue #11)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from nba_time_machine.ingestion.adapters import CollectionFailure, collect_source
from nba_time_machine.ingestion.contracts import SourceDefinition
from nba_time_machine.ingestion.runtime import _retained


NOW = datetime(2026, 10, 12, 17, 0, tzinfo=timezone.utc)

PODCAST_RSS = """<rss version="2.0"
  xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
  xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel>
  <title>Fixture basketball podcast</title>
  <item>
    <guid isPermaLink="false">episode-7</guid>
    <link>https://podcasts.example.com/episodes/7?utm_source=feed&amp;v=2</link>
    <title>NBA preview</title>
    <itunes:author>Fixture host</itunes:author>
    <description><![CDATA[<p>Upcoming games</p>]]></description>
    <pubDate>Mon, 12 Oct 2026 14:00:00 GMT</pubDate>
    <enclosure url="https://media.example.com/episode-7.mp3"
      type="audio/mpeg" length="1234"/>
    <podcast:transcript url="https://media.example.com/episode-7.vtt"
      type="text/vtt"/>
  </item>
  <item><guid isPermaLink="false">episode-7</guid>
    <title>Duplicate GUID</title></item>
  <item><guid>episode-8</guid><title>Second episode</title></item>
</channel></rss>"""


def podcast_source(**overrides: object) -> SourceDefinition:
    config: dict[str, object] = {
        "id": "basketball-podcast-fixture",
        "name": "Fixture podcast",
        "kind": "podcast",
        "adapter": "podcast_rss",
        "locator": "https://podcasts.example.com/rss",
        "enabled": True,
        "verification_status": "verified",
        "cadence_minutes": 60,
        "requires_auth": False,
        "retention_policy": "metadata_only",
    }
    config.update(overrides)
    return SourceDefinition.model_validate(config)


@pytest.mark.asyncio
async def test_podcast_rss_collects_episode_metadata_not_media() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        assert request.url.host == "podcasts.example.com"
        return httpx.Response(
            200, text=PODCAST_RSS,
            headers={"Content-Type": "application/rss+xml"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await collect_source(podcast_source(), client, NOW)

    # One HTTP request to the approved feed: never follow the enclosure or
    # podcast:transcript URLs embedded in untrusted RSS metadata.
    assert requests == ["https://podcasts.example.com/rss"]
    assert result.status == "ok"
    assert len(result.captures) == 2
    first, second = result.captures
    assert first.external_id == "episode-7"
    assert first.canonical_url == "https://podcasts.example.com/episodes/7?v=2"
    assert first.title == "NBA preview"
    assert first.author == "Fixture host"
    assert first.text == "Upcoming games"
    assert first.published_at == datetime(2026, 10, 12, 14, tzinfo=timezone.utc)
    assert first.discovered_at == NOW
    assert first.captured_at == NOW
    assert second.external_id == "episode-8"
    assert second.canonical_url is None
    assert second.published_at is None
    assert first.content_hash != second.content_hash

    # Retention is enforced at the persistence boundary, not by relying on
    # the adapter to remove XML elements that may contain transcript locators.
    assert _retained("metadata_only", first) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,expected", [
    ({"enabled": False}, "not_verified_or_enabled"),
    ({"verification_status": "unverified"}, "not_verified_or_enabled"),
    ({"requires_auth": True}, "auth_not_configured"),
    ({"kind": "media"}, "invalid_source_kind"),
])
async def test_podcast_policy_failures_make_no_network_requests(
    overrides: dict[str, object], expected: str,
) -> None:
    def deny_network(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"unsafe request to {request.url}")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(deny_network)
    ) as client:
        with pytest.raises(CollectionFailure) as exc:
            await collect_source(podcast_source(**overrides), client, NOW)
    assert exc.value.status == "skipped_config"
    assert exc.value.code == expected


@pytest.mark.asyncio
async def test_podcast_html_response_does_not_fall_back_to_web_scraping() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200, text="<html><body>Sign in</body></html>",
                headers={"Content-Type": "text/html"},
            )
        )
    ) as client:
        with pytest.raises(CollectionFailure) as exc:
            await collect_source(podcast_source(), client, NOW)
    assert exc.value.status == "parse_error"
    assert exc.value.code == "not_rss_or_atom"


@pytest.mark.asyncio
async def test_podcast_feed_redirect_does_not_follow_audio_or_other_hosts() -> None:
    requests: list[str] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302, headers={"Location": "https://media.example.com/private/rss"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        with pytest.raises(CollectionFailure) as exc:
            await collect_source(podcast_source(), client, NOW)
    assert requests == ["https://podcasts.example.com/rss"]
    assert exc.value.status == "blocked"
    assert exc.value.code == "http_blocked_or_redirect"
