from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class AIJSONRequest(BaseModel):
    """One provider-neutral request for machine-consumed JSON output."""

    model_config = ConfigDict(extra="forbid")

    use_case: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    system_prompt: str | None = None


class AITokenUsage(BaseModel):
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


OutputT = TypeVar("OutputT", bound=BaseModel)


class AIJSONResult(BaseModel, Generic[OutputT]):
    output: OutputT
    model: str
    prompt_version: str
    schema_version: str
    usage: AITokenUsage | None = None
