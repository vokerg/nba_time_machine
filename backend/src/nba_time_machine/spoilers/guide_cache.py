"""Bounded internal day snapshots; disclosure/permissions are never cached.

PostgreSQL row versions detect committed inserts, updates and deletes, including
in-place corrections. Eligibility and validity flags also change the signature
as the clock crosses a boundary without any write. No captured text is hashed,
transferred or retained here. The deliberately conservative signature spans the
structured sports inputs, so an unrelated sports update can evict a warm day.
"""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from sqlalchemy import text


# These are fixed repository-owned table names, never request/source input.
# Row IDs + xmin identify versions without downloading provider evidence JSON.
# Ignore acknowledgement and operator/job writes: they do not change game facts.
_STATIC_TABLES = ("sources", "seasons", "teams", "games", "sports_external_identities")
_SIGNATURE = text("""
SELECT encode(sha256(convert_to(coalesce(string_agg(version, ',' ORDER BY version), ''), 'UTF8')), 'hex')
FROM (
""" + "\nUNION ALL\n".join(
    f"SELECT '{table}:' || id::text || ':' || xmin::text AS version FROM {table}"
    for table in _STATIC_TABLES
) + """
UNION ALL
SELECT 'observation:' || id::text || ':' || xmin::text FROM game_observations
WHERE available_at <= :cutoff AND observed_at <= :cutoff
UNION ALL
SELECT 'fact:' || id::text || ':' || xmin::text || ':' ||
       (valid_from <= :cutoff)::text || ':' || (valid_to IS NULL OR valid_to > :cutoff)::text
FROM temporal_facts
WHERE game_id IS NOT NULL AND available_at <= :cutoff AND observed_at <= :cutoff
  AND (fact_type = 'provider_game_evidence' OR fact_type LIKE 'ranking.postgame.%')
UNION ALL
SELECT 'score:' || id::text || ':' || xmin::text FROM recommendation_scores
WHERE as_of <= :cutoff
) AS revisions
""")


async def guide_revision(session, cutoff):
    return await session.scalar(_SIGNATURE, {"cutoff": cutoff})


@dataclass
class PreparedDay:
    slate: object
    snapshots: dict
    scores: dict | None = None
    expectations: dict | None = None


class GuideDayCache:
    def __init__(self, capacity=32, max_age=3600):
        self.capacity, self.max_age = capacity, max_age
        self.entries = OrderedDict()
        self.lock = asyncio.Lock()

    def get(self, key):
        item = self.entries.pop(key, None)
        if item is None:
            return None
        created, value = item
        if monotonic() - created >= self.max_age:
            return None
        self.entries[key] = item
        return value

    def put(self, key, value):
        self.entries[key] = monotonic(), value
        self.entries.move_to_end(key)
        while len(self.entries) > self.capacity:
            self.entries.popitem(last=False)
