"""
Social Advisor — Phase 8.4
============================
Advises VYRA on social situations before and after they happen.

Pre-brief: "You have a salary negotiation in 30 min — here's your strategy."
Post-debrief: "How did it go? What worked?" → store outcome for future.

Also handles:
  - Draft messages in the right tone for each person
  - Detect when user is about to say something they might regret (stress mode)
  - Suggest reconnection messages for neglected relationships

Usage:
    advisor = get_social_advisor()
    brief   = await advisor.pre_brief("salary negotiation with boss Sarah tomorrow")
    draft   = await advisor.draft_message("Sarah", "follow up on salary discussion", tone="professional")
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

BRIEF_SYSTEM = """You are a personal social coach for VYRA's user.
Given context about a situation and the people involved, provide specific,
actionable advice. Be direct and practical. Use knowledge of their relationships."""

DRAFT_SYSTEM = """You draft messages for VYRA's user.
Match the tone exactly to the relationship type and context.
Be natural — sound like the user, not a formal assistant.
Keep it appropriately brief."""

DEBRIEF_SYSTEM = """You help the user reflect on a social interaction.
Ask one specific follow-up question to capture what worked and what didn't.
Store insights for future advice."""


@dataclass
class SocialBrief:
    situation: str
    strategy: str
    key_points: List[str]
    what_to_avoid: List[str]
    person_notes: str
    generated_at: str


@dataclass
class DraftMessage:
    recipient: str
    context: str
    draft: str
    tone: str
    word_count: int


class SocialAdvisor:

    def __init__(self):
        self.client = get_nvidia_client()

    async def pre_brief(
        self,
        situation: str,
        person_name: Optional[str] = None,
    ) -> SocialBrief:
        """Generate a pre-interaction coaching brief."""
        person_ctx = ""
        if person_name:
            try:
                from memory.world_model import get_world_model  # type: ignore
                from social.relationship_engine import get_relationship_engine  # type: ignore
                wm     = get_world_model()
                person = wm.get_person(person_name)
                if person:
                    person_ctx = (
                        f"Person: {person.name} ({person.role})\n"
                        f"Dynamics: {person.emotional_dynamics}\n"
                        f"Preferences: {', '.join(person.known_preferences[:3])}\n"
                        f"Notes: {person.notes}"
                    )
            except Exception:
                pass

        # Pull relevant past episodes
        memory_ctx = ""
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            memory_ctx = await mem.get_context_for_llm(situation, top_k=4)
        except Exception:
            pass

        prompt = (
            f"Situation: {situation}\n\n"
            + (f"Person context:\n{person_ctx}\n\n" if person_ctx else "")
            + (f"Relevant history:\n{memory_ctx}\n\n" if memory_ctx else "")
            + f"Provide a social coaching brief. JSON format:\n"
            f'{{"strategy":"...", "key_points":["...","..."], '
            f'"what_to_avoid":["..."], "person_notes":"..."}}'
        )

        try:
            resp = await self.client.athink(
                prompt=prompt,
                system=BRIEF_SYSTEM,
                max_tokens=2048,
            )
            import json
            raw   = resp.answer.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            d     = json.loads(raw[start:end])
            return SocialBrief(
                situation   = situation,
                strategy    = d.get("strategy", ""),
                key_points  = d.get("key_points", []),
                what_to_avoid = d.get("what_to_avoid", []),
                person_notes  = d.get("person_notes", person_ctx),
                generated_at  = datetime.utcnow().isoformat(),
            )
        except Exception as e:
            resp2 = await self.client.achat(
                [{"role": "system", "content": BRIEF_SYSTEM},
                 {"role": "user", "content": prompt}],
                model="fast", max_tokens=1024,
            )
            return SocialBrief(
                situation=situation, strategy=resp2.content,
                key_points=[], what_to_avoid=[], person_notes=person_ctx,
                generated_at=datetime.utcnow().isoformat(),
            )

    async def draft_message(
        self,
        recipient: str,
        context: str,
        tone: str = "casual",
        channel: str = "text",   # "text" | "email" | "slack"
    ) -> DraftMessage:
        """Draft a message to a specific person."""
        person_ctx = ""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm     = get_world_model()
            person = wm.get_person(recipient)
            if person:
                person_ctx = (
                    f"Recipient: {person.name} ({person.role})\n"
                    f"Communication style: {person.communication_style}\n"
                    f"Notes: {person.notes}"
                )
        except Exception:
            pass

        prompt = (
            f"Recipient: {recipient}\n"
            f"{person_ctx}\n"
            f"Context/purpose: {context}\n"
            f"Tone: {tone}\n"
            f"Channel: {channel}\n\n"
            f"Draft the message. Just the message text, nothing else."
        )

        resp = await self.client.achat(
            [{"role": "system", "content": DRAFT_SYSTEM},
             {"role": "user",   "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.7,
        )
        draft = resp.content.strip()
        return DraftMessage(
            recipient  = recipient,
            context    = context,
            draft      = draft,
            tone       = tone,
            word_count = len(draft.split()),
        )

    async def debrief(self, situation: str, outcome: str):
        """Store post-interaction learnings."""
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            await mem.record(
                content  = f"Social situation: {situation}\nOutcome: {outcome}",
                source   = "conversation",
                context  = "Social debrief",
                manual_importance = 0.65,
            )
        except Exception:
            pass

    async def reconnect_message(self, person_name: str) -> Optional[DraftMessage]:
        """Draft a warm reconnection message for a neglected contact."""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm     = get_world_model()
            person = wm.get_person(person_name)
            if not person:
                return None
            context = (
                f"Reconnecting after some time apart. "
                f"Last interaction notes: {person.notes[:100] if person.notes else 'general catch-up'}"
            )
            return await self.draft_message(
                person_name, context, tone="warm and casual"
            )
        except Exception:
            return None


_advisor: Optional[SocialAdvisor] = None

def get_social_advisor() -> SocialAdvisor:
    global _advisor
    if _advisor is None:
        _advisor = SocialAdvisor()
    return _advisor
