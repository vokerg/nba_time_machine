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
