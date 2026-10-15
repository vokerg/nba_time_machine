"""Readable supporting events from retained normalized evidence (no provider fetch)."""
from nba_time_machine.ranking.morning_features import TrajectoryFeatures
from nba_time_machine.sports.morning_models import Evidence


def supporting_plays(evidence: Evidence, metrics: TrajectoryFeatures) -> list[dict]:
    result = []
    leader = 0
    deficit_found = False
    winner = 1 if evidence.home.score > evidence.away.score else -1
    for i, play in enumerate(evidence.plays):
        margin = play.home - play.away
        current = (margin > 0) - (margin < 0)
        tags, clutch_ms = [], 0
        if current:
            if leader and current != leader:
                tags.append("lead_changes")
            leader = current
        if not deficit_found and metrics.winner_max_deficit > 0 and -winner * margin == metrics.winner_max_deficit:
            tags.append("comeback")
            deficit_found = True
        if i + 1 < len(evidence.plays):
            following = evidence.plays[i + 1]
            if following.period == play.period and play.period >= 4 and abs(margin) <= 5:
                start = min(play.remaining_ms, 300000) if play.period == 4 else play.remaining_ms
                clutch_ms = max(0, start - following.remaining_ms)
                if clutch_ms:
                    tags.append("clutch")
        if play.period > 4 and (i == 0 or evidence.plays[i - 1].period != play.period):
            tags.append("overtime")
        if tags:
            result.append({"source_play_id": play.external_id, "index": play.index,
                "period": play.period, "remaining_ms": play.remaining_ms,
                "home": play.home, "away": play.away, "tags": tags,
                "clutch_ms": clutch_ms})
    return result
