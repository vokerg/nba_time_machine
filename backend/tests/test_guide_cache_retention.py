"""Bound prepared day retention without caching permission or consent."""
from unittest.mock import patch

from nba_time_machine.spoilers.guide_cache import GuideDayCache


def test_cache_has_fixed_capacity_and_expires_without_extending_on_read():
    with patch("nba_time_machine.spoilers.guide_cache.monotonic", return_value=0) as now:
        cache = GuideDayCache(capacity=2, max_age=60)
        cache.put("first", 1)
        cache.put("second", 2)
        assert cache.get("first") == 1
        cache.put("third", 3)
        assert cache.get("second") is None
        now.return_value = 59
        assert cache.get("first") == 1
        now.return_value = 60
        assert cache.get("first") is None
        assert cache.get("third") is None
