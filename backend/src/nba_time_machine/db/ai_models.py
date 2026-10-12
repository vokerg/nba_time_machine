"""Metadata for validated AI results; no prompts or model output are stored here."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class AIResultMetadataRecord(Base):
    """Audit metadata only; a separate, spoiler-checked use case owns any output."""

    __tablename__ = "ai_result_metadata"
    __table_args__ = (
        CheckConstraint("btrim(use_case) <> ''", name="use_case_nonblank"),
        CheckConstraint("btrim(model_name) <> ''", name="model_name_nonblank"),
        CheckConstraint("btrim(prompt_version) <> ''", name="prompt_version_nonblank"),
        CheckConstraint("btrim(schema_version) <> ''", name="schema_version_nonblank"),
        CheckConstraint(
            "num_nonnulls(source_item_id, game_id) <= 1",
            name="at_most_one_subject",
        ),
        CheckConstraint("prompt_tokens >= 0", name="prompt_tokens_nonnegative"),
        CheckConstraint("completion_tokens >= 0", name="completion_tokens_nonnegative"),
        CheckConstraint("total_tokens >= 0", name="total_tokens_nonnegative"),
        Index("ix_ai_result_metadata_use_case_created", "use_case", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    use_case: Mapped[str] = mapped_column(String(96), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(96), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(96), nullable=False)
    source_item_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="RESTRICT"), nullable=True,
    )
    game_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("games.id", ondelete="RESTRICT"), nullable=True,
    )
    input_as_of: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
