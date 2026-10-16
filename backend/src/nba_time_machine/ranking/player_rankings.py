"""Validated normalized imports; no publisher scraping or historical backdating."""
import hashlib
import json
import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

SOURCE_ID = 'ringer-nba-top100-manual'
SOURCE_URL = 'https://www.theringer.com/nba-ranked/top-100'
FACT_TYPE = 'player_rankings.ringer-v1'


def normalized_name(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower())


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class RankedPlayer(Model):
    rank: int = Field(ge=1, le=100, strict=True)
    name: str = Field(min_length=1, max_length=120)
    team: str | None = Field(default=None, max_length=8)
    source_player_id: str | None = Field(default=None, max_length=160)
    espn_id: str | None = Field(default=None, pattern=r'^[0-9]{1,20}$')
    espn_name_alias: str | None = Field(default=None, max_length=120)
    alias_review: str | None = Field(default=None, max_length=500)

    @model_validator(mode='after')
    def valid(self):
        from nba_time_machine.sports.morning_models import TEAM_NAMES
        if not normalized_name(self.name) or (self.team is not None and self.team not in TEAM_NAMES):
            raise ValueError('invalid player name or NBA team abbreviation')
        if self.espn_name_alias and (not self.espn_id or not self.alias_review):
            raise ValueError('aliases require explicit ESPN ID and review reference')
        return self


class RankingImport(Model):
    schema_version: Literal[1] = 1
    provider: Literal['The Ringer'] = 'The Ringer'
    ranking_version: str = Field(min_length=1, max_length=120)
    season: str = Field(pattern=r'^20[0-9]{2}-20[0-9]{2}$')
    source_url: Literal['https://www.theringer.com/nba-ranked/top-100'] = SOURCE_URL
    published_date: date | None = None
    publication_status: Literal['publisher_date_only', 'unknown']
    publication_reference: str | None = Field(default=None, max_length=500)
    permission_reference: str = Field(min_length=1, max_length=500)
    players: tuple[RankedPlayer, ...] = Field(min_length=100, max_length=100)

    @model_validator(mode='after')
    def valid(self):
        if set(p.rank for p in self.players) != set(range(1, 101)):
            raise ValueError('exactly one player at each rank 1–100 is required')
        for attr in ('source_player_id', 'espn_id'):
            values = [getattr(p, attr) for p in self.players if getattr(p, attr)]
            if len(set(values)) != len(values):
                raise ValueError('duplicate player identity')
        if (self.publication_status == 'publisher_date_only') != (self.published_date is not None):
            raise ValueError('publication status must describe the supplied date')
        if self.published_date and not self.publication_reference:
            raise ValueError('published date needs provenance; it never establishes historical availability')
        start, end = map(int, self.season.split('-'))
        if end != start + 1:
            raise ValueError('invalid season')
        return self


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def map_players(snapshot: RankingImport, catalog: list[dict]) -> list[dict]:
    """Catalog rows come from stored ESPN boxes; IDs never come from fuzzy guesses."""
    identities = {}
    for row in catalog:
        entry = identities.setdefault(row['espn_id'], {'names': set(), 'teams': set(), 'facts': set()})
        entry['names'].add(normalized_name(row['name']))
        entry['teams'].add(row['team'])
        entry['facts'].add(row['fact_id'])
    result = []
    for player in sorted(snapshot.players, key=lambda p: p.rank):
        name = normalized_name(player.espn_name_alias or player.name)
        if player.espn_id:
            candidates = [player.espn_id] if player.espn_id in identities and name in identities[player.espn_id]['names'] else []
            method = 'validated_explicit_id'
        else:
            candidates = [key for key, row in identities.items() if name in row['names']]
            if len(candidates) > 1 and player.team:
                candidates = [key for key in candidates if player.team in identities[key]['teams']]
            method = 'unique_name_team' if player.team else 'unique_name'
        status = 'matched' if len(candidates) == 1 else 'ambiguous' if candidates else 'unmatched'
        key = candidates[0] if status == 'matched' else None
        result.append({**player.model_dump(mode='json'), 'espn_id': key, 'mapping_status': status,
                       'mapping_method': method, 'mapping_fact_ids': sorted(identities[key]['facts']) if key else [],
                       'mapping_candidates': sorted(candidates)})
    # Two differently spelled source rows must never resolve to one person.
    ids = [r['espn_id'] for r in result if r['espn_id']]
    for row in result:
        if row['espn_id'] and ids.count(row['espn_id']) > 1:
            row.update(espn_id=None, mapping_status='ambiguous_duplicate_identity')
    return result
