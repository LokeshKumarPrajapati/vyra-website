"""
Real-Time Information Pipeline — Phase 7.3
============================================
Always-running monitor that tracks topics the user cares about.
Delivers alerts or daily digests without being asked.

Sources:
  - DuckDuckGo news search (no API key needed)
  - arXiv API (research papers)
  - GitHub trending (tech users)
  - Custom RSS feeds

Interest profile is built from WorldModel + episodic memory tags.
New items are stored as episodes and optionally surfaced as voice notifications.
"""

import asyncio
import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable, Dict, List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:
    _AIOHTTP = False

POLL_INTERVAL_MINUTES = 60    # check sources every hour
MAX_ITEMS_PER_SOURCE  = 5

@dataclass
class NewsItem:
    title: str
    url: str
    summary: str
    source: str
    published: str
    relevance: float = 0.5    # 0-1 based on user interest match
    tags: List[str]  = field(default_factory=list)

@dataclass
class PipelineDigest:
    generated_at: str
    items: List[NewsItem]
    topics_covered: List[str]
    total_sources_checked: int


class RealtimePipeline:

    def __init__(self):
        self._running      = False
        self._notify: Optional[Callable[[str], Awaitable[None]]] = None
        self._interest_topics: List[str] = []
        self._seen_urls: set = set()
        self._digest_items: List[NewsItem] = []

    def set_notify_callback(self, cb: Callable[[str], Awaitable[None]]):
        self._notify = cb

    def set_interests(self, topics: List[str]):
        self._interest_topics = topics

    def _load_interests(self) -> List[str]:
        """Load from WorldModel + recent episode tags."""
        topics = list(self._interest_topics)
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm = get_world_model()
            topics.extend(wm.profile.technical_stack[:5])
            topics.extend(list(wm.knowledge.keys())[:5])
        except Exception:
            pass
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            eps  = get_episodic_memory().recent(n=30)
            tags = [t for ep in eps for t in ep.tags]
            from collections import Counter
            topics.extend([t for t, _ in Counter(tags).most_common(5)])
        except Exception:
            pass
        # Deduplicate
        seen = set()
        result = []
        for t in topics:
            if t and t.lower() not in seen:
                seen.add(t.lower())
                result.append(t)
        return result[:10]

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[RealtimePipeline] Started.")
        while self._running:
            await asyncio.sleep(POLL_INTERVAL_MINUTES * 60)
            await self._cycle()

    async def _cycle(self):
        interests = self._load_interests()
        if not interests:
            return
        print(f"[Pipeline] Checking: {interests[:3]}...")
        items = []
        for topic in interests[:5]:   # limit to top 5
            new_items = await self._fetch_ddg_news(topic)
            items.extend(new_items)

        # Filter seen
        fresh = [i for i in items if i.url not in self._seen_urls]
        for i in fresh:
            self._seen_urls.add(i.url)

        # Store as episodes
        for item in fresh[:MAX_ITEMS_PER_SOURCE]:
            await self._store_item(item)
            self._digest_items.append(item)

        # Alert for high-relevance items
        urgent = [i for i in fresh if i.relevance > 0.85]
        for item in urgent[:2]:
            await self._alert(item)

        print(f"[Pipeline] Found {len(fresh)} new items.")

    # ── Sources ───────────────────────────────────────────────────────────────

    async def _fetch_ddg_news(self, topic: str) -> List[NewsItem]:
        if not _AIOHTTP:
            return []
        url = f"https://duckduckgo.com/news.js?q={topic.replace(' ', '+')}&o=json&kl=us-en"
        headers = {"User-Agent": "Mozilla/5.0 VYRA Research Pipeline"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json(content_type=None)
            items = []
            for art in (data.get("results") or [])[:MAX_ITEMS_PER_SOURCE]:
                item = NewsItem(
                    title    = art.get("title", ""),
                    url      = art.get("url", ""),
                    summary  = art.get("excerpt", ""),
                    source   = art.get("source", ""),
                    published= art.get("date", datetime.utcnow().isoformat()),
                    relevance= self._score_relevance(art.get("title", ""), topic),
                    tags     = [topic],
                )
                if item.title and item.url:
                    items.append(item)
            return items
        except Exception:
            return []

    async def _fetch_arxiv(self, topic: str) -> List[NewsItem]:
        if not _AIOHTTP:
            return []
        url = f"http://export.arxiv.org/api/query?search_query=all:{topic}&max_results=5&sortBy=submittedDate"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    text = await resp.text()
            root  = ET.fromstring(text)
            ns    = {"atom": "http://www.w3.org/2005/Atom"}
            items = []
            for entry in root.findall("atom:entry", ns):
                title   = (entry.find("atom:title", ns)   or ET.Element("x")).text or ""
                summary = (entry.find("atom:summary", ns) or ET.Element("x")).text or ""
                link_el = entry.find("atom:id", ns)
                url_str = link_el.text if link_el is not None else ""
                items.append(NewsItem(
                    title=title.strip(), url=url_str,
                    summary=summary.strip()[:400],
                    source="arXiv", published=datetime.utcnow().isoformat(),
                    relevance=0.8, tags=[topic, "research", "arxiv"],
                ))
            return items
        except Exception:
            return []

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _score_relevance(self, title: str, topic: str) -> float:
        interests = self._load_interests()
        title_lower = title.lower()
        matches = sum(1 for t in interests if t.lower() in title_lower)
        base    = 0.5 if topic.lower() in title_lower else 0.3
        return min(1.0, base + matches * 0.1)

    async def _store_item(self, item: NewsItem):
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            await mem.record(
                content  = f"{item.title}\n{item.summary}",
                source   = "research",
                context  = f"From {item.source} — {item.url}",
                manual_importance = item.relevance * 0.6,
            )
        except Exception:
            pass

    async def _alert(self, item: NewsItem):
        if self._notify:
            msg = f"Breaking news I think you'll care about: {item.title}. Want details?"
            try:
                await self._notify(msg)
            except Exception:
                pass

    def get_digest(self, last_n: int = 10) -> PipelineDigest:
        items = self._digest_items[-last_n:]
        topics = list({t for i in items for t in i.tags})
        return PipelineDigest(
            generated_at         = datetime.utcnow().isoformat(),
            items                = items,
            topics_covered       = topics,
            total_sources_checked= len(self._seen_urls),
        )

    def stop(self):
        self._running = False


_pipeline: Optional[RealtimePipeline] = None

def get_pipeline() -> RealtimePipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = RealtimePipeline()
    return _pipeline
