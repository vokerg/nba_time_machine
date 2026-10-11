"""Bounded RSS/Atom and single-page HTML collectors; no crawling or spoiler decisions."""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

import httpx

from nba_time_machine.ingestion.contracts import RawCapture, SourceDefinition, VerificationStatus

MAX_BYTES = 512_000
MAX_ITEMS = 50
MAX_TEXT = 20_000
EXCERPT = 280
USER_AGENT = "NBA-Time-Machine/0.1 (+source-policy-aware research collector)"
SUPPORTED_ADAPTERS = frozenset({"rss", "atom", "rss_or_web", "web"})


class CollectionFailure(Exception):
    """A bounded, non-content-bearing collection failure."""

    def __init__(self, status: str, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class AdapterResult:
    captures: tuple[RawCapture, ...]
    status: str = "ok"


def canonical_url(value: str | None) -> str | None:
    """Require a public HTTP(S) destination and remove fragments/tracking."""
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").lower().rstrip(".")
        if parts.scheme not in {"https", "http"} or not host or parts.username:
            return None
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            address = ipaddress.ip_address(host)
            if not address.is_global:
                return None
        except ValueError:
            # System resolvers may interpret non-canonical numeric aliases
            # (127.1, 0177.0.0.1, 0x7f000001, 2130706433) as loopback.
            # Keep valid globally routed IP literals eligible.
            if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9]+)(?:\.(?:0x[0-9a-f]+|[0-9]+))*", host):
                return None
        query = urlencode(
            [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
        )
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", query, ""))
    except ValueError:
        return None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden and data.strip():
            self.blocks.append(data.strip())


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text = _Text()
        self.in_title = False
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.text.handle_starttag(tag, attrs)
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            attributes = dict(attrs)
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key and attributes.get("content"):
                self.meta[key] = attributes["content"]

    def handle_endtag(self, tag: str) -> None:
        self.text.handle_endtag(tag)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        self.text.handle_data(data)


def _plain(value: str | None) -> str | None:
    if value is None:
        return None
    parser = _Text()
    parser.feed(value)
    clean = re.sub(r"\s+", " ", " ".join(parser.blocks)).strip()
    return clean[:MAX_TEXT] or None


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _child(node: ET.Element, names: tuple[str, ...]) -> str | None:
    for child in node:
        local = child.tag.rsplit("}", 1)[-1]
        if local in names:
            return "".join(child.itertext()).strip() or None
    return None


def _atom_link(node: ET.Element) -> str | None:
    for child in node:
        if child.tag.rsplit("}", 1)[-1] == "link":
            if child.get("rel", "alternate") == "alternate" and child.get("href"):
                return child.get("href")
    return None


def _capture(
    source: SourceDefinition,
    *,
    now: datetime,
    external_id: str | None,
    url: str | None,
    published_at: datetime | None,
    title: str | None,
    author: str | None,
    text: str | None,
    payload: str,
    content_type: str,
) -> RawCapture:
    # Hash the obtained item/page, not a truncated excerpt, to detect revisions.
    return RawCapture(
        source_id=source.id,
        external_id=external_id,
        canonical_url=url,
        published_at=published_at,
        discovered_at=now,
        captured_at=now,
        content_type=content_type,
        title=title,
        author=author,
        text=text,
        raw_payload=payload,
        content_hash=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    )


def parse_feed(source: SourceDefinition, body: str, now: datetime) -> AdapterResult:
    if "<!DOCTYPE" in body.upper() or "<!ENTITY" in body.upper():
        raise CollectionFailure("parse_error", "unsafe_xml")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise CollectionFailure("parse_error", "invalid_xml") from exc
    local = root.tag.rsplit("}", 1)[-1].lower()
    if local == "rss":
        channel = next((e for e in root if e.tag.rsplit("}", 1)[-1] == "channel"), None)
        entries = [] if channel is None else [
            child for child in channel if child.tag.rsplit("}", 1)[-1] == "item"
        ]
    elif local == "feed":
        entries = [child for child in root if child.tag.rsplit("}", 1)[-1] == "entry"]
    else:
        raise CollectionFailure("parse_error", "not_rss_or_atom")

    captures: list[RawCapture] = []
    seen: set[str] = set()
    for entry in entries[:MAX_ITEMS]:
        link = canonical_url(_atom_link(entry) if local == "feed" else _child(entry, ("link",)))
        guid = _child(entry, ("guid", "id"))
        identity = guid or link
        if not identity or identity in seen:
            continue
        seen.add(identity)
        author = _child(entry, ("creator", "name", "author"))
        if local == "feed":
            author_node = next((e for e in entry if e.tag.rsplit("}", 1)[-1] == "author"), None)
            if author_node is not None:
                author = _child(author_node, ("name",)) or author
        title = _plain(_child(entry, ("title",)))
        description = _child(entry, ("description", "summary", "content", "encoded"))
        published = _published(_child(entry, ("pubDate", "published", "updated", "date")))
        captures.append(
            _capture(
                source, now=now, external_id=guid or link, url=link,
                published_at=published, title=title, author=_plain(author),
                text=_plain(description), payload=ET.tostring(entry, encoding="unicode"),
                content_type="application/atom+xml" if local == "feed" else "application/rss+xml",
            )
        )
    return AdapterResult(captures=tuple(captures), status="ok" if captures else "idle")


def parse_page(source: SourceDefinition, body: str, now: datetime) -> AdapterResult:
    parser = _Page()
    parser.feed(body)
    page_url = canonical_url(source.locator)
    if page_url is None:
        raise CollectionFailure("skipped_config", "invalid_url")
    title = _plain(parser.meta.get("og:title") or " ".join(parser.title_parts))
    published = _published(
        parser.meta.get("article:published_time") or parser.meta.get("date")
    )
    capture = _capture(
        source, now=now, external_id=page_url, url=page_url,
        published_at=published, title=title,
        author=_plain(parser.meta.get("author")),
        text=_plain(" ".join(parser.text.blocks)),
        payload=body, content_type="text/html",
    )
    return AdapterResult(captures=(capture,))


async def _request(
    client: httpx.AsyncClient, url: str, *, tries: int = 3
) -> tuple[str, str]:
    if canonical_url(url) is None:
        raise CollectionFailure("skipped_config", "invalid_url")
    for attempt in range(tries):
        try:
            async with client.stream(
                "GET", url, headers={"User-Agent": USER_AGENT},
                follow_redirects=False, timeout=httpx.Timeout(10.0),
            ) as response:
                if response.status_code == 401:
                    raise CollectionFailure("auth_error", "http_401")
                if response.status_code == 429:
                    raise CollectionFailure("rate_limited", "http_429")
                if response.status_code in {403, 404} or 300 <= response.status_code < 400:
                    raise CollectionFailure("blocked", "http_blocked_or_redirect")
                if response.status_code >= 500 and attempt + 1 < tries:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                if response.status_code >= 500:
                    raise CollectionFailure("network_error", "http_5xx")
                if response.status_code >= 400:
                    raise CollectionFailure("blocked", "http_4xx")
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise CollectionFailure("blocked", "max_bytes")
                mime = response.headers.get("content-type", "").split(";", 1)[0].lower()
                return data.decode("utf-8-sig", errors="replace"), mime
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt + 1 >= tries:
                raise CollectionFailure("network_error", "transport") from exc
            await asyncio.sleep(0.2 * (attempt + 1))
    raise CollectionFailure("network_error", "retry_exhausted")


async def collect_source(
    source: SourceDefinition, client: httpx.AsyncClient, now: datetime
) -> AdapterResult:
    """Fetch exactly one configured URL; only reviewed sources are eligible."""
    # Keep the network gate at the adapter boundary as well as the scheduler:
    # direct/manual callers must never bypass source review or disablement.
    if not source.enabled or source.verification_status != VerificationStatus.VERIFIED:
        raise CollectionFailure("skipped_config", "not_verified_or_enabled")
    if source.adapter not in SUPPORTED_ADAPTERS:
        raise CollectionFailure("skipped_config", "unsupported_adapter")
    if source.requires_auth:
        raise CollectionFailure("skipped_config", "auth_not_configured")
    url = canonical_url(source.locator)
    if url is None:
        raise CollectionFailure("skipped_config", "invalid_url")
    body, mime = await _request(client, url)
    if source.adapter in {"rss", "atom"} or (
        source.adapter == "rss_or_web"
        and (mime in {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"}
             or body.lstrip().startswith(("<?xml", "<rss", "<feed")))
    ):
        return parse_feed(source, body, now)
    if mime not in {"text/html", "application/xhtml+xml", ""}:
        raise CollectionFailure("parse_error", "unsupported_mime")
    return parse_page(source, body, now)
