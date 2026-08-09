"""Bounded, source-backed collection for the HoneyOS Topic Pool."""

from __future__ import annotations

import asyncio
import hashlib
import html
import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlsplit

from honeyos.companion.topic_pool import (
    ProactivePreferences,
    TopicCandidate,
    TopicItem,
    TopicPoolStore,
    normalize_source_url,
)


logger = logging.getLogger(__name__)

DEFAULT_DIRECTIONS = (
    "AI technology and useful software",
    "science discoveries and human stories",
    "games culture design and unusual ideas",
)
MAX_RAW_CANDIDATES = 30
MAX_VERIFIED_CANDIDATES = 12
MAX_ACCEPTED = 3
MAX_EXCERPT_CHARS = 4000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RawCandidate:
    id: str
    title: str
    url: str
    source_name: str
    description: str
    category: str
    published_at: datetime | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class VerifiedCandidate:
    raw: RawCandidate
    excerpt: str


@dataclass(frozen=True)
class SelectedTopic:
    candidate_id: str
    hook: str
    category: str
    score: float
    reason: str


@dataclass(frozen=True)
class CollectionResult:
    accepted: tuple[TopicItem, ...] = ()
    raw_count: int = 0
    verified_count: int = 0
    skipped_reason: str = ""


SearchFn = Callable[[str, int], Awaitable[Sequence[RawCandidate]]]
FetchFn = Callable[[RawCandidate], Awaitable[VerifiedCandidate | None]]
FilterFn = Callable[
    [Sequence[VerifiedCandidate], ProactivePreferences, Mapping[str, Any] | None],
    Awaitable[Sequence[SelectedTopic]],
]


def _stable_candidate_id(url: str, title: str) -> str:
    payload = f"{url}\n{' '.join(title.lower().split())}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _literal_public_url(url: str) -> bool:
    """Reject malformed URLs and literal non-public IPs before DNS checks."""

    try:
        parts = urlsplit(str(url).strip())
    except ValueError:
        return False
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return False
    try:
        address = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return True
    return bool(address.is_global)


def parse_web_search_results(
    payload: str | Mapping[str, Any], *, category: str
) -> list[RawCandidate]:
    """Normalize the stable `web_search_tool` envelope into Scout candidates."""

    try:
        parsed = json.loads(payload) if isinstance(payload, str) else dict(payload)
    except (TypeError, ValueError):
        return []
    data = parsed.get("data", {}) if isinstance(parsed, dict) else {}
    rows = data.get("web", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []
    results: list[RawCandidate] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = " ".join(str(row.get("title") or "").split())
        raw_url = str(row.get("url") or row.get("href") or "").strip()
        if not title or not _literal_public_url(raw_url):
            continue
        try:
            url = normalize_source_url(raw_url)
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        source_name = urlsplit(url).hostname or "Web"
        results.append(
            RawCandidate(
                id=_stable_candidate_id(url, title),
                title=title[:500],
                url=url,
                source_name=source_name[:120],
                description=" ".join(
                    str(row.get("description") or row.get("snippet") or "").split()
                )[:2000],
                category=" ".join(str(category or "general").split())[:80],
                source_id=str(row.get("id") or "").strip() or None,
            )
        )
    return results


def parse_filter_response(
    payload: str | Mapping[str, Any], *, allowed_ids: set[str]
) -> tuple[SelectedTopic, ...]:
    """Validate strict model output without accepting invented candidates."""

    try:
        parsed = json.loads(payload) if isinstance(payload, str) else dict(payload)
    except (TypeError, ValueError):
        return ()
    rows = parsed.get("topics", []) if isinstance(parsed, dict) else []
    if not isinstance(rows, list):
        return ()
    selected: list[SelectedTopic] = []
    seen: set[str] = set()
    for row in rows:
        if len(selected) >= MAX_ACCEPTED or not isinstance(row, dict):
            break
        candidate_id = str(row.get("candidate_id") or "").strip()
        hook = " ".join(str(row.get("hook") or "").split())
        category = " ".join(str(row.get("category") or "general").split())
        reason = " ".join(str(row.get("reason") or "").split())
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            continue
        if (
            candidate_id not in allowed_ids
            or candidate_id in seen
            or not hook
            or not reason
            or not 0 <= score <= 1
        ):
            continue
        seen.add(candidate_id)
        selected.append(
            SelectedTopic(
                candidate_id=candidate_id,
                hook=hook[:1000],
                category=category[:80] or "general",
                score=score,
                reason=reason[:1000],
            )
        )
    return tuple(selected)


async def default_web_search(query: str, limit: int) -> list[RawCandidate]:
    from honeyos.tools.web_tools import web_search_tool

    raw = await asyncio.to_thread(web_search_tool, query, limit)
    return parse_web_search_results(raw, category=query.split(" latest", 1)[0])


_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def _text_excerpt(content: str) -> str:
    without_code = _SCRIPT_STYLE_RE.sub(" ", content)
    plain = _TAG_RE.sub(" ", without_code)
    return _SPACE_RE.sub(" ", html.unescape(plain)).strip()[:MAX_EXCERPT_CHARS]


async def default_fetch_source(item: RawCandidate) -> VerifiedCandidate | None:
    """Verify one public result with a bounded, SSRF-safe direct fetch."""

    from honeyos.tools.url_safety import (
        async_is_safe_url,
        create_ssrf_safe_async_client,
    )

    if not await async_is_safe_url(item.url):
        return None
    try:
        async with create_ssrf_safe_async_client(
            timeout=12,
            follow_redirects=True,
            headers={"User-Agent": "HoneyOS-TopicScout/1.0"},
        ) as client:
            response = await client.get(item.url)
            response.raise_for_status()
            content_type = str(response.headers.get("content-type") or "").lower()
            if not any(kind in content_type for kind in ("text/", "html", "json", "xml")):
                return None
            content = response.text[:250_000]
    except Exception as exc:  # noqa: BLE001 - one failed source must not kill a round
        logger.debug("Topic Scout source verification failed for %s: %s", item.url, exc)
        return None
    excerpt = _text_excerpt(content)
    if len(excerpt) < 80:
        return None
    return VerifiedCandidate(raw=item, excerpt=excerpt)


_FILTER_PROMPT = """You select short-lived conversation seeds for a private AI companion.
Return strict JSON: {"topics":[{"candidate_id":"...","hook":"...","category":"...","score":0.0,"reason":"..."}]}.
Return zero to three items. An empty topics array is valid and preferred over weak material.
Use only candidate_id values from the input. Never invent facts, URLs, sources or IDs.
Choose for user relevance, freshness, source quality, safety, novelty and conversational potential.
The hook is a grounded angle worth continuing, not a finished article, clickbait headline, question bait or marketing copy.
Reject duplicate, unverifiable, stale, blocked-category or purely promotional material.
Do not write the final user-facing companion message."""


async def filter_with_auxiliary_model(
    candidates: Sequence[VerifiedCandidate],
    preferences: ProactivePreferences,
    main_runtime: Mapping[str, Any] | None,
) -> tuple[SelectedTopic, ...]:
    """Use the configured auxiliary/main model and validate its selected IDs."""

    from honeyos.agent.auxiliary_client import async_call_llm
    from honeyos.companion.distillation import _main_runtime_from_config

    runtime = _main_runtime_from_config()
    runtime.update(dict(main_runtime or {}))
    provider = str(runtime.get("provider") or "").strip()
    model = str(runtime.get("model") or "").strip()
    if not provider or not model:
        return ()
    call_overrides: dict[str, Any] = {"provider": provider, "model": model}
    for key in ("base_url", "api_key"):
        value = runtime.get(key)
        if callable(value) or (isinstance(value, str) and value.strip()):
            call_overrides[key] = value
    candidate_payload = [
        {
            "candidate_id": item.raw.id,
            "title": item.raw.title,
            "source": item.raw.source_name,
            "url": item.raw.url,
            "description": item.raw.description,
            "verified_excerpt": item.excerpt[:1600],
            "category": item.raw.category,
        }
        for item in candidates[:MAX_VERIFIED_CANDIDATES]
    ]
    response = await async_call_llm(
        task="topic_pool_filter",
        messages=[
            {"role": "system", "content": _FILTER_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "focus_categories": preferences.focus_categories,
                        "blocked_categories": preferences.blocked_categories,
                        "candidates": candidate_payload,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
        temperature=0,
        max_tokens=1000,
        main_runtime=runtime,
        **call_overrides,
    )
    content = str(response.choices[0].message.content or "")
    return parse_filter_response(
        content, allowed_ids={item.raw.id for item in candidates}
    )


class TopicScout:
    """Collect at most one small, verified Topic Pool batch per due window."""

    def __init__(
        self,
        home: Path,
        *,
        store: TopicPoolStore | None = None,
        search_fn: SearchFn = default_web_search,
        fetch_fn: FetchFn = default_fetch_source,
        filter_fn: FilterFn = filter_with_auxiliary_model,
        now_fn: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.home = Path(home).expanduser().resolve()
        self.now_fn = now_fn
        self.store = store or TopicPoolStore(self.home, now_fn=now_fn)
        self.search_fn = search_fn
        self.fetch_fn = fetch_fn
        self.filter_fn = filter_fn

    @staticmethod
    def _directions(preferences: ProactivePreferences) -> tuple[str, ...]:
        focus = tuple(item for item in preferences.focus_categories if item.strip())
        chosen = focus[:3] if focus else DEFAULT_DIRECTIONS
        if len(chosen) < 3:
            chosen = chosen + tuple(
                item for item in DEFAULT_DIRECTIONS if item not in chosen
            )[: 3 - len(chosen)]
        return tuple(chosen[:3])

    async def collect_if_due(
        self,
        *,
        now: datetime | None = None,
        main_runtime: Mapping[str, Any] | None = None,
    ) -> CollectionResult:
        preferences = self.store.preferences()
        if not preferences.consented:
            return CollectionResult(skipped_reason="not_consented")
        current = now or self.now_fn()
        if not self.store.collection_due(hours=6, now=current):
            return CollectionResult(skipped_reason="not_due")
        try:
            return await self.collect_once(main_runtime=main_runtime)
        finally:
            self.store.mark_collection(at=current)

    async def collect_once(
        self, *, main_runtime: Mapping[str, Any] | None = None
    ) -> CollectionResult:
        preferences = self.store.preferences()
        raw_items: list[RawCandidate] = []
        seen_urls: set[str] = set()
        for direction in self._directions(preferences):
            query = f"{direction} latest news past 24 hours"
            try:
                found = await self.search_fn(query, 10)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Topic Scout search failed for %s: %s", direction, exc)
                continue
            for item in found:
                if len(raw_items) >= MAX_RAW_CANDIDATES:
                    break
                try:
                    normalized = normalize_source_url(item.url)
                except ValueError:
                    continue
                if normalized in seen_urls:
                    continue
                if item.category in preferences.blocked_categories:
                    continue
                seen_urls.add(normalized)
                raw_items.append(item)

        verified: list[VerifiedCandidate] = []
        for item in raw_items:
            if len(verified) >= MAX_VERIFIED_CANDIDATES:
                break
            try:
                result = await self.fetch_fn(item)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Topic Scout fetch callback failed for %s: %s", item.url, exc)
                continue
            if result is not None and result.excerpt.strip():
                verified.append(result)

        if not verified:
            return CollectionResult(raw_count=len(raw_items), verified_count=0)
        try:
            selected = await self.filter_fn(verified, preferences, main_runtime)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Topic Scout filter failed; dropping this round: %s", exc)
            return CollectionResult(
                raw_count=len(raw_items), verified_count=len(verified)
            )

        verified_by_id = {item.raw.id: item for item in verified}
        now = self.now_fn()
        candidates: list[TopicCandidate] = []
        for choice in selected[:MAX_ACCEPTED]:
            verified_item = verified_by_id.get(choice.candidate_id)
            if verified_item is None:
                continue
            raw = verified_item.raw
            candidates.append(
                TopicCandidate(
                    source_id=raw.source_id,
                    source_title=raw.title,
                    source_url=raw.url,
                    source_name=raw.source_name,
                    summary=(raw.description or verified_item.excerpt)[:2000],
                    hook=choice.hook,
                    category=choice.category or raw.category,
                    language="zh",
                    observed_at=now,
                    published_at=raw.published_at,
                    expires_at=now + timedelta(hours=48),
                    score=choice.score,
                    selection_reason=choice.reason,
                )
            )
        accepted = self.store.add_candidates(candidates)
        return CollectionResult(
            accepted=accepted,
            raw_count=len(raw_items),
            verified_count=len(verified),
        )

