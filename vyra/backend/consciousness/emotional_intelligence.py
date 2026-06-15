"""
VYRA Emotional Intelligence v2 — Phase 16
==========================================
Deep understanding of Lokesh's emotional state from conversation signals.
Adapts VYRA's communication style in real-time.

Based on:
  - Mayer & Salovey (1990) Emotional Intelligence model
  - Goleman (1995) EQ dimensions: self-awareness, empathy, social skills
  - Interpersonal Complementarity Theory (Kiesler 1983)

Features:
  1. USER EMOTION DETECTION — infers Lokesh's mood from messages
  2. STYLE ADAPTATION — adjusts VYRA's tone to match/complement
  3. EMPATHY RESPONSES — knows when to validate vs problem-solve
  4. STRESS DETECTION — identifies signs of overwhelm/frustration
  5. RAPPORT TRACKER — overall relationship quality score
"""

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR = Path(__file__).parent.parent / "data"
EI_PATH  = DATA_DIR / "emotional_intelligence.json"

EMOTION_SIGNALS = {
    "frustration": ["frustrated", "annoyed", "not working", "broken", "again", "why", "ugh", "stupid"],
    "stress": ["deadline", "urgent", "asap", "must finish", "running out", "behind", "pressure"],
    "excitement": ["great", "amazing", "finally", "worked", "perfect", "love this", "awesome"],
    "curiosity": ["how does", "why does", "what if", "interesting", "tell me more", "explain"],
    "tiredness": ["tired", "exhausted", "sleepy", "long day", "later", "tomorrow"],
}

STYLE_ADAPTERS = {
    "frustration": "be concise, acknowledge the frustration, skip preamble",
    "stress":      "be efficient, bullet points, prioritize the most critical thing",
    "excitement":  "match energy, build on their enthusiasm",
    "curiosity":   "go deep, provide context, invite exploration",
    "tiredness":   "be brief, offer to continue later, don't overwhelm",
    "neutral":     "conversational, warm, thorough",
}


@dataclass
class EmotionalReading:
    timestamp: str
    detected_emotion: str       # dominant emotion inferred
    confidence: float           # 0.0–1.0
    signals_found: List[str]    # words that triggered detection
    style_note: str             # how VYRA should adapt


class EmotionalIntelligence:
    """
    Infers Lokesh's emotional state from messages and adapts VYRA's style.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._history: List[Dict] = []
        self._rapport_score: float = 0.7
        self._current_emotion: str = "neutral"
        self._interaction_count: int = 0
        self._load()

    def _load(self):
        try:
            raw = json.loads(EI_PATH.read_text())
            self._history = raw.get("history", [])[-50:]
            self._rapport_score = raw.get("rapport_score", 0.7)
            self._current_emotion = raw.get("current_emotion", "neutral")
            self._interaction_count = raw.get("interaction_count", 0)
        except Exception:
            pass

    def _save(self):
        try:
            EI_PATH.write_text(json.dumps({
                "history": self._history[-50:],
                "rapport_score": self._rapport_score,
                "current_emotion": self._current_emotion,
                "interaction_count": self._interaction_count,
            }, indent=2))
        except Exception:
            pass

    def analyze_message(self, text: str) -> EmotionalReading:
        """Detect emotional signals in Lokesh's message."""
        text_lower = text.lower()
        scores: Dict[str, float] = {}
        all_signals: Dict[str, List[str]] = {}

        for emotion, signals in EMOTION_SIGNALS.items():
            found = [s for s in signals if s in text_lower]
            if found:
                scores[emotion] = len(found) / len(signals)
                all_signals[emotion] = found

        if not scores:
            detected = "neutral"
            confidence = 0.5
            found_signals: List[str] = []
        else:
            detected = max(scores, key=scores.get)  # type: ignore
            confidence = min(1.0, scores[detected] * 3.0)
            found_signals = all_signals.get(detected, [])

        style_note = STYLE_ADAPTERS.get(detected, STYLE_ADAPTERS["neutral"])
        reading = EmotionalReading(
            timestamp=datetime.utcnow().isoformat(),
            detected_emotion=detected,
            confidence=confidence,
            signals_found=found_signals,
            style_note=style_note,
        )

        self._current_emotion = detected
        self._interaction_count += 1
        self._history.append(asdict(reading))

        # Rapport slowly increases with positive interactions
        if detected in ("excitement", "curiosity"):
            self._rapport_score = min(1.0, self._rapport_score + 0.01)
        elif detected == "frustration":
            self._rapport_score = max(0.3, self._rapport_score - 0.02)

        self._save()
        return reading

    def get_style_guidance(self) -> str:
        """Return current style adaptation guidance for VYRA."""
        return STYLE_ADAPTERS.get(self._current_emotion, STYLE_ADAPTERS["neutral"])

    def to_system_fragment(self) -> str:
        if self._current_emotion == "neutral":
            return ""
        style = self.get_style_guidance()
        rapport = round(self._rapport_score * 100)
        return (
            f"[Lokesh's current mood: {self._current_emotion}. "
            f"Style guidance: {style}. "
            f"Rapport: {rapport}/100]"
        )

    def snapshot(self) -> Dict[str, Any]:
        recent = self._history[-5:] if self._history else []
        emotion_freq: Dict[str, int] = {}
        for r in self._history[-20:]:
            em = r.get("detected_emotion", "neutral")
            emotion_freq[em] = emotion_freq.get(em, 0) + 1
        return {
            "current_emotion": self._current_emotion,
            "rapport_score": round(self._rapport_score, 3),
            "interactions_analyzed": self._interaction_count,
            "emotion_frequency": emotion_freq,
            "recent_readings": len(recent),
        }


_ei: Optional[EmotionalIntelligence] = None

def get_emotional_intelligence() -> EmotionalIntelligence:
    global _ei
    if _ei is None:
        _ei = EmotionalIntelligence()
    return _ei


if __name__ == "__main__":
    ei = get_emotional_intelligence()
    r1 = ei.analyze_message("This is not working again! Why does it keep breaking?")
    print(f"Reading 1: {r1.detected_emotion} ({r1.confidence:.2f}) — {r1.style_note}")
    r2 = ei.analyze_message("Amazing! It finally worked perfectly!")
    print(f"Reading 2: {r2.detected_emotion} ({r2.confidence:.2f}) — {r2.style_note}")
    print("Snapshot:", ei.snapshot())
    print("Fragment:", ei.to_system_fragment())
