"""Share current-evidence verification within one consented guide request only."""
from nba_time_machine.ranking.evidence import SqlAlchemyRankingEvidenceRepository
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline


class RequestScoreVerifier:
    def __init__(self, session):
        self.pipeline = MorningRankingPipeline(session)
        self.evidence = SqlAlchemyRankingEvidenceRepository(session)
        self._morning = {}

    async def morning_many(self, game_ids, cutoff):
        missing = tuple(gid for gid in game_ids if (gid, cutoff) not in self._morning)
        if missing:
            values = await self.pipeline.derive_many(missing, as_of=cutoff)
            self._morning.update({(gid, cutoff): result[2] if result is not None else None
                                  for gid, result in values.items()})
        return {gid: self._morning[gid, cutoff] for gid in game_ids}

    async def __call__(self, gid, cutoff):
        result = (await self.morning_many((gid,), cutoff))[gid]
        if result is not None:
            return result
        return await self.evidence.postgame(gid, as_of=cutoff)
