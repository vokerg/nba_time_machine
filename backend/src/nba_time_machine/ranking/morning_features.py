"""Versioned, reproducible building blocks from a complete normalized trajectory.

This is internal outcome-bearing data, never a public response or AI context.
"""
from dataclasses import dataclass

from nba_time_machine.ranking.scoring import PostgameSignal
from nba_time_machine.sports.morning_models import Evidence, assess

FEATURE_VERSION = "morning-trajectory-v1"


@dataclass(frozen=True)
class TrajectoryFeatures:
    clutch_ms: int
    lead_changes: int
    winner_max_deficit: int
    overtime_periods: int

    def normalized(self) -> dict[PostgameSignal, float]:
        # Provisional explicit scales, not empirically calibrated predictions.
        return {
            PostgameSignal.CLUTCH: min(self.clutch_ms / 300_000, 1),
            PostgameSignal.LEAD_CHANGES: min(self.lead_changes / 20, 1),
            PostgameSignal.COMEBACK: min(self.winner_max_deficit / 25, 1),
            PostgameSignal.OVERTIME: min(self.overtime_periods / 3, 1),
        }


def trajectory_features(evidence: Evidence) -> TrajectoryFeatures | None:
    """Revalidate instead of trusting stored coverage flags or model_copy callers.

    Clutch is regulation's last five minutes plus OT, while within five points.
    A play's score holds until the next play (no interpolation). Ties preserve
    the last nonzero leader; A -> tie -> B counts once, A -> tie -> A does not.
    Comeback is the eventual winner's largest observed deficit, not a lead swing.
    """
    evidence = assess(evidence)
    if not evidence.pbp_usable:
        return None
    changes = clutch = deficit = leader = 0
    winner = 1 if evidence.home.score > evidence.away.score else -1
    for index, play in enumerate(evidence.plays):
        margin = play.home - play.away
        current = (margin > 0) - (margin < 0)
        if current:
            changes += int(bool(leader) and current != leader)
            leader = current
        deficit = max(deficit, -winner * margin)
        if index + 1 < len(evidence.plays):
            following = evidence.plays[index + 1]
            if following.period == play.period and play.period >= 4 and abs(margin) <= 5:
                start = min(play.remaining_ms, 300_000) if play.period == 4 else play.remaining_ms
                clutch += max(0, start - following.remaining_ms)
    return TrajectoryFeatures(clutch, changes, deficit, len(evidence.home.periods) - 4)
