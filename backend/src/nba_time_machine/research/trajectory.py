"""Provider-neutral, synthetic-only validation prototype for issue #82.

No source parser is approved: the attempted sources are blocked or rights
unresolved. These types define a future adapter boundary, not trusted sports
facts. Completeness here means structural coverage, never source authenticity,
permission, canonical identity, action continuity or a physical final timestamp.
"""
from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class Action(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    event_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    revision_at: AwareDatetime | None = None
    period: int = Field(ge=1, le=20)
    remaining_ms: int = Field(ge=0, le=720_000)
    home: int = Field(ge=0)
    away: int = Field(ge=0)
    kind: Literal["start", "play", "end"]

    @model_validator(mode="after")
    def clock_range(self):
        if self.period > 4 and self.remaining_ms > 300_000:
            raise ValueError("overtime_clock_out_of_range")
        return self


class Trace(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    provider: str = Field(min_length=1)
    provider_game_id: str = Field(min_length=1)
    home_team_id: str = Field(min_length=1)
    away_team_id: str = Field(min_length=1)
    observed_at: AwareDatetime
    final_state: bool
    declared_periods: int = Field(ge=4, le=20)
    actions: tuple[Action, ...]

    @model_validator(mode="after")
    def identities(self):
        if self.home_team_id == self.away_team_id:
            raise ValueError("same_team_identity")
        return self


class Coverage(BaseModel):
    model_config = ConfigDict(frozen=True)
    structurally_complete: bool
    errors: tuple[str, ...]
    action_count: int
    revisions_collapsed: int
    periods: tuple[int, ...]
    overtime_periods: int | None = None
    lead_changes: int | None = None
    winner_max_deficit: int | None = None
    # Independently supplied totals are required even for internal reconciliation.
    totals_reconciled: bool = False
    trusted_final_at: None = None
    canonical_identity_verified: bool = False
    independently_verified_complete: bool = False


def validate_trace(trace: Trace, *, reference_totals: tuple[int, int] | None) -> Coverage:
    """Fail closed; never sort unexplained out-of-order actions or invent gaps.

    Exact repeats collapse. Conflicting event versions require explicit distinct
    revision timestamps; the newest wins. Corrections must then reconcile with
    the entire remaining sequence, otherwise no quantitative diagnostics emit.
    Reference totals alone do not prove independent provenance or completeness.
    """
    errors: set[str] = set()
    latest: dict[str, Action] = {}
    for action in trace.actions:
        if action.revision_at is not None and action.revision_at > trace.observed_at:
            errors.add("future_revision")
        previous = latest.get(action.event_id)
        if previous is None:
            latest[action.event_id] = action
        elif action != previous:
            if (previous.revision_at is None or action.revision_at is None
                    or previous.revision_at == action.revision_at):
                errors.add("ambiguous_revision")
            elif action.revision_at > previous.revision_at:
                latest[action.event_id] = action
    # Dict preserves source identity order, including a later corrected version.
    actions = tuple(latest.values())
    periods = tuple(sorted({a.period for a in actions}))
    if periods != tuple(range(1, trace.declared_periods + 1)):
        errors.add("missing_or_extra_period")
    if not trace.final_state:
        errors.add("not_final")
    if any(a.order >= b.order for a, b in zip(actions, actions[1:])):
        errors.add("unordered_actions")
    if any(a.period > b.period for a, b in zip(actions, actions[1:])):
        errors.add("unordered_periods")
    for period in periods:
        group = [a for a in actions if a.period == period]
        duration = 720_000 if period <= 4 else 300_000
        if (group[0].kind != "start" or group[0].remaining_ms != duration
                or group[-1].kind != "end" or group[-1].remaining_ms != 0
                or sum(a.kind == "start" for a in group) != 1
                or sum(a.kind == "end" for a in group) != 1):
            errors.add("missing_or_invalid_boundary")
        if any(a.remaining_ms < b.remaining_ms for a, b in zip(group, group[1:])):
            errors.add("clock_reversed")
        if period >= 4 and period < trace.declared_periods:
            if group[-1].home != group[-1].away:
                errors.add("overtime_without_tied_boundary")
    if actions:
        if actions[0].home != 0 or actions[0].away != 0:
            errors.add("nonzero_initial_score")
        for a, b in zip(actions, actions[1:]):
            if b.home < a.home or b.away < a.away:
                errors.add("score_regressed")
            if b.period != a.period and (b.home, b.away) != (a.home, a.away):
                errors.add("score_changed_between_periods")
        last = actions[-1]
        if last.home == last.away:
            errors.add("tied_final")
        reconciled = reference_totals is not None and (last.home, last.away) == reference_totals
    else:
        reconciled = False
    if not reconciled:
        errors.add("missing_or_mismatched_reference_totals")
    complete = not errors
    changes = deficit = None
    if complete:
        signs = [1 if a.home > a.away else -1 for a in actions if a.home != a.away]
        changes = sum(a != b for a, b in zip(signs, signs[1:]))
        home_won = actions[-1].home > actions[-1].away
        deficit = max(0, max((a.away - a.home) if home_won else (a.home - a.away)
                             for a in actions))
    return Coverage(
        structurally_complete=complete, errors=tuple(sorted(errors)),
        action_count=len(actions), revisions_collapsed=len(trace.actions) - len(actions),
        periods=periods, overtime_periods=trace.declared_periods - 4 if complete else None,
        lead_changes=changes, winner_max_deficit=deficit, totals_reconciled=reconciled,
    )
