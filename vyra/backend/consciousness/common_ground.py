"""
VYRA Common Ground Tracker
============================
Based on Grice's Cooperative Principle + Clark & Brennan's Common Ground Theory.

Communication works because both parties track shared knowledge.
When you explain something, you calibrate to what the OTHER person already knows.
You don't explain water to someone who's been swimming their whole life.
You don't assume shared jargon with someone who's new to a field.

Common Ground = the intersection of what BOTH parties know they both know.

VYRA tracks:
  1. LOKESH'S KNOWLEDGE MAP — what topics he knows well vs poorly
  2. ESTABLISHED CONTEXT — what's been agreed/stated this session
  3. PRESUPPOSITIONS — what VYRA can safely assume without explaining
  4. GAPS TO BRIDGE — what he needs explained before next step works
  5. VOCABULARY LEVEL — what terminology is safe to use

This makes VYRA's explanations:
  - Never condescending (over-explaining what he knows)
  - Never confusing (under-explaining what he doesn't)
  - Always calibrated to HIS level, not a generic level
  - Building on established context so she doesn't repeat herself

Update mechanism:
  - Signals of expertise: uses jargon correctly, asks advanced questions
  - Signals of novice: asks what a basic term means, misuses terminology
  - Each interaction updates knowledge scores per domain
  - Session context accumulates across the conversation
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR    = Path(__file__).parent.parent / "data"
GROUND_PATH = DATA_DIR / "common_ground.json"


@dataclass
class KnowledgeDomain:
    domain: str
    level: float          # 0.0 (novice) to 1.0 (expert)
    evidence_up: List[str] = field(default_factory=list)    # signals of expertise
    evidence_down: List[str] = field(default_factory=list)  # signals of gaps
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def update(self, signal: float, evidence: str = ""):
        """signal: +0.1 for expertise shown, -0.1 for gap shown."""
        self.level = max(0.0, min(1.0, self.level + signal))
        if signal > 0 and evidence:
            self.evidence_up.append(evidence)
            self.evidence_up = self.evidence_up[-5:]
        elif signal < 0 and evidence:
            self.evidence_down.append(evidence)
            self.evidence_down = self.evidence_down[-5:]
        self.last_updated = datetime.utcnow().isoformat()

    def explanation_depth(self) -> str:
        if self.level >= 0.8: return "expert"       # use jargon, skip basics
        if self.level >= 0.6: return "advanced"     # assume fundamentals
        if self.level >= 0.4: return "intermediate" # explain non-obvious concepts
        if self.level >= 0.2: return "beginner"     # explain most terms
        return "novice"                              # explain everything


@dataclass
class GroundedFact:
    content: str          # what's been established
    timestamp: str
    source: str           # "user_stated" | "agreed" | "inferred" | "vyra_stated"
    certainty: float      # 0.0–1.0


class CommonGround:
    """
    Tracks shared knowledge between VYRA and Lokesh.
    Updated every turn. Used to calibrate explanation depth.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._knowledge: Dict[str, KnowledgeDomain] = {}
        self._session_facts: List[GroundedFact] = []      # cleared per session
        self._persisted_facts: List[GroundedFact] = []    # persisted across sessions
        self._load()

    def _load(self):
        try:
            raw = json.loads(GROUND_PATH.read_text())
            for domain, data in raw.get("knowledge", {}).items():
                self._knowledge[domain] = KnowledgeDomain(**data)
            for f in raw.get("persisted_facts", []):
                self._persisted_facts.append(GroundedFact(**f))
            self._persisted_facts = self._persisted_facts[-100:]
        except Exception:
            pass

    def _save(self):
        try:
            GROUND_PATH.write_text(json.dumps({
                "knowledge": {k: asdict(v) for k, v in self._knowledge.items()},
                "persisted_facts": [asdict(f) for f in self._persisted_facts[-100:]],
            }, indent=2))
        except Exception:
            pass

    # ── Knowledge level tracking ──────────────────────────────────────────────

    def signal_expertise(self, domain: str, evidence: str = ""):
        """User demonstrated knowledge of this domain."""
        if domain not in self._knowledge:
            self._knowledge[domain] = KnowledgeDomain(domain=domain, level=0.5)
        self._knowledge[domain].update(+0.1, evidence)
        self._save()

    def signal_gap(self, domain: str, evidence: str = ""):
        """User showed a knowledge gap in this domain."""
        if domain not in self._knowledge:
            self._knowledge[domain] = KnowledgeDomain(domain=domain, level=0.5)
        self._knowledge[domain].update(-0.1, evidence)
        self._save()

    def set_level(self, domain: str, level: float):
        """Explicitly set knowledge level for a domain."""
        if domain not in self._knowledge:
            self._knowledge[domain] = KnowledgeDomain(domain=domain, level=level)
        else:
            self._knowledge[domain].level = max(0.0, min(1.0, level))
        self._save()

    def get_level(self, domain: str) -> float:
        return self._knowledge.get(domain, KnowledgeDomain(domain=domain, level=0.5)).level

    def explanation_depth(self, domain: str) -> str:
        kd = self._knowledge.get(domain)
        return kd.explanation_depth() if kd else "intermediate"

    # ── Session context tracking ──────────────────────────────────────────────

    def establish(self, fact: str, source: str = "agreed", certainty: float = 0.9):
        """Add something to the common ground (what we both know we know)."""
        gf = GroundedFact(
            content=fact[:200], timestamp=datetime.utcnow().isoformat(),
            source=source, certainty=certainty,
        )
        self._session_facts.append(gf)
        if certainty > 0.8:
            self._persisted_facts.append(gf)
            self._persisted_facts = self._persisted_facts[-100:]
        self._save()

    def is_established(self, topic: str) -> bool:
        """Check if a topic/fact is already in common ground."""
        tl = topic.lower()
        for f in self._session_facts + self._persisted_facts[-20:]:
            if tl in f.content.lower():
                return True
        return False

    def clear_session(self):
        """Called at end of session — session facts cleared, persisted remain."""
        self._session_facts.clear()

    # ── Adaptive explanation ──────────────────────────────────────────────────

    def calibration_instruction(self, domain: str) -> str:
        """Returns a system prompt fragment telling VYRA how to explain this domain."""
        depth = self.explanation_depth(domain)
        level = self.get_level(domain)
        instructions = {
            "expert":       f"Lokesh knows {domain} at expert level — use technical terms freely, skip fundamentals.",
            "advanced":     f"Lokesh is advanced in {domain} — explain only non-obvious concepts, not basics.",
            "intermediate": f"Lokesh has working knowledge of {domain} — briefly define jargon, explain nuances.",
            "beginner":     f"Lokesh is a beginner in {domain} — explain terms clearly, use analogies.",
            "novice":       f"Lokesh is new to {domain} — start from fundamentals, no jargon without explanation.",
        }
        return instructions.get(depth, f"Calibrate {domain} explanation to intermediate level.")

    def detect_from_message(self, message: str, domains_of_interest: Optional[List[str]] = None):
        """
        Heuristic: analyze a user message for knowledge signals.
        Updates common ground automatically.
        """
        msg = message.lower()
        # Expert signals: uses precise technical terms, asks nuanced questions
        expert_signals = {
            "python": ["asyncio", "decorator", "metaclass", "generator", "__dunder__", "gil"],
            "machine_learning": ["backprop", "gradient", "transformer", "attention head", "perplexity"],
            "finance": ["irr", "cap table", "vesting cliff", "liquidation preference", "arr"],
            "react": ["hooks", "reconciliation", "hydration", "fiber", "suspense"],
        }
        # Novice signals: asks "what is X", "how do I"
        novice_signals = ["what is", "what does", "i don't know", "i don't understand",
                          "can you explain", "i'm new to", "never used"]

        for domain, terms in expert_signals.items():
            if domains_of_interest and domain not in domains_of_interest:
                continue
            if any(term in msg for term in terms):
                self.signal_expertise(domain, f"used term: {next(t for t in terms if t in msg)}")

        if any(signal in msg for signal in novice_signals):
            # Find which domain they're asking about
            for domain in (domains_of_interest or list(expert_signals.keys())):
                if domain in msg or domain.replace("_", " ") in msg:
                    self.signal_gap(domain, f"asked basic question about {domain}")

    def to_system_fragment(self) -> str:
        lines = ["[Common Ground — what VYRA and Lokesh share as established knowledge]"]
        # Top knowledge domains
        if self._knowledge:
            domains = sorted(self._knowledge.items(), key=lambda x: abs(x[1].level - 0.5), reverse=True)[:5]
            lines.append("  Knowledge calibration:")
            for domain, kd in domains:
                lines.append(f"    {domain}: {kd.explanation_depth()} (level={kd.level:.2f})")
        # Recent session facts
        recent = self._session_facts[-4:]
        if recent:
            lines.append("  Established this session:")
            for f in recent:
                lines.append(f"    ✓ {f.content[:80]}")
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "domains_tracked": len(self._knowledge),
            "session_facts": len(self._session_facts),
            "persisted_facts": len(self._persisted_facts),
            "knowledge": {k: {"level": round(v.level, 2), "depth": v.explanation_depth()}
                          for k, v in self._knowledge.items()},
        }


_cg: Optional[CommonGround] = None
def get_common_ground() -> CommonGround:
    global _cg
    if _cg is None:
        _cg = CommonGround()
    return _cg
