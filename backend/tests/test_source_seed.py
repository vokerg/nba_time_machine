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
