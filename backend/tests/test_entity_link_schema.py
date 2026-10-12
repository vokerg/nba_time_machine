"""Entity link rows are time-stamped untrusted candidate associations (issue #2)."""
from sqlalchemy import CheckConstraint

from nba_time_machine.db import Base, SourceItemEntityLinkRecord


def test_entity_link_schema_requires_exactly_one_target_and_provenance() -> None:
    table = SourceItemEntityLinkRecord.__table__
    assert table is Base.metadata.tables["source_item_entity_links"]
    assert set(table.columns.keys()) == {
        "id", "source_item_id", "entity_type", "game_id", "team_id", "player_id",
        "link_state", "derivation_method", "observed_at", "available_at",
    }
    checks = {
        constraint.name for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert {
        "ck_source_item_entity_links_one_target",
        "ck_source_item_entity_links_target_matches_type",
        "ck_source_item_entity_links_link_state_valid",
        "ck_source_item_entity_links_derivation_method_valid",
        "ck_source_item_entity_links_availability_not_backdated",
    } <= checks
    assert all(name not in table.columns for name in (
        "body", "text_content", "raw_payload", "spoiler_safe", "authorized",
    ))
    assert sum(index.unique for index in table.indexes) == 3
