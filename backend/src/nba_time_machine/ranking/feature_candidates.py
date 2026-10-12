"""Conservative, non-persistent provider feature candidates for ranking.

A candidate is NOT a vetted TemporalFactRecord or a scorer FeatureObservation.
It carries no verified source registry identity, canonical game UUID, historical
availability boundary or trusted finish time; consumers must not score it.
"""
from __future__ import annotations

from dataclasses import dataclass

from nba_time_machine.ranking.scoring import PostgameSignal
from nba_time_machine.sports.contracts import NormalizedGameObservation


@dataclass(frozen=True, slots=True)
class OvertimeCandidate:
    """Provider-level positive overtime evidence, not a normalized quality score."""

    provider: str
    external_event_id: str
    signal: PostgameSignal
    overtime_occurred: bool
    provider_status: str


def thesportsdb_overtime_candidate(
    observation: NormalizedGameObservation,
) -> OvertimeCandidate | None:
    """Extract *positive* NBA overtime evidence from TheSportsDB's AOT status.

    TheSportsDB's documented basketball status AOT denotes a game finished
    after overtime; OT alone denotes an in-progress period. FT/FINAL do not
    independently prove *absence* of overtime and yield no candidate.
    This is intentionally not a TemporalFactRecord writer or score producer.
    """
    if type(observation) is not NormalizedGameObservation:
        return None
    if observation.status != "final" or type(observation.metadata) is not dict:
        return None

    raw_status = observation.metadata.get("provider_status")
    if type(raw_status) is not str or raw_status.strip().upper() != "AOT":
        return None
    if (
        type(observation.home_score) is not int
        or type(observation.away_score) is not int
        or observation.home_score < 0
        or observation.away_score < 0
        or type(observation.external_event_id) is not str
        or not observation.external_event_id.strip()
    ):
        # A final status without a complete event result is not sufficient
        # evidence to promote into any future persisted ranking feature.
        return None

    return OvertimeCandidate(
        provider="thesportsdb",
        external_event_id=observation.external_event_id,
        signal=PostgameSignal.OVERTIME,
        overtime_occurred=True,
        provider_status="AOT",
    )
