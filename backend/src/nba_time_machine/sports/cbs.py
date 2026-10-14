"""CBS HTML backup. Never execute embedded JS or invent absent play identities."""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from html.parser import HTMLParser

from nba_time_machine.sports.espn import minutes, parse_statistics
from nba_time_machine.sports.morning_models import (
    EASTERN, TEAM_NAMES, Evidence, GameRef, Play, PlayerBox, Team, abbreviation, assess, clock_ms,
)

GAME_ABBR = re.compile(r"NBA_(\d{8})_([A-Z]{2,4})@([A-Z]{2,4})")


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list = field(default_factory=list)

    def find(self, tag: str):
        for child in self.children:
            if isinstance(child, Element):
                if child.tag == tag:
                    yield child
                yield from child.find(tag)

    def text(self) -> str:
        return " ".join(" ".join(c.text() if isinstance(c, Element) else c for c in self.children).split())


class Document(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.root = Element("root")
        self.stack = [self.root]
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        if len(self.stack) > 150:
            raise ValueError("html_depth_limit")
        node = Element(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Element(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def ref_from_abbr(value: str) -> GameRef:
    match = GAME_ABBR.fullmatch(value)
    if not match:
        raise ValueError("invalid_cbs_game")
    day, away, home = match.groups()
    return GameRef(provider="cbs", external_id=value,
        day=datetime.strptime(day, "%Y%m%d").date(), home=abbreviation(home), away=abbreviation(away))


def schedule(content: str, day: date) -> list[GameRef]:
    doc = Document(content)
    from urllib.parse import unquote
    refs = {}
    for link in doc.root.find("a"):
        url = unquote(link.attrs.get("href") or "")
        if "/nba/gametracker/" not in url:
            continue
        match = GAME_ABBR.search(url)
        if match:
            ref = ref_from_abbr(match.group())
            if ref.day == day:
                refs[ref.key] = ref
    # A changed/empty HTML page is not proof that the NBA had no games.
    if not refs:
        raise ValueError("cbs_schedule_unverified_empty")
    return list(refs.values())


def gametracker(content: str, ref: GameRef, observed_at: datetime) -> Evidence:
    match = re.search(r"var current_game_scoreboard\s*=\s*JSON\.parse\('((?:\\.|[^'])*)'\.replace", content)
    if not match:
        raise ValueError("missing_cbs_scoreboard")
    data = json.loads(html.unescape(match[1]).replace("\\'", "'"))
    actual = ref_from_abbr(data["gameAbbr"])
    if actual.key != ref.key:
        raise ValueError("wrong_cbs_matchup")
    tip = datetime.fromtimestamp(int(data["scheduled_epoch"]), timezone.utc)
    if tip.astimezone(EASTERN).date() != ref.day:
        raise ValueError("wrong_cbs_day")
    if ref.scheduled_at and abs((tip - ref.scheduled_at).total_seconds()) > 1800:
        raise ValueError("cbs_tip_mismatch")
    teams = {}
    for side in ("home", "away"):
        row = data[side + "team"]
        abbr = abbreviation(row["abbr"])
        if abbr != getattr(ref, side):
            raise ValueError("wrong_cbs_team")
        period_map = data["game_status"][side + "score"]["quarter"]
        if sorted(map(int, period_map)) != list(range(1, len(period_map) + 1)):
            raise ValueError("missing_cbs_period_totals")
        teams[side] = Team(external_id=str(row["id"]), abbreviation=abbr,
            name=TEAM_NAMES[abbr], score=int(data[side + "TeamScore"]),
            periods=tuple(int(period_map[str(i)]) for i in range(1, len(period_map) + 1)))
    doc = Document(content)
    plays, players, pbp_errors, box_errors = [], {}, [], []
    pbp_period = 0
    home_score = away_score = 0
    try:
        for table in doc.root.find("table"):
            headings = [cell.text() for cell in table.find("th")]
            if headings != ["Time", "Team", "", "Play", "Score"]:
                continue
            pbp_period += 1
            for row in table.find("tr"):
                cells = list(row.find("td"))
                if not cells:
                    continue
                if len(cells) != 5:
                    raise ValueError("invalid_cbs_play_row")
                values = [c.text() for c in cells]
                if values[4]:
                    parts = values[4].split("-")
                    if len(parts) != 2:
                        raise ValueError("invalid_cbs_score")
                    away_score, home_score = map(int, parts)
                end = values[3].strip().lower() == "end of period"
                plays.append(Play(index=len(plays), period=pbp_period, remaining_ms=clock_ms(values[0]),
                    home=home_score, away=away_score, kind="period_end" if end else "play", period_end=end))
    except (ValueError, TypeError, KeyError):
        plays = []
        pbp_errors.append("invalid_cbs_play_schema")
    # Find team ownership from the canonical box panel, not table order or row position.
    try:
        # Observed GameTracker ownership panels, rather than table position or
        # arbitrary team-like CSS classes elsewhere in the document.
        def walk(node, team_id=None):
            if not isinstance(node, Element):
                return
            attrs = node.attrs
            if attrs.get("id") == "player-stats-away":
                team_id = teams["away"].external_id
            if attrs.get("id") == "player-stats-home":
                team_id = teams["home"].external_id
            if node.tag == "table":
                rows = list(node.find("tr"))
                header = next(([c.text() for c in r.find("td")] for r in rows
                               if "MIN" in [c.text() for c in r.find("td")]), None)
                if header and "PTS" in header and team_id is not None:
                    if team_id is None:
                        raise ValueError("unknown_cbs_box_team")
                    for row in rows:
                        links = [link for link in row.find("a") if re.search(r"/nba/players/\d+/", link.attrs.get("href") or "")]
                        if not links:
                            continue
                        player_id = re.search(r"/nba/players/(\d+)/", links[0].attrs["href"])[1]
                        values = [c.text() for c in row.find("td")]
                        dnp = any("DNP" in v.upper() or "DID NOT PLAY" in v.upper() for v in values[1:])
                        stats = dict(zip(header[1:], values[1:], strict=True)) if len(values) == len(header) else {}
                        played = bool(stats and str(stats.get("PTS", "")).isdigit())
                        minute, precision = minutes(stats["MIN"]) if played else (None, "unknown")
                        entry = PlayerBox(external_id=player_id, team_id=team_id, name=links[0].text(),
                            starter=header[0] == "Starters", did_not_play=False if played else (True if dnp else None),
                            minutes=minute, minutes_precision=precision,
                            statistics=parse_statistics(stats) if played else {})
                        if player_id in players and players[player_id] != entry:
                            raise ValueError("conflicting_cbs_player_rows")
                        players[player_id] = entry
                    return
            for child in node.children:
                walk(child, team_id)
        walk(doc.root)
    except (ValueError, KeyError, TypeError):
        players = {}
        box_errors.append("invalid_cbs_box_schema")
    game_type = {"pre": "preseason", "reg": "regular_season", "post": "playoffs"}.get(data.get("seasonType"))
    if game_type is None:
        game_type = {"Preseason": "preseason", "Regular Season": "regular_season", "Playoffs": "playoffs"}[data["type"]]
    year = int(data["seasonYear"])
    if year != ref.day.year - (ref.day.month < 7):
        raise ValueError("wrong_cbs_season")
    return assess(Evidence(provider="cbs", external_id=str(data["id"]), ref=actual.model_copy(update={"scheduled_at": tip}),
        observed_at=observed_at, season=f"{year}-{year + 1}", game_type=game_type,
        status="final" if data["status"] == "FINAL" else "pending", home=teams["home"], away=teams["away"],
        plays=tuple(plays), players=tuple(players.values()), pbp_errors=tuple(pbp_errors), box_errors=tuple(box_errors),
        notes=("no_stable_play_ids", "no_verified_event_wallclocks", "rounded_player_minutes")))
