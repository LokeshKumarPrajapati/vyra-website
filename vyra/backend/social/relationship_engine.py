"""
Relationship Engine — Phase 8.1
==================================
Builds and maintains a detailed model of everyone in the user's life.
Tracks communication patterns, emotional dynamics, preferences, and context.

Features:
  - Auto-extracts person mentions from conversations
  - Tracks interaction frequency and last contact
  - Detects relationship dynamics (positive, tense, improving)
  - Generates smart reminders ("You haven't talked to Alex in 3 weeks")
  - Provides communication style guidance per person
  - Stores all under WorldModel.people (persisted to world_model.json)

Usage:
    engine = get_relationship_engine()
    await engine.process_conversation("Priya called me about the deployment issue")
    tip    = engine.communication_tip("Priya")
    engine.get_neglected(threshold_days=14)   # who needs attention
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

EXTRACT_SYSTEM = """You extract person mentions and relationship signals from conversations.
Output valid JSON only. Only include people explicitly mentioned."""

STYLE_SYSTEM = """You generate a brief, specific communication tip for interacting with
a specific person given their profile. 1-2 sentences, actionable, specific."""


class RelationshipEngine:

    def __init__(self):
        self.client = get_nvidia_client()

    # ── Extraction ────────────────────────────────────────────────────────────

    async def process_conversation(self, text: str) -> List[str]:
        """
        Extract person mentions + relationship signals from a conversation.
        Updates WorldModel.people accordingly.
        Returns list of person names found.
        """
        prompt = (
            f"Conversation:\n{text[:2000]}\n\n"
            f"Extract all people mentioned. For each, provide:\n"
            f"  - name: their name\n"
            f"  - role: relationship (friend/colleague/boss/client/family/partner)\n"
            f"  - emotional_signal: positive/negative/neutral/tense\n"
            f"  - notes: specific detail mentioned (max 1 sentence)\n"
            f"  - last_interaction: 'just now' if mentioned as current\n\n"
            f"JSON array. Empty array if no people mentioned."
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": EXTRACT_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="fast",
                max_tokens=512,
                temperature=0.1,
            )
            raw   = resp.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            people = json.loads(raw[start:end])

            found = []
            for p in people:
                if not p.get("name"):
                    continue
                self._update_person(p)
                found.append(p["name"])
            return found
        except Exception:
            return []

    def _update_person(self, data: Dict[str, Any]):
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm   = get_world_model()
            name = data.get("name", "")
            if not name:
                return
            notes = data.get("notes", "")
            emotional = data.get("emotional_signal", "neutral")
            wm.add_person(
                name=name,
                role=data.get("role", "acquaintance"),
                notes=notes,
                last_interaction=datetime.utcnow().isoformat(),
                emotional_dynamics=emotional,
            )
        except Exception:
            pass

    # ── Reminders ─────────────────────────────────────────────────────────────

    def get_neglected(self, threshold_days: int = 14) -> List[Dict]:
        """Return people who haven't been mentioned in threshold_days."""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm      = get_world_model()
            cutoff  = datetime.utcnow() - timedelta(days=threshold_days)
            results = []
            for person in wm.people.values():
                if not person.last_interaction:
                    continue
                last = datetime.fromisoformat(person.last_interaction)
                if last < cutoff and person.relationship_strength > 0.3:
                    days_since = (datetime.utcnow() - last).days
                    results.append({
                        "name":       person.name,
                        "role":       person.role,
                        "days_since": days_since,
                        "notes":      person.notes,
                    })
            results.sort(key=lambda x: x["days_since"], reverse=True)
            return results
        except Exception:
            return []

    def get_neglected_reminder(self, threshold_days: int = 14) -> Optional[str]:
        neglected = self.get_neglected(threshold_days)
        if not neglected:
            return None
        top = neglected[0]
        return (
            f"You haven't been in touch with {top['name']} ({top['role']}) "
            f"for {top['days_since']} days. "
            f"Want me to draft a message?"
        )

    # ── Communication tips ────────────────────────────────────────────────────

    async def communication_tip(self, person_name: str) -> str:
        """Generate a specific tip for communicating with this person."""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm     = get_world_model()
            person = wm.get_person(person_name)
            if not person:
                return ""
            profile = (
                f"Name: {person.name}\n"
                f"Role: {person.role}\n"
                f"Communication style: {person.communication_style}\n"
                f"Preferences: {', '.join(person.known_preferences[:3])}\n"
                f"Emotional dynamics: {person.emotional_dynamics}\n"
                f"Notes: {person.notes}"
            )
            resp = await self.client.achat(
                [{"role": "system", "content": STYLE_SYSTEM},
                 {"role": "user", "content": f"Person profile:\n{profile}\n\nCommunication tip:"}],
                model="fast",
                max_tokens=150,
                temperature=0.5,
            )
            return resp.content.strip()
        except Exception:
            return ""

    # ── Relationship health ───────────────────────────────────────────────────

    def relationship_health_report(self) -> str:
        """Summary of relationship status for morning briefing."""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm      = get_world_model()
            neglect = self.get_neglected(14)
            tense   = [p for p in wm.people.values() if "tense" in (p.emotional_dynamics or "").lower()]
            lines   = []
            if neglect:
                names = ", ".join(p["name"] for p in neglect[:2])
                lines.append(f"Haven't heard from: {names}")
            if tense:
                names = ", ".join(p.name for p in tense[:2])
                lines.append(f"Relationship tension with: {names}")
            return "\n".join(lines) if lines else "All relationships look healthy."
        except Exception:
            return ""


_engine: Optional[RelationshipEngine] = None

def get_relationship_engine() -> RelationshipEngine:
    global _engine
    if _engine is None:
        _engine = RelationshipEngine()
    return _engine
