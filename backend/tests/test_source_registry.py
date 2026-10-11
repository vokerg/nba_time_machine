"""Validation and seed safety without a live database."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nba_time_machine.ingestion.contracts import SourceDefinition
from nba_time_machine.ingestion.registry import SourceSeed, load_source_seed


ROOT = Path(__file__).resolve().parents[2]


def _source(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": "fixture-source",
        "name": "Test Source",
        "kind": "web",
        "adapter": "web",
        "locator": "https://example.com/feed",
        "enabled": False,
        "verification_status": "unverified",
        "cadence_minutes": 15,
        "requires_auth": False,
        "retention_policy": "metadata_excerpt",
    }
    row.update(overrides)
    return row


def test_real_seed_loads_with_validated_unique_ids() -> None:
    seed = load_source_seed(ROOT / "config" / "sources.seed.json")
    assert seed.schema_version == 1
    assert len(seed.sources) >= 30
    assert len({source.id for source in seed.sources}) == len(seed.sources)
    assert all(source.enabled is False for source in seed.sources)



def test_nba_communications_feed_candidate_remains_disabled_pending_verification() -> None:
    """A reachable RSS MIME alone is not an approved collector."""
    seed = load_source_seed(ROOT / "config" / "sources.seed.json")
    (feed,) = (source for source in seed.sources if source.id == "nba-communications-feed")

    assert feed.locator == "https://pr.nba.com/feed/"
    assert feed.kind == "web"
    assert feed.adapter == "rss"
    assert feed.category == ["official", "league_news", "press_releases"]
    assert feed.requires_auth is False
    assert feed.cadence_minutes == 60
    assert feed.retention_policy == "metadata_only"
    assert feed.verification_status == "unverified"
    assert feed.enabled is False
    assert feed.id != "nba-official-news"
    assert all(source.id != "nba-communications-feed" or not source.enabled
               for source in seed.sources)

def test_official_team_site_seed_covers_every_nba_team() -> None:
    """Team identity research is complete; none is assumed collectible yet."""
    expected_slugs = {
        "ATL": "hawks",
        "BOS": "celtics",
        "BKN": "nets",
        "CHA": "hornets",
        "CHI": "bulls",
        "CLE": "cavaliers",
        "DAL": "mavs",
        "DEN": "nuggets",
        "DET": "pistons",
        "GSW": "warriors",
        "HOU": "rockets",
        "IND": "pacers",
        "LAC": "clippers",
        "LAL": "lakers",
        "MEM": "grizzlies",
        "MIA": "heat",
        "MIL": "bucks",
        "MIN": "timberwolves",
        "NOP": "pelicans",
        "NYK": "knicks",
        "OKC": "thunder",
        "ORL": "magic",
        "PHI": "sixers",
        "PHX": "suns",
        "POR": "blazers",
        "SAC": "kings",
        "SAS": "spurs",
        "TOR": "raptors",
        "UTA": "jazz",
        "WAS": "wizards",
    }
    seed = load_source_seed(ROOT / "config" / "sources.seed.json")
    team_sources = [source for source in seed.sources if "team_site" in source.category]

    assert len(team_sources) == len(expected_slugs) == 30
    assert len({source.id for source in team_sources}) == 30
    assert len({source.locator for source in team_sources}) == 30
    assert {source.category[2] for source in team_sources} == {
        f"team:{code}" for code in expected_slugs
    }
    for code, slug in expected_slugs.items():
        (source,) = (
            source for source in team_sources if source.id == f"nba-team-{code.lower()}-site"
        )
        assert source.locator == f"https://www.nba.com/{slug}/"
        assert source.kind == "web"
        assert source.adapter == "web"
        assert source.category == ["official", "team_site", f"team:{code}"]
        assert source.cadence_minutes == 60
        assert source.requires_auth is False
        assert source.retention_policy == "metadata_only"
        assert source.verification_status == "unverified"
        assert source.enabled is False


def test_seed_rejects_duplicate_source_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate source id"):
        SourceSeed.model_validate(
            {
                "schema_version": 1,
                "status": "seed_research_backlog",
                "sources": [_source(), _source(name="Same ID")],
            }
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"retention_policy": "unlimited"},
        {"requires_auth": "sometimes"},
        {"enabled": "true"},
        {"verification_status": "probably_verified"},
        {"kind": "imaginary"},
        {"adapter": ""},
        {"locator": ""},
        {"cadence_minutes": 0},
        {"id": "not a slug"},
        {"adapter_settings": ["not-a-mapping"]},
        {"secret_token": "unexpected"},
    ],
)
def test_invalid_source_access_or_configuration_is_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        SourceDefinition.model_validate(_source(**overrides))


def test_verification_and_enabled_are_independent_fields() -> None:
    verified_disabled = SourceDefinition.model_validate(
        _source(verification_status="verified", enabled=False)
    )
    enabled_unverified = SourceDefinition.model_validate(
        _source(verification_status="unverified", enabled=True)
    )
    assert verified_disabled.verification_status == "verified"
    assert verified_disabled.enabled is False
    assert enabled_unverified.verification_status == "unverified"
    assert enabled_unverified.enabled is True
