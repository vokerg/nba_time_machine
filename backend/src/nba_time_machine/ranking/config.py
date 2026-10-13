"""Product-tunable coarse disclosure, independent of the score model."""
from pydantic_settings import BaseSettings, SettingsConfigDict

from nba_time_machine.ranking.disclosure import VerdictBands


class RankingDisclosureSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RANKING_VERDICT_")

    medium_from: float = 4.0
    high_from: float = 7.0
    low_label: str = "Lower priority"
    medium_label: str = "Worth considering"
    high_label: str = "Worth watching"

    def bands(self) -> VerdictBands:
        # Validation stays in the shared contract, including finite thresholds.
        return VerdictBands(
            self.medium_from, self.high_from,
            self.low_label, self.medium_label, self.high_label,
        )
