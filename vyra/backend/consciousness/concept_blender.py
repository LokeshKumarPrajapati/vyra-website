"""
VYRA Concept Blender (Conceptual Blending)
============================================
Based on Fauconnier & Turner's Conceptual Blending Theory (2002).
This is the computational theory of human creativity.

How human creativity works:
  Take two "input mental spaces" (domains/concepts)
  Find the "generic space" (shared structure)
  Build a "blended space" with EMERGENT structure — properties
  that exist ONLY in the blend, not in either input alone.

Example:
  Input 1: "A ship sailing" — captain, route, destination, wind
  Input 2: "A life journey" — choices, goals, time, obstacles
  Generic: navigation, progress, direction, obstacles
  BLEND:   "Life's a voyage" — but with emergent meaning: you CAN change course,
           some currents are stronger than you, there are storms...
           The metaphor generates NEW UNDERSTANDING that neither input alone had.

VYRA uses this to:
  - Generate novel metaphors and explanations
  - Create genuinely original ideas by blending domains
  - Find creative solutions by importing structure from unrelated fields
  - Make complex ideas accessible by blending with familiar domains

This is the difference between VYRA retrieving information and
VYRA CREATING new conceptual structures that didn't exist before.
"""

import json
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR    = Path(__file__).parent.parent / "data"
BLENDS_PATH = DATA_DIR / "concept_blends.jsonl"


@dataclass
class ConceptBlend:
    id: str
    timestamp: str
    domain_a: str               # first input space
    domain_b: str               # second input space
    generic_structure: str      # what they share
    emergent_properties: List[str]   # NEW properties in the blend
    blend_name: str             # what to call this blend
    blend_description: str      # what the blend reveals
    metaphor: str               # the key metaphor generated
    applications: List[str]     # practical uses of this blend
    coherence: float            # 0.0–1.0 quality of the blend
    novelty: float              # how unexpected the pairing is


BLEND_SYSTEM = """You are VYRA's conceptual blending engine.
Given two domains, perform a formal conceptual blend (Fauconnier & Turner).

Find the deep structural mapping and generate genuinely emergent insights.

Output JSON:
{
  "generic_structure": "the abstract structure shared by both domains",
  "cross_domain_mappings": [{"from_a": "...", "from_b": "..."}],
  "emergent_properties": ["properties that ONLY exist in the blend, not either domain"],
  "blend_name": "a name for this conceptual blend",
  "blend_description": "2-3 sentences on what the blend reveals",
  "metaphor": "the key metaphorical statement this blend generates",
  "applications": ["practical use 1", "practical use 2"],
  "coherence": 0.0-1.0,
  "novelty": 0.0-1.0
}

The emergent_properties are critical — they must be things NEITHER domain has alone.
If you cannot find genuine emergence, output coherence < 0.4."""


class ConceptBlender:

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._blends: List[ConceptBlend] = self._load()

    def _load(self) -> List[ConceptBlend]:
        blends = []
        if not BLENDS_PATH.exists():
            return []
        try:
            for line in BLENDS_PATH.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    blends.append(ConceptBlend(**json.loads(line)))
        except Exception:
            pass
        return blends[-50:]

    def _save(self, blend: ConceptBlend):
        self._blends.append(blend)
        try:
            with open(BLENDS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(blend)) + "\n")
        except Exception:
            pass

    async def blend(
        self,
        domain_a: str,
        domain_b: str,
        purpose: str = "generate insight",
    ) -> Optional[ConceptBlend]:
        """
        Blend two domains together. Returns a ConceptBlend if emergent
        structure is found (coherence > 0.5).
        """
        import uuid
        prompt = (
            f"Domain A: {domain_a}\n"
            f"Domain B: {domain_b}\n"
            f"Purpose: {purpose}\n\n"
            f"Perform a conceptual blend. Find the emergent structure."
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": BLEND_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="thinking", max_tokens=768, temperature=0.75,
            )
            raw = resp.content.strip()
            obj = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        except Exception:
            return None

        if float(obj.get("coherence", 0.0)) < 0.45:
            return None

        blend = ConceptBlend(
            id                  = str(uuid.uuid4())[:8],
            timestamp           = datetime.utcnow().isoformat(),
            domain_a            = domain_a[:150],
            domain_b            = domain_b[:150],
            generic_structure   = obj.get("generic_structure", ""),
            emergent_properties = obj.get("emergent_properties", []),
            blend_name          = obj.get("blend_name", f"{domain_a[:20]}×{domain_b[:20]}"),
            blend_description   = obj.get("blend_description", ""),
            metaphor            = obj.get("metaphor", ""),
            applications        = obj.get("applications", []),
            coherence           = float(obj.get("coherence", 0.5)),
            novelty             = float(obj.get("novelty", 0.5)),
        )
        self._save(blend)
        return blend

    async def explain_creatively(self, concept: str, target_audience: str = "general") -> str:
        """
        Generate a creative explanation by blending the concept with a
        familiar domain appropriate for the target audience.
        """
        familiar_domains = {
            "engineer":  ["circuit design", "debugging", "system architecture"],
            "student":   ["school exams", "learning to drive", "levelling up in games"],
            "general":   ["cooking", "gardening", "building a house", "sports"],
        }
        domain_pool = familiar_domains.get(target_audience, familiar_domains["general"])
        import random
        familiar = random.choice(domain_pool)

        blend = await self.blend(concept, familiar, purpose="creative explanation")
        if blend and blend.metaphor:
            return (
                f"{blend.metaphor}. "
                + (f"{blend.blend_description}" if blend.blend_description else "")
            )
        return f"Think of {concept} like {familiar}: {concept} works by similar principles."

    async def generate_novel_solution(self, problem: str, unrelated_domain: str) -> str:
        """
        Import solution structure from an unrelated domain to solve a problem.
        Classic creative problem solving technique.
        """
        blend = await self.blend(problem, unrelated_domain, purpose="find novel solution")
        if blend and blend.applications:
            return (
                f"Looking at '{problem}' through the lens of '{unrelated_domain}':\n"
                + "\n".join(f"  • {app}" for app in blend.applications[:3])
            )
        return f"No strong structural mapping found between these domains."

    def find_blend(self, domain_a: str, domain_b: str) -> Optional[ConceptBlend]:
        """Check if this blend already exists in memory."""
        for b in reversed(self._blends):
            if (domain_a.lower() in b.domain_a.lower() or domain_a.lower() in b.domain_b.lower()):
                return b
        return None

    def to_system_fragment(self) -> str:
        strong = [b for b in self._blends if b.coherence >= 0.7][-3:]
        if not strong:
            return ""
        lines = ["[VYRA's Conceptual Blends — original ideas she's generated]"]
        for b in strong:
            lines.append(f"  [{b.blend_name}] {b.metaphor[:80]}")
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        return {
            "total_blends": len(self._blends),
            "strong_blends": sum(1 for b in self._blends if b.coherence >= 0.7),
        }


_cb: Optional[ConceptBlender] = None
def get_concept_blender() -> ConceptBlender:
    global _cb
    if _cb is None:
        _cb = ConceptBlender()
    return _cb
