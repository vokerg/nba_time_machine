from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from nba_time_machine.sports.collection import CoverageReport, source_policy, validate_window
from nba_time_machine.sports.config import SportsProviderSettings
from nba_time_machine.sports.thesportsdb import TheSportsDBClient


def test_windows_do_not_silently_collect_a_different_season():
    validate_window('2025-2026', date(2025, 10, 1), date(2026, 6, 30))
    validate_window('2026-2027', None, None)
    for start, end in [(date(2026, 10, 1), date(2026, 10, 2)), (date(2025, 10, 2), date(2025, 10, 1)), (date(2025, 10, 1), None)]:
        with pytest.raises(ValueError):
            validate_window('2025-2026', start, end)


def test_verified_manual_run_does_not_enable_scheduling_or_weaken_retention():
    source = SimpleNamespace(enabled=False, verification_status='verified', adapter='thesportsdb',
                             locator='https://www.thesportsdb.com/api/v1/json', requires_auth=False,
                             retention_policy='normalized_full', adapter_settings={})
    with pytest.raises(ValueError, match='disabled'):
        source_policy(source, False)
    source_policy(source, True)
    assert not source.enabled
    for field, value in [('verification_status', 'unverified'), ('retention_policy', 'metadata_only'), ('requires_auth', True)]:
        other = SimpleNamespace(**vars(source))
        setattr(other, field, value)
        with pytest.raises(ValueError):
            source_policy(other, True)


@pytest.mark.asyncio
async def test_season_endpoint_uses_nba_identity_and_handles_missing_coverage():
    def handler(request):
        assert request.url.path.endswith('/eventsseason.php')
        assert dict(request.url.params) == {'id': '4387', 's': '2025-2026'}
        return httpx.Response(200, json={'events': None})
    async with httpx.AsyncClient(base_url='https://test.invalid', transport=httpx.MockTransport(handler)) as http:
        async with TheSportsDBClient(SportsProviderSettings(), http_client=http) as client:
            assert await client.season_events('2025-2026') == []
    assert CoverageReport('2025-2026').complete_season_verified is False
