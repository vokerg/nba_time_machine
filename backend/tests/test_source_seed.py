import json
from pathlib import Path

from nba_time_machine.ingestion.contracts import SourceDefinition


ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "config" / "sources.seed.json"


def test_source_seed_matches_contract() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["status"] == "seed_research_backlog"
    assert len(payload["sources"]) >= 30

    source_ids: set[str] = set()
    for row in payload["sources"]:
        source = SourceDefinition.model_validate(row)
        assert source.id not in source_ids
        source_ids.add(source.id)
        assert source.enabled is False


def test_discovered_official_transactions_and_injury_surfaces_remain_unverified() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {row["id"]: SourceDefinition.model_validate(row)
               for row in payload["sources"]}
    expected = {
        "nba-official-injuries":
            "https://official.nba.com/nba-injury-report-2025-26-season/",
        "nba-official-transactions":
            "https://www.nba.com/players/transactions",
    }
    for source_id, url in expected.items():
        source = sources[source_id]
        assert source.locator == url
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.retention_policy == "metadata_only"
        assert source.adapter == "web"
        assert "official" in source.category


def test_national_media_page_discovery_is_not_collector_approval() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {row["id"]: SourceDefinition.model_validate(row)
               for row in payload["sources"]}
    expected = {
        "cbs-sports-nba": "https://www.cbssports.com/nba/",
        "nbc-sports-nba": "https://www.nbcsports.com/nba/news",
        "bleacher-report-nba": "https://bleacherreport.com/nba",
        "the-ringer-nba": "https://www.theringer.com/topic/nba",
    }

    assert len(set(expected.values())) == len(expected)
    for source_id, url in expected.items():
        source = sources[source_id]
        assert source.locator == url
        assert source.kind == "media"
        assert source.adapter == "rss_or_web"
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.retention_policy == "metadata_only"
        assert "media" in source.category


def test_yahoo_sbnation_discovery_does_not_activate_collectors() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {
        row["id"]: SourceDefinition.model_validate(row)
        for row in payload["sources"]
    }
    expected = {
        "yahoo-sports-nba": "https://sports.yahoo.com/nba/news/",
        "sb-nation-nba": "https://www.sbnation.com/nba",
    }

    assert len(set(expected.values())) == len(expected)
    for source_id, section_url in expected.items():
        source = sources[source_id]
        assert source.locator == section_url
        assert source.kind == "media"
        # rss_or_web still denotes a planned choice, not a working parser.
        assert source.adapter == "rss_or_web"
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.retention_policy == "metadata_only"
        assert source.requires_auth is False


def test_podcast_rss_locators_remain_discovery_only() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {
        row["id"]: SourceDefinition.model_validate(row)
        for row in payload["sources"]
    }
    expected = {
        "pod-no-dunks":
            "https://www.omnycontent.com/d/playlist/e73c998e-6e60-432f-8610-ae210140c5b1/170a762b-6e4b-4cb5-a181-b36a00f64617/64cb7714-6ad9-4029-887f-b36a00f64628/podcast.rss",
        "pod-duncd-on": "https://feeds.simplecast.com/JGGpY1xu",
        "pod-thinking-basketball": "https://anchor.fm/s/86b2b318/podcast/rss",
    }

    assert len(set(expected.values())) == len(expected)
    for source_id, feed_url in expected.items():
        source = sources[source_id]
        assert source.locator == feed_url
        assert source.kind == "podcast"
        assert source.adapter == "podcast_rss"
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.retention_policy == "metadata_only"
        assert source.requires_auth is False


def test_second_podcast_rss_discovery_is_not_live_verification() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {
        row["id"]: SourceDefinition.model_validate(row)
        for row in payload["sources"]
    }
    expected = {
        "pod-locked-on-nba": "https://feeds.simplecast.com/XThpxTzR",
        "pod-hoop-collective": "https://feeds.megaphone.fm/ESP4033296397",
        "pod-bill-simmons": "https://feeds.megaphone.fm/the-bill-simmons-podcast",
    }

    assert len(set(expected.values())) == len(expected)
    for source_id, rss_url in expected.items():
        source = sources[source_id]
        assert source.locator == rss_url
        assert source.kind == "podcast"
        assert source.adapter == "podcast_rss"
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.retention_policy == "metadata_only"
        assert source.requires_auth is False


def test_mismatch_candidate_rss_is_not_verified_or_enabled() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {
        row["id"]: SourceDefinition.model_validate(row)
        for row in payload["sources"]
    }
    source = sources["pod-the-mismatch"]

    # The historical Megaphone feed slug names a different show. Publisher
    # identity, feed channel title and episode GUID stability still need smoke.
    assert source.locator == "https://feeds.megaphone.fm/the-jj-redick-podcast"
    assert source.kind == "podcast"
    assert source.adapter == "podcast_rss"
    assert source.cadence_minutes == 120
    assert source.enabled is False
    assert source.verification_status == "unverified"
    assert source.retention_policy == "metadata_only"
    assert source.requires_auth is False


def test_youtube_channel_discovery_is_not_collector_approval() -> None:
    payload = json.loads(SEED.read_text(encoding="utf-8"))
    sources = {
        row["id"]: SourceDefinition.model_validate(row)
        for row in payload["sources"]
    }
    expected = {
        "youtube-nba":
            "https://www.youtube.com/channel/UCWJ2lWNubArHWmf3FIHbfcQ",
        "youtube-thinking-basketball":
            "https://www.youtube.com/channel/UC3HPbvB6f58X_7SMIp6OPYw",
    }

    assert len(set(expected.values())) == len(expected)
    for source_id, channel_url in expected.items():
        source = sources[source_id]
        assert source.locator == channel_url
        assert source.kind == "youtube"
        assert source.adapter == "youtube"  # Not an implemented video collector.
        assert source.enabled is False
        assert source.verification_status == "unverified"
        assert source.requires_auth is True  # API credential/access review outstanding.
        assert source.retention_policy == "metadata_only"

    assert "official" in sources["youtube-nba"].category
    assert "analysis" in sources["youtube-thinking-basketball"].category
