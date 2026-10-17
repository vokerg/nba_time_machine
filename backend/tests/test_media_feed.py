"""Cursor-signed pagination and conservative revision-level media clearance."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nba_time_machine.api.media_feed import get_media_service
from nba_time_machine.api.read_models import MediaFeedItemResponse, MediaFeedResponse
from nba_time_machine.ingestion.adapters import canonical_url
from nba_time_machine.main import app
from nba_time_machine.spoilers.media_feed import PageKey, _trusted_capture, decode_page, encode_page
from nba_time_machine.temporal.timeline import TimelineNotInitializedError, TimelineState

CURSOR = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)
PROFILE = uuid4()


def fixture(*, changed=None):
    item_id, capture_id = uuid4(), uuid4()
    stamp = CURSOR - timedelta(hours=2)
    item = SimpleNamespace(id=item_id, source_id="fixture", discovered_at=stamp, available_at=stamp)
    source = SimpleNamespace(
        id="fixture", name="Fixture publisher", verification_status="verified",
        requires_auth=False, kind="web", retention_policy="metadata_excerpt",
    )
    capture = SimpleNamespace(
        id=capture_id, source_id="fixture", source_item_id=item_id,
        content_type="application/rss+xml", title="Pregame feature",
        text_content="Information collected and reviewed", captured_at=stamp,
        discovered_at=stamp, available_at=stamp,
        canonical_url="https://example.org/feature",
    )
    review = SimpleNamespace(
        capture_id=capture_id, reviewed_at=stamp + timedelta(hours=1),
        sensitivity="general", game_ids=[], rights_cleared=True, link_cleared=True,
    )
    objects = dict(item=item, source=source, capture=capture, review=review)
    for kind, fields in (changed or {}).items():
        objects[kind] = SimpleNamespace(**{**vars(objects[kind]), **fields})
    return objects


def test_page_tokens_bind_exact_global_cursor_and_exclude_invalid_tokens():
    key = PageKey(CURSOR - timedelta(minutes=20), uuid4())
    token = encode_page(key, CURSOR)
    assert decode_page(token, CURSOR) == key
    for invalid, cursor in (
        (token, CURSOR + timedelta(seconds=1)),
        ("!", CURSOR),
        ("a" * 513, CURSOR),
    ):
        with pytest.raises(ValueError, match="page token"):
            decode_page(invalid, cursor)
    assert decode_page(None, CURSOR) is None


@pytest.mark.parametrize("change", [
    {"capture": {"title": " "}},
    {"capture": {"content_type": "application/javascript"}},
    {"capture": {"captured_at": CURSOR + timedelta(seconds=1)}},
    {"capture": {"available_at": None}},
    {"source": {"verification_status": "unverified"}},
    {"review": {"rights_cleared": False}},
    {"review": {"reviewed_at": CURSOR + timedelta(seconds=1)}},
    {"review": {"sensitivity": "unknown"}},
    {"review": {"sensitivity": "outcome_dependent"}},
    {"review": {"game_ids": [uuid4()]}},
    {"item": {"available_at": None}},
])
def test_uncertain_or_unreviewed_revisions_fail_closed(change):
    assert _trusted_capture(**fixture(changed=change), cursor=CURSOR) is None


def test_review_time_is_true_availability_and_retention_blocks_excerpt():
    data = fixture()
    media, known = _trusted_capture(**data, cursor=CURSOR)
    assert known == data["review"].reviewed_at
    assert media.fields[0].value == "Pregame feature"
    assert media.fields[1].value == "Information collected and reviewed"
    data = fixture(changed={"source": {"retention_policy": "metadata_only"}})
    media, _ = _trusted_capture(**data, cursor=CURSOR)
    assert len(media.fields) == 1
    assert canonical_url("javascript:alert(1)") is None


class FakeTimeline:
    def __init__(self):
        self.cursor = CURSOR

    async def resume(self, profile_id):
        if profile_id != PROFILE:
            raise TimelineNotInitializedError("missing")
        return TimelineState(profile_id, self.cursor, CURSOR, CURSOR)


class FakeMedia:
    def __init__(self):
        self.calls = []

    async def list_items(self, profile_id, *, cursor, limit, page):
        self.calls.append((profile_id, cursor, limit, page))
        return MediaFeedResponse(
            time_cursor=cursor,
            items=(MediaFeedItemResponse(item_id=str(uuid4()), headline="Reviewed"),),
        )


def test_http_enforces_saved_cursor_pagination_validation_and_profile():
    timeline, media = FakeTimeline(), FakeMedia()
    app.dependency_overrides[get_media_service] = lambda: (timeline, media)
    try:
        with TestClient(app) as client:
            url = f"/profiles/{PROFILE}/media"
            assert client.get(url).status_code == 422
            assert client.get(url, params={"time_cursor": "2026-10-15T12:00:00"}).status_code == 422
            assert client.get(url, params={"time_cursor": CURSOR.isoformat(), "limit": 100}).status_code == 422
            assert client.get(f"/profiles/{uuid4()}/media", params={"time_cursor": CURSOR.isoformat()}).status_code == 404
            assert client.get(url, params={"time_cursor": (CURSOR-timedelta(seconds=1)).isoformat()}).status_code == 409
            result = client.get(url, params={"time_cursor": CURSOR.isoformat()})
            assert result.status_code == 200
            assert result.json()["items"][0]["headline"] == "Reviewed"
            assert media.calls == [(PROFILE, CURSOR, 10, None)]
            class Advances(FakeMedia):
                async def list_items(self, profile_id, *, cursor, limit, page):
                    timeline.cursor += timedelta(hours=1)
                    return await super().list_items(profile_id, cursor=cursor, limit=limit, page=page)
            app.dependency_overrides[get_media_service] = lambda: (timeline, Advances())
            assert client.get(url, params={"time_cursor": CURSOR.isoformat()}).status_code == 409
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("kind", ["web", "media", "podcast"])
def test_registered_article_and_podcast_source_kinds_are_reviewable(kind):
    # Registry uses 'media' for national publishers (not only 'web').
    # The revision still needs an explicit timely review and source verification.
    args = fixture(changed={"source": {"kind": kind}})
    assert _trusted_capture(**args, cursor=CURSOR) is not None
    args = fixture(changed={"source": {"kind": kind, "verification_status": "unverified"}})
    assert _trusted_capture(**args, cursor=CURSOR) is None
    args = fixture(changed={"source": {"kind": kind}, "review": {"rights_cleared": False}})
    assert _trusted_capture(**args, cursor=CURSOR) is None


@pytest.mark.parametrize("kind", ["structured", "stats_site", "x_account", "youtube", "document", "video"])
def test_unapproved_or_unimplemented_source_kinds_remain_blocked(kind):
    assert _trusted_capture(**fixture(changed={"source": {"kind": kind}}), cursor=CURSOR) is None
