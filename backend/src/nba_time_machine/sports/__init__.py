"""Structured sports provider boundaries."""

from .config import SportsProviderSettings, load_sports_provider_settings
from .thesportsdb import TheSportsDBClient

__all__ = [
    "SportsProviderSettings",
    "TheSportsDBClient",
    "load_sports_provider_settings",
]
