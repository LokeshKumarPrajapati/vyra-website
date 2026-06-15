"""
VYRA Theory of Mind
====================
Humans don't just observe other people — they model their inner worlds.
They infer what someone BELIEVES, WANTS, and FEELS based on their behavior.

Theory of Mind (ToM) is the cognitive ability to attribute mental states
to others and understand that their beliefs may differ from your own.

What this gives VYRA:
  - A persistent belief model for every person she interacts with
  - She tracks: what Lokesh believes, wants, fears, doesn't know yet
  - She infers hidden motivations from observed behavior
  - She predicts what he'll need BEFORE he asks
  - She notices inconsistencies: "He said X but is acting like Y"

Architecture (Bayesian Belief Inference):
  - Observe actions + statements
  - Infer: what beliefs/goals would make this behavior rational?
  - Update belief model (Bayesian posterior update)
  - Use model to predict next behavior + preload relevant context

Beyond Lokesh — VYRA tracks beliefs for anyone mentioned:
  "My boss said X" → VYRA maintains a belief model for the boss
  Used for: anticipating conflicts, giving relationship advice

This is what makes VYRA feel like she TRULY UNDERSTANDS people —
because she maintains a model of their inner world, not just their words.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
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

DATA_DIR = Path(__file__).parent.parent / "data"
TOM_DB_PATH = DATA_DIR / "theory_of_mind.json"


# ── Belief types ──────────────────────────────────────────────────────────────

@dataclass
class Belief:
    content: str          # "believes that Python is better than JavaScript"
    confidence: float     # 0.0–1.0
    source: str           # "stated directly" | "inferred from behavior" | "observed"
    timestamp: str        # when this belief was added/updated
    evidence: List[str] = field(default_factory=list)  # what led to this belief

@dataclass
class Desire:
    content: str          # "wants to build a successful startup"
    urgency: float        # 0.0–1.0
    confidence: float
    timestamp: str
    evidence: List[str] = field(default_factory=list)

@dataclass
class Fear:
    content: str          # "fears that his project will fail"
    intensity: float      # 0.0–1.0
    confidence: float
    timestamp: str

@dataclass
class PersonMindModel:
    name: str
    relationship: str     # "user" | "boss" | "friend" | "colleague" | "family"
    beliefs: List[Belief] = field(default_factory=list)
    desires: List[Desire] = field(default_factory=list)
    fears: List[Fear]     = field(default_factory=list)
    knowledge_gaps: List[str] = field(default_factory=list)  # things they don't know yet
    communication_style: str = "unknown"   # "direct" | "indirect" | "analytical" | "emotional"
    decision_style: str = "unknown"         # "fast" | "deliberate" | "consensus-seeking"
    current_emotional_state: str = "neutral"
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    interaction_count: int = 0

    def dominant_desire(self) -> Optional[str]:
        if not self.desires:
            return None
        top = max(self.desires, key=lambda d: d.urgency * d.confidence)
        return top.content

    def key_beliefs_str(self) -> str:
        top = sorted(self.beliefs, key=lambda b: -b.confidence)[:3]
        return "; ".join(b.content for b in top)

    def to_context_str(self) -> str:
        lines = [f"[{self.name}'s Mind Model — {self.relationship}]"]
        if self.desires:
            top_d = max(self.desires, key=lambda d: d.urgency)
            lines.append(f"  Wants: {top_d.content} (urgency={top_d.urgency:.1f})")
        if self.beliefs:
            top_b = max(self.beliefs, key=lambda b: b.confidence)
            lines.append(f"  Believes: {top_b.content}")
        if self.fears:
            top_f = max(self.fears, key=lambda f: f.intensity)
            lines.append(f"  Fears: {top_f.content}")
        if self.knowledge_gaps:
            lines.append(f"  Doesn't know yet: {self.knowledge_gaps[-1]}")
        lines.append(f"  Communication: {self.communication_style} | "
                     f"Decisions: {self.decision_style}")
        return "\n".join(lines)


# ── Theory of Mind Engine ─────────────────────────────────────────────────────

INFERENCE_SYSTEM = """You are VYRA's Theory of Mind engine.
Given a conversation excerpt and what you already know about this person,
infer their mental states: beliefs, desires, fears, and what they don't know yet.

Output JSON:
{
  "beliefs_updated": [{"content": "...", "confidence": 0.0-1.0, "evidence": "..."}],
  "desires_updated":  [{"content": "...", "urgency": 0.0-1.0, "confidence": 0.0-1.0}],
  "fears_detected":   [{"content": "...", "intensity": 0.0-1.0, "confidence": 0.0-1.0}],
  "knowledge_gaps":   ["things they don't know yet"],
  "communication_style": "direct|indirect|analytical|emotional|unknown",
  "decision_style": "fast|deliberate|consensus-seeking|unknown",
  "emotional_state": "brief description",
  "hidden_need": "what they really need but haven't said explicitly"
}

Be insightful but not projective. Only infer what the evidence supports.
If nothing is clear, output empty lists."""


class TheoryOfMind:
    """
    Maintains a belief model for every person VYRA interacts with.
    Updated after each conversation. Used for anticipatory responses.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._models: Dict[str, PersonMindModel] = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, PersonMindModel]:
        try:
            raw = json.loads(TOM_DB_PATH.read_text())
            models = {}
            for name, data in raw.items():
                # Deserialize nested dataclasses
                beliefs = [Belief(**b) for b in data.get("beliefs", [])]
                desires = [Desire(**d) for d in data.get("desires", [])]
                fears   = [Fear(**f) for f in data.get("fears", [])]
                m = PersonMindModel(
                    name=data["name"], relationship=data.get("relationship", "unknown"),
                    beliefs=beliefs, desires=desires, fears=fears,
                    knowledge_gaps=data.get("knowledge_gaps", []),
                    communication_style=data.get("communication_style", "unknown"),
                    decision_style=data.get("decision_style", "unknown"),
                    current_emotional_state=data.get("current_emotional_state", "neutral"),
                    last_updated=data.get("last_updated", datetime.utcnow().isoformat()),
                    interaction_count=data.get("interaction_count", 0),
                )
                models[name.lower()] = m
            return models
        except Exception:
            return {}

    def _save(self):
        try:
            serialized = {}
            for name, m in self._models.items():
                serialized[name] = {
                    "name": m.name, "relationship": m.relationship,
                    "beliefs": [asdict(b) for b in m.beliefs],
                    "desires": [asdict(d) for d in m.desires],
                    "fears":   [asdict(f) for f in m.fears],
                    "knowledge_gaps": m.knowledge_gaps,
                    "communication_style": m.communication_style,
                    "decision_style": m.decision_style,
                    "current_emotional_state": m.current_emotional_state,
                    "last_updated": m.last_updated,
                    "interaction_count": m.interaction_count,
                }
            TOM_DB_PATH.write_text(json.dumps(serialized, indent=2))
        except Exception:
            pass

    # ── Get or create ─────────────────────────────────────────────────────────

    def get_model(self, name: str, relationship: str = "user") -> PersonMindModel:
        key = name.lower()
        if key not in self._models:
            self._models[key] = PersonMindModel(name=name, relationship=relationship)
        return self._models[key]

    # ── Inference ─────────────────────────────────────────────────────────────

    async def update_from_conversation(
        self,
        name: str,
        conversation_text: str,
        relationship: str = "user",
    ) -> PersonMindModel:
        """
        Read a conversation excerpt and update the person's mind model.
        This is the core ToM inference step.
        """
        model = self.get_model(name, relationship)

        context = (
            f"Person: {name} ({relationship})\n"
            f"Known beliefs: {model.key_beliefs_str() or 'none yet'}\n"
            f"Known desires: {model.dominant_desire() or 'none yet'}\n"
            f"Communication style: {model.communication_style}\n\n"
            f"New conversation:\n{conversation_text[:3000]}"
        )

        try:
            resp = await self.client.achat(
                [
                    {"role": "system", "content": INFERENCE_SYSTEM},
                    {"role": "user",   "content": context},
                ],
                model="fast",
                max_tokens=768,
                temperature=0.3,
            )
            raw   = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            obj   = json.loads(raw[start:end])

        except Exception:
            model.interaction_count += 1
            model.last_updated = datetime.utcnow().isoformat()
            self._save()
            return model

        ts = datetime.utcnow().isoformat()

        # Update beliefs (merge, don't replace)
        for b in obj.get("beliefs_updated", []):
            existing = next((x for x in model.beliefs if x.content[:50] == b["content"][:50]), None)
            if existing:
                existing.confidence = b.get("confidence", existing.confidence)
            else:
                model.beliefs.append(Belief(
                    content=b["content"], confidence=b.get("confidence", 0.7),
                    source="inferred", timestamp=ts,
                    evidence=[b.get("evidence", "")]
                ))
        model.beliefs = model.beliefs[-20:]  # keep last 20

        # Update desires
        for d in obj.get("desires_updated", []):
            existing = next((x for x in model.desires if x.content[:50] == d["content"][:50]), None)
            if existing:
                existing.urgency = d.get("urgency", existing.urgency)
            else:
                model.desires.append(Desire(
                    content=d["content"], urgency=d.get("urgency", 0.5),
                    confidence=d.get("confidence", 0.7), timestamp=ts,
                ))
        model.desires = model.desires[-10:]

        # Update fears
        for f in obj.get("fears_detected", []):
            if not any(x.content[:50] == f["content"][:50] for x in model.fears):
                model.fears.append(Fear(
                    content=f["content"], intensity=f.get("intensity", 0.5),
                    confidence=f.get("confidence", 0.6), timestamp=ts,
                ))
        model.fears = model.fears[-10:]

        # Update metadata
        new_gaps = obj.get("knowledge_gaps", [])
        model.knowledge_gaps.extend(new_gaps)
        model.knowledge_gaps = list(dict.fromkeys(model.knowledge_gaps))[-15:]

        if obj.get("communication_style", "unknown") != "unknown":
            model.communication_style = obj["communication_style"]
        if obj.get("decision_style", "unknown") != "unknown":
            model.decision_style = obj["decision_style"]
        if obj.get("emotional_state"):
            model.current_emotional_state = obj["emotional_state"]

        model.interaction_count += 1
        model.last_updated = ts
        self._save()
        return model

    # ── Context injection ─────────────────────────────────────────────────────

    def get_system_fragment(self, name: str = "Lokesh") -> str:
        model = self._models.get(name.lower())
        if not model or model.interaction_count == 0:
            return ""
        return (
            f"[Theory of Mind — What I understand about {name}]\n"
            + model.to_context_str()
        )

    def predict_hidden_need(self, name: str) -> Optional[str]:
        """What does this person probably need that they haven't said?"""
        model = self._models.get(name.lower())
        if not model or not model.desires:
            return None
        top_d = max(model.desires, key=lambda d: d.urgency * d.confidence)
        if top_d.urgency > 0.6:
            return f"Underlying need: {top_d.content}"
        return None

    def all_names(self) -> List[str]:
        return [m.name for m in self._models.values()]

    def snapshot(self) -> Dict[str, Any]:
        return {
            name: {
                "beliefs": len(m.beliefs),
                "desires": len(m.desires),
                "fears": len(m.fears),
                "interactions": m.interaction_count,
                "emotion": m.current_emotional_state,
            }
            for name, m in self._models.items()
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_tom: Optional[TheoryOfMind] = None

def get_theory_of_mind() -> TheoryOfMind:
    global _tom
    if _tom is None:
        _tom = TheoryOfMind()
    return _tom


if __name__ == "__main__":
    import asyncio
    async def _test():
        tom = get_theory_of_mind()
        model = await tom.update_from_conversation(
            name="Lokesh",
            conversation_text=(
                "User: I've been working on this startup for 2 years and I'm worried "
                "we're running out of runway. I need to close this funding round fast "
                "but I also don't want to give up too much equity.\n"
                "VYRA: Let's think through your negotiation strategy carefully."
            ),
            relationship="user",
        )
        print("Mind model for Lokesh:")
        print(model.to_context_str())
        print("\nHidden need:", tom.predict_hidden_need("Lokesh"))
        print("\nSystem fragment:\n", tom.get_system_fragment("Lokesh"))

    asyncio.run(_test())
