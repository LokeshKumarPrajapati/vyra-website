"""
Briefing Engine — Phase 2.3
============================
Generates VYRA's daily proactive morning (and evening) briefings.

Morning briefing covers:
  1. Active goals & overnight progress
  2. Today's calendar events (if Google Calendar connected)
  3. Pending approvals from background executor
  4. News relevant to user's interest profile (if real-time pipeline active)
  5. System health (disk, memory, pending Windows updates)

Evening briefing covers:
  1. What was accomplished today
  2. What's queued for tomorrow
  3. Goal progress delta

Briefing is delivered via voice (text returned to vyra.py for TTS)
and also sent to the UI as a structured card.

Usage:
    engine  = get_briefing_engine()
    briefing = await engine.morning_briefing()
    # briefing.voice_text → feed to Gemini TTS
    # briefing.ui_card    → emit via Socket.IO
"""

import asyncio
import json
import platform
import time
from dataclasses import dataclass
from datetime import datetime, date
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
from goals.goal_engine import get_goal_engine  # type: ignore

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


# ── Briefing result ───────────────────────────────────────────────────────────

@dataclass
class Briefing:
    type: str                    # "morning" | "evening"
    generated_at: str
    voice_text: str              # ~60 seconds of TTS content
    ui_card: Dict[str, Any]      # structured card for frontend
    raw_sections: Dict[str, str] # section_name → content


# ── Engine ────────────────────────────────────────────────────────────────────

MORNING_SYSTEM = """You are VYRA's briefing writer. Generate a natural, warm, engaging
morning briefing that sounds like a knowledgeable personal assistant speaking aloud.
Keep it under 200 words. Be direct — no filler phrases like 'Certainly!' or 'Of course!'.
Start with a greeting using the current time of day."""

EVENING_SYSTEM = """You are VYRA's briefing writer. Generate a brief, encouraging
evening wrap-up that highlights accomplishments and sets up tomorrow clearly.
Keep it under 150 words. Warm but efficient tone."""


class BriefingEngine:

    def __init__(self):
        self.client = get_nvidia_client()

    # ── Public ────────────────────────────────────────────────────────────────

    async def morning_briefing(self, user_name: str = "Lokesh") -> Briefing:
        sections = await self._gather_morning_sections(user_name)
        voice    = await self._write_voice_text(sections, "morning", user_name)
        card     = self._build_morning_card(sections)
        return Briefing(
            type="morning",
            generated_at=datetime.utcnow().isoformat(),
            voice_text=voice,
            ui_card=card,
            raw_sections=sections,
        )

    async def evening_briefing(self, user_name: str = "Lokesh") -> Briefing:
        sections = await self._gather_evening_sections(user_name)
        voice    = await self._write_voice_text(sections, "evening", user_name)
        card     = self._build_evening_card(sections)
        return Briefing(
            type="evening",
            generated_at=datetime.utcnow().isoformat(),
            voice_text=voice,
            ui_card=card,
            raw_sections=sections,
        )

    # ── Section gatherers ─────────────────────────────────────────────────────

    async def _gather_morning_sections(self, user_name: str) -> Dict[str, str]:
        sections: Dict[str, str] = {}

        # 1. Goals
        sections["goals"] = self._goals_section()

        # 2. Pending approvals
        sections["approvals"] = self._approvals_section()

        # 3. System health
        sections["system"] = self._system_health()

        # 4. Date/time context
        now = datetime.now()
        sections["datetime"] = (
            f"Today is {now.strftime('%A, %B %d %Y')}. "
            f"Time: {now.strftime('%I:%M %p')}."
        )

        return sections

    async def _gather_evening_sections(self, user_name: str) -> Dict[str, str]:
        sections: Dict[str, str] = {}
        sections["goals"]    = self._goals_section(today_only=True)
        sections["datetime"] = datetime.now().strftime("%A evening, %B %d")
        return sections

    # ── Section builders ──────────────────────────────────────────────────────

    def _goals_section(self, today_only: bool = False) -> str:
        engine = get_goal_engine()
        active = engine.list_active()
        if not active:
            return "No active goals."
        lines = []
        for g in active[:4]:
            pct  = int(g.progress * 100)
            task = g.next_task
            next_action = f"Next: {task.instruction[:60]}" if task else "All tasks queued."
            lines.append(f"• {g.title} — {pct}% done. {next_action}")
        return "\n".join(lines)

    def _approvals_section(self) -> str:
        try:
            from goals.background_executor import get_executor  # type: ignore
            queue = get_executor().get_approval_queue()
            if not queue:
                return "No pending approvals."
            return f"{len(queue)} task(s) waiting for your approval."
        except Exception:
            return ""

    def _system_health(self) -> str:
        if not _PSUTIL:
            return ""
        try:
            cpu  = psutil.cpu_percent(interval=0.5)
            ram  = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            parts = [
                f"CPU {cpu:.0f}%",
                f"RAM {ram.percent:.0f}% used",
                f"Disk {disk.percent:.0f}% used",
            ]
            battery = psutil.sensors_battery()
            if battery:
                parts.append(
                    f"Battery {battery.percent:.0f}%"
                    + ("" if battery.power_plugged else " (unplugged)")
                )
            return ", ".join(parts)
        except Exception:
            return ""

    # ── Voice writer ──────────────────────────────────────────────────────────

    async def _write_voice_text(
        self, sections: Dict[str, str], briefing_type: str, user_name: str
    ) -> str:
        content = "\n\n".join(
            f"[{k.upper()}]\n{v}" for k, v in sections.items() if v
        )
        system = MORNING_SYSTEM if briefing_type == "morning" else EVENING_SYSTEM
        prompt = (
            f"User's name: {user_name}\n\n"
            f"Data to include:\n{content}\n\n"
            f"Write the briefing now:"
        )
        resp = await self.client.achat(
            [{"role": "system", "content": system},
             {"role": "user",   "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.7,
        )
        return resp.content.strip()

    # ── Card builders ─────────────────────────────────────────────────────────

    def _build_morning_card(self, sections: Dict[str, str]) -> Dict[str, Any]:
        return {
            "type":      "morning_briefing",
            "timestamp": datetime.utcnow().isoformat(),
            "sections": [
                {"title": "Active Goals",       "content": sections.get("goals", "")},
                {"title": "Pending Approvals",  "content": sections.get("approvals", "")},
                {"title": "System Health",      "content": sections.get("system", "")},
            ],
        }

    def _build_evening_card(self, sections: Dict[str, str]) -> Dict[str, Any]:
        return {
            "type":      "evening_briefing",
            "timestamp": datetime.utcnow().isoformat(),
            "sections": [
                {"title": "Today's Progress", "content": sections.get("goals", "")},
            ],
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[BriefingEngine] = None

def get_briefing_engine() -> BriefingEngine:
    global _engine
    if _engine is None:
        _engine = BriefingEngine()
    return _engine


if __name__ == "__main__":
    async def _test():
        engine   = get_briefing_engine()
        briefing = await engine.morning_briefing("Lokesh")
        print("=== VOICE TEXT ===")
        print(briefing.voice_text)
        print("\n=== UI CARD ===")
        print(json.dumps(briefing.ui_card, indent=2))

    asyncio.run(_test())
