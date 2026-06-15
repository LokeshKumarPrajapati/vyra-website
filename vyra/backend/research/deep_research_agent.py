"""
Deep Research Agent — Phase 7.1
==================================
Multi-source research synthesis engine. Not just a browser — a researcher.

Process:
  1. Query expansion  → generate 4-6 search variants for better coverage
  2. Parallel search  → run all queries simultaneously via web_agent or DuckDuckGo
  3. Source filtering → rank sources by credibility
  4. Fact extraction  → extract key claims + evidence per source
  5. Cross-reference  → verify claims across sources, flag contradictions
  6. Synthesis        → unified answer with confidence scores and citations
  7. Memory storage   → save research as an Episode for future recall

Usage:
    agent  = get_research_agent()
    report = await agent.research("What caused the 2025 AI chip shortage?")
    print(report.synthesis)
    print(report.sources)
    print(report.confidence)
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

# Optional: use existing web_agent for actual web searches
_WEB_AGENT = None
def _get_web_agent():
    global _WEB_AGENT
    if _WEB_AGENT is None:
        try:
            from web_agent import WebAgent  # type: ignore
            _WEB_AGENT = WebAgent()
        except Exception:
            pass
    return _WEB_AGENT


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Source:
    url: str
    title: str
    snippet: str
    credibility: float = 0.7     # 0-1
    claims: List[str] = field(default_factory=list)

@dataclass
class ResearchReport:
    topic: str
    synthesis: str               # final unified answer
    key_facts: List[str]         # bullet-point key findings
    sources: List[Source]
    contradictions: List[str]    # conflicting claims found
    confidence: float            # 0-1 overall confidence
    gaps: List[str]              # what couldn't be found
    generated_at: str
    latency_ms: float
    queries_run: List[str]


# ── Agent ─────────────────────────────────────────────────────────────────────

EXPAND_SYSTEM = """You generate diverse search queries to comprehensively research a topic.
Vary phrasing, include different angles (technical, historical, current, critical).
Output a JSON array of strings only."""

EXTRACT_SYSTEM = """You extract structured information from a web page snippet.
Output JSON: {"claims": ["claim1", "claim2"], "credibility": 0.8}
Credibility: 1.0=major academic/news, 0.8=reputable site, 0.5=blog, 0.3=unknown."""

SYNTH_SYSTEM = """You are a research synthesis specialist.
Given multiple sources and extracted claims, produce a comprehensive, accurate,
well-structured answer. Always note uncertainty. Cite source numbers like [1], [2].
Flag contradictions. Be thorough but readable."""

class DeepResearchAgent:

    def __init__(self, max_sources: int = 8):
        self.client      = get_nvidia_client()
        self.max_sources = max_sources

    async def research(
        self,
        topic: str,
        context: str = "",
        depth: str = "standard",   # "quick" | "standard" | "deep"
    ) -> ResearchReport:
        t0     = time.time()
        n_queries = {"quick": 2, "standard": 4, "deep": 6}.get(depth, 4)

        # 1. Expand queries
        queries = await self._expand_queries(topic, n_queries)

        # 2. Search (parallel)
        search_results = await asyncio.gather(*[
            self._search(q) for q in queries
        ])
        all_sources: List[Source] = []
        for results in search_results:
            all_sources.extend(results)

        # Deduplicate by URL
        seen_urls = set()
        unique_sources = []
        for s in all_sources:
            if s.url not in seen_urls:
                seen_urls.add(s.url)
                unique_sources.append(s)

        # Top sources by credibility
        unique_sources.sort(key=lambda s: s.credibility, reverse=True)
        top_sources = unique_sources[:self.max_sources]

        # 3. Extract claims from each source (parallel)
        top_sources = list(await asyncio.gather(*[
            self._extract_claims(s) for s in top_sources
        ]))

        # 4. Cross-reference and find contradictions
        contradictions = await self._find_contradictions(top_sources)

        # 5. Synthesise
        synthesis, key_facts, confidence, gaps = await self._synthesise(
            topic, top_sources, contradictions, context
        )

        report = ResearchReport(
            topic          = topic,
            synthesis      = synthesis,
            key_facts      = key_facts,
            sources        = top_sources,
            contradictions = contradictions,
            confidence     = confidence,
            gaps           = gaps,
            generated_at   = datetime.utcnow().isoformat(),
            latency_ms     = (time.time() - t0) * 1000,
            queries_run    = queries,
        )

        # 6. Store as episode for future recall
        asyncio.create_task(self._store_episode(report))

        return report

    # ── Query expansion ───────────────────────────────────────────────────────

    async def _expand_queries(self, topic: str, n: int) -> List[str]:
        prompt = (
            f"Research topic: {topic}\n"
            f"Generate exactly {n} diverse search queries to research this comprehensively.\n"
            f"Include different angles. JSON array of strings only."
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": EXPAND_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="fast",
                max_tokens=256,
                temperature=0.7,
            )
            raw   = resp.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            queries = json.loads(raw[start:end])
            return [str(q) for q in queries[:n]]
        except Exception:
            return [topic]

    # ── Search ────────────────────────────────────────────────────────────────

    async def _search(self, query: str) -> List[Source]:
        """Try web_agent first, fall back to LLM knowledge."""
        web = _get_web_agent()
        if web:
            try:
                results = await asyncio.to_thread(web.search, query, max_results=3)
                return [
                    Source(
                        url=r.get("url", ""),
                        title=r.get("title", ""),
                        snippet=r.get("snippet", ""),
                    )
                    for r in (results or [])
                    if r.get("snippet")
                ]
            except Exception:
                pass
        # Fallback: LLM knowledge as "source"
        resp = await self.client.achat(
            [{"role": "user", "content": f"Provide factual information about: {query}. "
              "Include specific facts, data points, and examples."}],
            model="thinking",
            max_tokens=1024,
        )
        return [Source(
            url="llm_knowledge", title=f"VYRA Knowledge: {query[:50]}",
            snippet=resp.content, credibility=0.6,
        )]

    # ── Claim extraction ──────────────────────────────────────────────────────

    async def _extract_claims(self, source: Source) -> Source:
        prompt = f"Source: {source.title}\nContent: {source.snippet[:1500]}"
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": EXTRACT_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="fast",
                max_tokens=256,
                temperature=0.1,
            )
            raw   = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            d     = json.loads(raw[start:end])
            source.claims      = d.get("claims", [])
            source.credibility = float(d.get("credibility", 0.7))
        except Exception:
            pass
        return source

    # ── Contradiction detection ───────────────────────────────────────────────

    async def _find_contradictions(self, sources: List[Source]) -> List[str]:
        if len(sources) < 2:
            return []
        all_claims = []
        for i, s in enumerate(sources):
            for c in s.claims:
                all_claims.append(f"[Source {i+1}] {c}")
        if not all_claims:
            return []
        prompt = (
            f"Claims from multiple sources:\n"
            + "\n".join(all_claims[:30])
            + "\n\nIdentify any contradictions between these claims. "
            "List each contradiction as one sentence. JSON array of strings, or [] if none."
        )
        try:
            resp = await self.client.achat(
                [{"role": "user", "content": prompt}],
                model="fast",
                max_tokens=256,
                temperature=0.2,
            )
            raw   = resp.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            return json.loads(raw[start:end])
        except Exception:
            return []

    # ── Synthesis ─────────────────────────────────────────────────────────────

    async def _synthesise(
        self,
        topic: str,
        sources: List[Source],
        contradictions: List[str],
        context: str,
    ) -> Tuple[str, List[str], float, List[str]]:
        source_block = "\n\n".join(
            f"[{i+1}] {s.title} ({s.url})\n"
            f"Credibility: {s.credibility:.1f}\n"
            f"Claims: {'; '.join(s.claims[:5])}\n"
            f"Content: {s.snippet[:600]}"
            for i, s in enumerate(sources)
        )
        prompt = (
            f"Research topic: {topic}\n"
            f"User context: {context or 'none'}\n\n"
            f"Sources:\n{source_block}\n\n"
            f"Contradictions found: {'; '.join(contradictions) or 'None'}\n\n"
            f"Produce a comprehensive research synthesis. "
            f"Also output: key_facts (list), confidence (0-1), gaps (list).\n"
            f"JSON format: {{"
            f'"synthesis":"...", "key_facts":["..."], "confidence":0.85, "gaps":["..."]}}'
        )
        try:
            resp = await self.client.athink(
                prompt=prompt, system=SYNTH_SYSTEM, max_tokens=8192,
            )
            raw   = resp.answer.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            d     = json.loads(raw[start:end])
            return (
                d.get("synthesis", raw),
                d.get("key_facts", []),
                float(d.get("confidence", 0.75)),
                d.get("gaps", []),
            )
        except Exception as e:
            # Return raw answer as synthesis
            try:
                resp2 = await self.client.achat(
                    [{"role": "system", "content": SYNTH_SYSTEM},
                     {"role": "user", "content": f"Topic: {topic}\n\nSources:\n{source_block}"}],
                    model="fast",
                    max_tokens=4096,
                )
                return resp2.content, [], 0.65, []
            except Exception:
                return f"Research on '{topic}' could not be completed.", [], 0.3, [str(e)]

    # ── Episode storage ───────────────────────────────────────────────────────

    async def _store_episode(self, report: ResearchReport):
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            await mem.record(
                content  = f"Research: {report.topic}\n\n{report.synthesis[:1000]}",
                source   = "research",
                context  = f"{len(report.sources)} sources, confidence {report.confidence:.2f}",
                manual_importance = 0.7,
            )
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_agent: Optional[DeepResearchAgent] = None

def get_research_agent() -> DeepResearchAgent:
    global _agent
    if _agent is None:
        _agent = DeepResearchAgent()
    return _agent


if __name__ == "__main__":
    async def _test():
        agent  = get_research_agent()
        report = await agent.research(
            "What are the key differences between Mamba and Transformer architectures in 2025?",
            depth="standard",
        )
        print(f"Sources: {len(report.sources)}")
        print(f"Confidence: {report.confidence:.2f}")
        print(f"Key facts: {report.key_facts[:3]}")
        print(f"Contradictions: {report.contradictions[:2]}")
        print(f"\n=== SYNTHESIS ===\n{report.synthesis[:800]}")

    asyncio.run(_test())
