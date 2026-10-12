"""Metadata-only AI result audit schema: no model text is retained (issue #2)."""
from sqlalchemy import CheckConstraint

from nba_time_machine.db import AIResultMetadataRecord, Base


def test_ai_result_metadata_schema_excludes_prompt_and_generated_text() -> None:
    table = AIResultMetadataRecord.__table__
    assert table is Base.metadata.tables["ai_result_metadata"]
    assert {
        "id", "use_case", "model_name", "prompt_version", "schema_version",
        "source_item_id", "game_id", "input_as_of", "prompt_tokens",
        "completion_tokens", "total_tokens", "created_at",
    } == set(table.columns)
    assert all(word not in table.columns for word in (
        "prompt", "system_prompt", "response", "raw_output",
        "output", "content", "api_key",
    ))
    checks = {
        constraint.name for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_ai_result_metadata_at_most_one_subject" in checks
    assert "ck_ai_result_metadata_prompt_tokens_nonnegative" in checks
