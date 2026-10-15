"""Measured player production and extreme game patterns, independent of tuning.

Outcome-bearing internal evidence. No historical rarity claims, name-based star
weights, provider mixing, repaired plays or precision invented from rounded minutes.
"""
from dataclasses import dataclass

from nba_time_machine.sports.morning_models import Evidence, assess

ENRICHMENT_VERSION = "entertainment-measurements-v1"
STATS = {"PTS", "REB", "OREB", "DREB", "AST", "STL", "BLK", "TO",
         "FGM", "FGA", "3PTM", "3PTA", "FTM", "FTA"}


@dataclass(frozen=True)
class EntertainmentMeasurements:
    players: tuple[dict, ...] | None
    patterns: tuple[dict, ...] | None
    player_errors: tuple[str, ...]
    pattern_errors: tuple[str, ...]
    version: str = ENRICHMENT_VERSION


def _box_consistent(evidence: Evidence) -> bool:
    for p in evidence.players:
        if p.did_not_play is not False:
            continue
        s = p.statistics
        if (not STATS.issubset(s) or any(type(s[k]) is not int or s[k] < 0 for k in STATS)
                or s["FGM"] > s["FGA"] or s["3PTM"] > s["3PTA"]
                or s["3PTM"] > s["FGM"] or s["3PTA"] > s["FGA"]
                or s["FGM"] - s["3PTM"] > s["FGA"] - s["3PTA"]
                or s["FTM"] > s["FTA"] or s["REB"] != s["OREB"] + s["DREB"]
                or s["PTS"] != 2 * s["FGM"] + s["3PTM"] + s["FTM"]):
            return False
    return True


def _player_rows(e: Evidence) -> tuple[dict, ...]:
    rows = []
    for player in e.players:
        if player.did_not_play is not False:
            continue
        s = player.statistics
        # NBA glossary TS approximation; undefined with no shooting attempts.
        attempts = s["FGA"] + .44 * s["FTA"]
        rows.append({"provider": e.provider, "player_id": player.external_id,
            "name": player.name, "team_id": player.team_id,
            "team": e.home.abbreviation if player.team_id == e.home.external_id else e.away.abbreviation,
            "minutes": player.minutes, "minutes_precision": player.minutes_precision,
            "statistics": dict(s), "true_shooting": s["PTS"] / (2 * attempts) if attempts else None,
            "double_digit_categories": sum(s[k] >= 10 for k in ("PTS", "REB", "AST", "STL", "BLK")),
            "box_reference": f"{e.provider}:{e.external_id}:player:{player.external_id}"})
    return tuple(rows)


def elapsed_ms(play) -> int:
    if play.period <= 4:
        return (play.period - 1) * 720000 + 720000 - play.remaining_ms
    return 2880000 + (play.period - 5) * 300000 + 300000 - play.remaining_ms


def _pattern_rows(e: Evidence) -> tuple[dict, ...]:
    rows = []
    for signal, label, candidates in (
        ("max_lead", "Largest lead at any point", e.plays),
        ("first_half_lead", "Largest first-half lead", tuple(p for p in e.plays if p.period <= 2)),
    ):
        play = max(candidates, key=lambda p: abs(p.home - p.away))
        team = e.home if play.home >= play.away else e.away
        rows.append({"signal": signal, "label": label, "raw": abs(play.home - play.away),
            "unit": "points", "team": team.abbreviation, "period": play.period,
            "source_play_ids": [play.external_id], "remaining_ms": play.remaining_ms})
    quarters = [(team.periods[p - 1], p, team)
                for team in (e.home, e.away) for p in range(1, 5)]
    ends = {p.period: p for p in e.plays if p.period_end and p.period <= 4}
    for signal, label, (points, period, team) in (
        ("low_quarter", "Lowest regulation quarter by one team", min(quarters, key=lambda q: q[0])),
        ("high_quarter", "Highest regulation quarter by one team", max(quarters, key=lambda q: q[0])),
    ):
        rows.append({"signal": signal, "label": label, "raw": points, "unit": "points",
            "team": team.abbreviation, "period": period,
            "source_play_ids": [ends[period].external_id], "remaining_ms": 0})
    period = max(range(1, 5), key=lambda p: abs(e.home.periods[p - 1] - e.away.periods[p - 1]))
    team = e.home if e.home.periods[period - 1] >= e.away.periods[period - 1] else e.away
    rows.append({"signal": "quarter_margin", "label": "Largest regulation quarter margin",
        "raw": abs(e.home.periods[period - 1] - e.away.periods[period - 1]), "unit": "points",
        "team": team.abbreviation, "period": period,
        "source_play_ids": [ends[period].external_id], "remaining_ms": 0})
    droughts = []
    for side, team in (("home", e.home), ("away", e.away)):
        last_score, last_time, last_play = 0, 0, e.plays[0]
        best = (0, e.plays[0], e.plays[0])
        for play in e.plays:
            clock = elapsed_ms(play)
            if clock - last_time > best[0]:
                best = clock - last_time, last_play, play
            value = getattr(play, side)
            if value != last_score:
                last_time, last_play = clock, play
            last_score = value
        droughts.append((best, team))
    (duration, start, end), team = max(droughts, key=lambda pair: pair[0][0])
    rows.append({"signal": "scoring_drought", "label": "Longest team scoring drought",
        "raw": duration, "unit": "milliseconds", "team": team.abbreviation,
        "period": end.period, "start_elapsed_ms": elapsed_ms(start),
        "end_elapsed_ms": elapsed_ms(end), "source_play_ids": [start.external_id, end.external_id],
        "remaining_ms": end.remaining_ms})
    return tuple(rows)


def entertainment_measurements(evidence: Evidence) -> EntertainmentMeasurements:
    checked = assess(evidence)
    box_errors = set(checked.box_errors)
    if not _box_consistent(checked):
        box_errors.add("inconsistent_player_box_statistics")
    return EntertainmentMeasurements(
        players=_player_rows(checked) if checked.box_usable and not box_errors else None,
        patterns=_pattern_rows(checked) if checked.pbp_usable else None,
        player_errors=tuple(sorted(box_errors)), pattern_errors=checked.pbp_errors,
    )
