"""
World Model — Phase 3.2
========================
A persistent, structured representation of the user's complete life context.

Unlike episodic memory (events) or unified_memory (facts), the World Model is
a LIVING, STRUCTURED graph of the user's world that VYRA continuously updates.

Components:
  - UserProfile       : skills, preferences, history, expertise domains
  - RelationshipGraph : people, companies, social dynamics
  - ProjectGraph      : ongoing work with state machines
  - KnowledgeDomains  : what user knows well vs poorly
  - EnvironmentState  : devices, home, routines, location patterns

VYRA uses this to answer IN CONTEXT — never generic advice, always personalised.

Usage:
    model = get_world_model()
    await model.update_from_episode(episode)          # auto-update from events
    ctx   = model.get_context_block("finance advice") # inject into LLM
    model.add_person("Priya", role="colleague", notes="works on ML infra")
"""

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR = Path(__file__).parent.parent / "data"
WM_FILE  = DATA_DIR / "world_model.json"


# ── Sub-models ────────────────────────────────────────────────────────────────

@dataclass
class Person:
    name: str
    role: str                    # "friend" | "colleague" | "boss" | "client" | "family"
    relationship_strength: float = 0.5   # 0-1
    communication_style: str     = "casual"
    known_preferences: List[str] = field(default_factory=list)
    notes: str                   = ""
    last_interaction: str        = ""
    interaction_count: int       = 0
    emotional_dynamics: str      = ""    # e.g. "tense lately", "very positive"

@dataclass
class Project:
    name: str
    description: str
    status: str           = "active"   # active | paused | done
    domain: str           = ""
    key_files: List[str]  = field(default_factory=list)
    milestones: List[str] = field(default_factory=list)
    blockers: List[str]   = field(default_factory=list)
    last_worked: str      = ""
    notes: str            = ""

@dataclass
class KnowledgeDomain:
    name: str
    expertise_level: float    = 0.5   # 0=beginner, 1=expert
    topics: List[str]         = field(default_factory=list)
    learning_in_progress: bool= False
    last_updated: str         = ""

@dataclass
class UserProfile:
    name: str                  = "Lokesh"
    timezone: str              = "Asia/Kolkata"
    language: str              = "en"
    preferred_response_style: str = "concise"
    occupation: str            = ""
    goals_summary: str         = ""
    personality_notes: str     = ""
    routines: Dict[str, str]   = field(default_factory=dict)   # "morning" → "gym, coffee, code"
    preferences: Dict[str, str]= field(default_factory=dict)   # "music_genre" → "lo-fi"
    dislikes: List[str]        = field(default_factory=list)
    technical_stack: List[str] = field(default_factory=list)   # "Python", "React", etc.


# ── World Model ───────────────────────────────────────────────────────────────

EXTRACT_SYSTEM = """You extract structured updates from conversations/events.
Output valid JSON only. Only include fields that are explicitly mentioned.
Do not invent information."""

class WorldModel:

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir   = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.wm_file    = data_dir / "world_model.json"
        self.client     = get_nvidia_client()
        self.profile    = UserProfile()
        self.people: Dict[str, Person]           = {}
        self.projects: Dict[str, Project]        = {}
        self.knowledge: Dict[str, KnowledgeDomain] = {}
        self.environment: Dict[str, Any]         = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if self.wm_file.exists():
            try:
                d = json.loads(self.wm_file.read_text(encoding="utf-8"))
                self.profile     = UserProfile(**d.get("profile", {}))
                self.people      = {k: Person(**v) for k, v in d.get("people", {}).items()}
                self.projects    = {k: Project(**v) for k, v in d.get("projects", {}).items()}
                self.knowledge   = {k: KnowledgeDomain(**v) for k, v in d.get("knowledge", {}).items()}
                self.environment = d.get("environment", {})
            except Exception as e:
                print(f"[WorldModel] Load error: {e}")

    def save(self):
        data = {
            "profile":     asdict(self.profile),
            "people":      {k: asdict(v) for k, v in self.people.items()},
            "projects":    {k: asdict(v) for k, v in self.projects.items()},
            "knowledge":   {k: asdict(v) for k, v in self.knowledge.items()},
            "environment": self.environment,
            "updated_at":  datetime.utcnow().isoformat(),
        }
        self.wm_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── Public API ────────────────────────────────────────────────────────────

    def add_person(self, name: str, role: str = "acquaintance", **kwargs) -> Person:
        key = name.lower().strip()
        if key not in self.people:
            self.people[key] = Person(name=name, role=role, **kwargs)
        else:
            p = self.people[key]
            for k, v in kwargs.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            p.interaction_count += 1
            p.last_interaction   = datetime.utcnow().isoformat()
        self.save()
        return self.people[key]

    def add_project(self, name: str, description: str = "", **kwargs) -> Project:
        key = name.lower().strip().replace(" ", "_")
        if key not in self.projects:
            self.projects[key] = Project(name=name, description=description, **kwargs)
        else:
            p = self.projects[key]
            for k, v in kwargs.items():
                if hasattr(p, k):
                    setattr(p, k, v)
            p.last_worked = datetime.utcnow().isoformat()
        self.save()
        return self.projects[key]

    def update_knowledge(self, domain: str, level_delta: float = 0.05, topics: List[str] = None):
        key = domain.lower().strip()
        if key not in self.knowledge:
            self.knowledge[key] = KnowledgeDomain(name=domain)
        kd = self.knowledge[key]
        kd.expertise_level = min(1.0, max(0.0, kd.expertise_level + level_delta))
        if topics:
            kd.topics = list(set(kd.topics + topics))
        kd.last_updated = datetime.utcnow().isoformat()
        self.save()

    async def update_from_episode(self, content: str, source: str = "conversation"):
        """Auto-extract world model updates from a conversation/event."""
        prompt = (
            f"Conversation/event:\n{content[:2000]}\n\n"
            f"Extract ANY world model updates. Include only explicitly mentioned info.\n"
            f"JSON format: {{\n"
            f'  "profile_updates": {{"occupation": "...", "technical_stack": [...]}},\n'
            f'  "people": [{{"name": "...", "role": "...", "notes": "..."}}],\n'
            f'  "projects": [{{"name": "...", "description": "...", "status": "active"}}],\n'
            f'  "knowledge": [{{"domain": "...", "topics": [...], "learning": true}}]\n'
            f"}}\n"
            f"Output only fields you are confident about. Output empty object {{}} if nothing."
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
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            d     = json.loads(raw[start:end])

            # Apply profile updates
            for k, v in d.get("profile_updates", {}).items():
                if hasattr(self.profile, k) and v:
                    if isinstance(getattr(self.profile, k), list):
                        existing = getattr(self.profile, k)
                        if isinstance(v, list):
                            setattr(self.profile, k, list(set(existing + v)))
                    else:
                        setattr(self.profile, k, v)

            # Apply people updates
            for p in d.get("people", []):
                if p.get("name"):
                    self.add_person(p["name"], role=p.get("role", "acquaintance"),
                                    notes=p.get("notes", ""))

            # Apply project updates
            for proj in d.get("projects", []):
                if proj.get("name"):
                    self.add_project(proj["name"], proj.get("description", ""),
                                     status=proj.get("status", "active"))

            # Apply knowledge updates
            for kd in d.get("knowledge", []):
                if kd.get("domain"):
                    self.update_knowledge(
                        kd["domain"],
                        topics=kd.get("topics", []),
                        level_delta=0.05 if kd.get("learning") else 0.0,
                    )

            self.save()
        except Exception as e:
            print(f"[WorldModel] update_from_episode error: {e}")

    def get_context_block(self, topic: str = "") -> str:
        """
        Returns a ready-to-inject context block for the LLM.
        Tailored to the topic if provided.
        """
        lines = [f"[World Model: About {self.profile.name}]"]

        # Profile
        if self.profile.occupation:
            lines.append(f"Occupation: {self.profile.occupation}")
        if self.profile.technical_stack:
            lines.append(f"Tech stack: {', '.join(self.profile.technical_stack)}")
        if self.profile.preferences:
            top_prefs = list(self.profile.preferences.items())[:3]
            lines.append("Preferences: " + ", ".join(f"{k}={v}" for k, v in top_prefs))

        # Active projects
        active_projs = [p for p in self.projects.values() if p.status == "active"]
        if active_projs:
            names = ", ".join(p.name for p in active_projs[:3])
            lines.append(f"Active projects: {names}")

        # Relevant people (if topic mentions a person name)
        topic_lower = topic.lower()
        for name, person in self.people.items():
            if name in topic_lower or person.role in ["boss", "partner"]:
                lines.append(
                    f"  {person.name} ({person.role}): {person.notes[:80]}"
                    + (f" [Last contact: {person.last_interaction[:10]}]" if person.last_interaction else "")
                )

        # Knowledge domains relevant to topic
        for key, kd in self.knowledge.items():
            if key in topic_lower and kd.expertise_level > 0.3:
                lines.append(
                    f"  Knows {kd.name}: level {kd.expertise_level:.1f}/1.0"
                    + (f" — learning topics: {', '.join(kd.topics[:3])}" if kd.topics else "")
                )

        return "\n".join(lines)

    def get_person(self, name: str) -> Optional[Person]:
        return self.people.get(name.lower().strip())

    def get_project(self, name: str) -> Optional[Project]:
        return self.projects.get(name.lower().strip().replace(" ", "_"))

    def summary(self) -> str:
        return (
            f"World Model: {len(self.people)} people, "
            f"{len(self.projects)} projects, "
            f"{len(self.knowledge)} knowledge domains"
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_model: Optional[WorldModel] = None

def get_world_model() -> WorldModel:
    global _model
    if _model is None:
        _model = WorldModel()
    return _model


if __name__ == "__main__":
    async def _test():
        model = get_world_model()
        await model.update_from_episode(
            "Lokesh is working on VYRA, an AI assistant in Python and React. "
            "He mentioned his colleague Priya helps with the ML pipeline. "
            "He's also learning about CUDA optimization."
        )
        print(model.summary())
        print(model.get_context_block("Python async"))

    asyncio.run(_test())
