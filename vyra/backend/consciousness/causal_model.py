"""
VYRA Causal Reasoning Model
=============================
Humans don't just correlate — they understand WHY things happen.
Pearl's do-calculus: observation vs intervention vs counterfactual.

Three levels of causal reasoning (Pearl's Ladder):
  Level 1 — Association:    "X and Y tend to happen together"
  Level 2 — Intervention:   "If I DO X, what will happen to Y?"
  Level 3 — Counterfactual: "If X had NOT happened, would Y have occurred?"

VYRA builds a dynamic causal graph from conversations and observations.
Every claim gets a causal chain. Every decision is evaluated causally.

Capabilities:
  - Build causal chains: "A → B → C because..."
  - Run interventions: simulate "what if I do X?"
  - Generate counterfactuals: "what would have happened if...?"
  - Explain WHY something happened, not just WHAT
  - Detect spurious correlations vs real causes
  - Identify root causes of failures
"""

import json
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR   = Path(__file__).parent.parent / "data"
CAUSAL_PATH = DATA_DIR / "causal_graph.json"


@dataclass
class CausalNode:
    id: str
    description: str
    domain: str          # "user_behavior" | "world" | "system" | "goal"
    observed_count: int = 0
    last_seen: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class CausalEdge:
    cause_id: str
    effect_id: str
    mechanism: str       # explanation of HOW cause produces effect
    strength: float      # 0.0–1.0 causal strength
    confidence: float    # 0.0–1.0 how sure VYRA is
    evidence: List[str] = field(default_factory=list)
    interventional: bool = False   # True = tested by doing, False = observed

@dataclass
class CausalChain:
    nodes: List[str]          # ordered node IDs
    mechanisms: List[str]     # mechanism for each edge
    total_strength: float
    explanation: str           # natural language explanation


CAUSAL_SYSTEM = """You are VYRA's causal reasoning engine.
Given a situation, extract causal relationships as JSON:
{
  "nodes": [{"id": "slug_id", "description": "...", "domain": "user_behavior|world|system|goal"}],
  "edges": [{"cause_id": "...", "effect_id": "...", "mechanism": "why/how cause produces effect",
             "strength": 0.0-1.0, "confidence": 0.0-1.0}],
  "root_cause": "the deepest cause in this situation",
  "counterfactual": "what would have happened if the root cause had not occurred"
}
Focus on genuine causal mechanisms, not just correlations."""


class CausalModel:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._nodes: Dict[str, CausalNode] = {}
        self._edges: List[CausalEdge] = []
        self._load()

    def _load(self):
        try:
            raw = json.loads(CAUSAL_PATH.read_text())
            for nd in raw.get("nodes", []):
                self._nodes[nd["id"]] = CausalNode(**nd)
            for ed in raw.get("edges", []):
                self._edges.append(CausalEdge(**ed))
        except Exception:
            pass

    def _save(self):
        try:
            CAUSAL_PATH.write_text(json.dumps({
                "nodes": [asdict(n) for n in self._nodes.values()],
                "edges": [asdict(e) for e in self._edges],
            }, indent=2))
        except Exception:
            pass

    async def analyze(self, situation: str, context: str = "") -> Dict[str, Any]:
        """Extract causal structure from a described situation."""
        prompt = f"Situation:\n{situation}\n\nContext: {context or 'none'}"
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": CAUSAL_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="thinking", max_tokens=1024, temperature=0.3,
            )
            raw = resp.content.strip()
            obj = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        except Exception:
            return {"root_cause": "unknown", "counterfactual": "unknown", "nodes": [], "edges": []}

        ts = datetime.utcnow().isoformat()
        for nd in obj.get("nodes", []):
            nid = nd.get("id", "")
            if nid:
                if nid in self._nodes:
                    self._nodes[nid].observed_count += 1
                    self._nodes[nid].last_seen = ts
                else:
                    self._nodes[nid] = CausalNode(
                        id=nid, description=nd.get("description",""),
                        domain=nd.get("domain","world"), observed_count=1, last_seen=ts
                    )

        for ed in obj.get("edges", []):
            cid, eid = ed.get("cause_id",""), ed.get("effect_id","")
            if cid and eid:
                existing = next((e for e in self._edges if e.cause_id==cid and e.effect_id==eid), None)
                if existing:
                    existing.strength   = (existing.strength + ed.get("strength",0.5)) / 2
                    existing.confidence = min(1.0, existing.confidence + 0.05)
                else:
                    self._edges.append(CausalEdge(
                        cause_id=cid, effect_id=eid,
                        mechanism=ed.get("mechanism",""), strength=ed.get("strength",0.5),
                        confidence=ed.get("confidence",0.6),
                    ))
        self._save()
        return obj

    async def ask_why(self, event: str) -> str:
        """'Why did X happen?' — traces causal chain."""
        prompt = (
            f"Event: {event}\n"
            f"Known causal nodes: {[n.description for n in list(self._nodes.values())[:10]]}\n"
            f"Trace the causal chain backward. What is the root cause? "
            f"Explain WHY this happened step by step. Be specific."
        )
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="thinking", max_tokens=512, temperature=0.4,
        )
        return resp.content.strip()

    async def simulate_intervention(self, action: str, context: str = "") -> Dict[str, Any]:
        """'What will happen if I DO X?' — causal intervention simulation."""
        prompt = (
            f"Proposed action (intervention): {action}\n"
            f"Context: {context or 'current situation'}\n"
            f"Known causal graph nodes: {[n.description for n in list(self._nodes.values())[:8]]}\n\n"
            f"Simulate: what causal chain does this action set in motion? "
            f"What are the direct effects? Second-order effects? Unintended consequences? "
            f"What is the probability of success? "
            f"Output JSON: {{\"direct_effects\": [], \"second_order\": [], \"risks\": [], \"success_probability\": 0.0-1.0, \"reasoning\": \"...\"}}"
        )
        try:
            resp = await self.client.achat(
                [{"role": "user", "content": prompt}],
                model="thinking", max_tokens=768, temperature=0.4,
            )
            raw = resp.content.strip()
            return json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        except Exception:
            return {"direct_effects": [], "second_order": [], "risks": [], "success_probability": 0.5}

    async def counterfactual(self, event: str, alternate_cause: str) -> str:
        """'What would have happened if X had not occurred / if Y had happened instead?'"""
        prompt = (
            f"What actually happened: {event}\n"
            f"Alternate scenario: {alternate_cause}\n\n"
            f"Generate a careful counterfactual analysis. "
            f"What would have been different? What would have stayed the same? Why?"
        )
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="thinking", max_tokens=512, temperature=0.5,
        )
        return resp.content.strip()

    def find_root_causes(self, effect_id: str) -> List[str]:
        """Trace back through graph to find root causes of an effect."""
        roots = []
        visited = set()
        def _trace(nid):
            if nid in visited:
                return
            visited.add(nid)
            parents = [e.cause_id for e in self._edges if e.effect_id == nid]
            if not parents:
                roots.append(nid)
            else:
                for p in parents:
                    _trace(p)
        _trace(effect_id)
        return roots

    def to_system_fragment(self) -> str:
        if not self._nodes:
            return ""
        recent = sorted(self._nodes.values(), key=lambda n: -n.observed_count)[:5]
        lines = ["[VYRA's Causal Model — patterns of cause and effect I've identified]"]
        for n in recent:
            effects = [e for e in self._edges if e.cause_id == n.id]
            if effects:
                top = max(effects, key=lambda e: e.strength)
                eff_node = self._nodes.get(top.effect_id)
                if eff_node:
                    lines.append(f"  {n.description} → {eff_node.description} (strength={top.strength:.2f})")
        return "\n".join(lines)

    def stats(self) -> dict:
        return {"nodes": len(self._nodes), "edges": len(self._edges)}


_cm: Optional[CausalModel] = None
def get_causal_model() -> CausalModel:
    global _cm
    if _cm is None:
        _cm = CausalModel()
    return _cm
