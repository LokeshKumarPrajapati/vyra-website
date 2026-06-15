"""
Automatic extraction of user-specific context from conversation.

Uses the language model to identify and extract:
- Important people (friends, family, colleagues) and their relations
- Critical facts (preferences, life events, constraints, interests)
- Preferences (likes, dislikes, habits)

Extracted data is merged into UserMemory without requiring repeated
explicit instructions from the user. Runs periodically or after N messages.
"""

import os
import json
import time
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Models tried in order — first available wins
# gemini-1.5-flash-8b is deprecated (404). gemini-2.5-flash-lite needs v1beta.
_EXTRACTOR_MODELS = [
    "gemini-2.5-flash",         # Primary — fast, smart
    "gemini-2.0-flash-lite",    # Cheap fallback
    "gemini-2.0-flash",         # Heavier fallback
    "gemini-1.5-flash",         # Last resort (v1beta only)
]

_EXTRACTOR_CLIENT = None


def _get_client():
    global _EXTRACTOR_CLIENT
    if _EXTRACTOR_CLIENT is None:
        _EXTRACTOR_CLIENT = genai.Client(
            http_options={"api_version": "v1beta"},
            api_key=os.getenv("GEMINI_API_KEY"),
        )
    return _EXTRACTOR_CLIENT


EXTRACTION_PROMPT = """You are a context extractor for a personal AI assistant named VYRA. From the conversation below, extract ONLY clearly stated, factual information that should be permanently remembered. Do NOT infer or guess — extract only what was explicitly said.

Rules:
1. PEOPLE: Extract people the user mentions with their relation (friend, family, colleague, etc.).
2. FACTS: Extract concrete, reusable facts in these categories:
   - preference: what the user likes/dislikes/prefers (e.g. "prefers JARVIS workflows over n8n")
   - work_project: projects, tools, tech stacks, workflow systems the user works with
   - behavioral_rule: explicit instructions the user gave VYRA (e.g. "don't use n8n", "always use JARVIS", "stop doing X")
   - constraint: hard limits (allergic to X, can't do Y)
   - life_event: events, milestones, jobs
   - interest: hobbies, topics the user is into
   - goal: things the user wants to achieve
   - general: anything else factual
3. TOOL PREFERENCES: If the user explicitly states which tool/system they prefer (n8n vs JARVIS workflows, Chrome vs Firefox, etc.) — capture it in BOTH facts (category: preference OR behavioral_rule) AND as a key-value preference.
4. BEHAVIORAL RULES: If the user says "don't do X", "always do Y", "from now on Z", "use X not Y" — extract as category: behavioral_rule with high specificity.
5. RELATIONSHIPS: relationships between people.
6. PREFERENCES: simple key-value pairs (e.g. "workflow_tool": "JARVIS", "browser": "Chrome").
7. Do NOT extract temporary chat context, opinions about weather, or vague statements.
8. Output valid JSON only, no markdown.

Output format (use exactly these keys):
{
  "people": [{"name": "FullName", "relation": "friend|family|colleague|...", "notes": "optional detail"}],
  "relationships": [{"person_a": "Name1", "person_b": "Name2", "relation": "connection_type", "notes": "optional"}],
  "facts": [{"fact": "one clear sentence", "category": "preference|behavioral_rule|constraint|life_event|interest|goal|work_project|general"}],
  "preferences": {"snake_case_key": "value"}
}

Conversation (user name: {user_name}):
---
{conversation}
---
JSON output:"""


def _messages_to_text(messages: List[Dict[str, Any]], user_name: str = "User") -> str:
    lines = []
    for m in messages:
        sender = m.get("sender", "Unknown")
        text = m.get("text", "").strip()
        if not text:
            continue
        if sender.lower() == "lokesh" or sender.lower() == "user":
            lines.append(f"{user_name}: {text}")
        else:
            lines.append(f"Assistant: {text}")
    return "\n".join(lines)


def _parse_json_from_response(text: str) -> Optional[Dict[str, Any]]:
    """Extract JSON object from model response (may be wrapped in markdown)."""
    if not text or not text.strip():
        return None
    text = text.strip()
    # Remove markdown code block if present
    if "```" in text:
        start = text.find("```")
        if start != -1:
            start = text.find("\n", start) + \
                1 if text.find("\n", start) != -1 else start + 3
            end = text.find("```", start)
            if end != -1:
                text = text[start:end]
    # Find first { and last }
    start_brace = text.find("{")
    if start_brace == -1:
        return None
    depth = 0
    end_brace = -1
    for i in range(start_brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end_brace = i
                break
    if end_brace == -1:
        return None
    try:
        return json.loads(text[start_brace: end_brace + 1])
    except json.JSONDecodeError:
        return None


def extract_from_messages(
    messages: List[Dict[str, Any]],
    user_name: str = "Lokesh",
    max_messages: int = 500,
) -> Dict[str, Any]:
    """
    Use the language model to extract people, facts, and preferences from
    recent conversation. Uses chunked extraction with sliding windows to
    handle large conversation histories without hitting token limits.
    Returns a dict with keys: people, relationships, facts, preferences.
    """
    if not messages or len(messages) < 2:
        return {"people": [], "facts": [], "preferences": {}, "relationships": []}

    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    # ── Chunked extraction: process in windows of WINDOW_SIZE messages ──
    WINDOW_SIZE = 30   # smaller = more granular extraction, fewer tokens per call
    OVERLAP = 5        # overlap between windows for context continuity

    all_people: List[Dict] = []
    all_facts: List[Dict] = []
    all_relationships: List[Dict] = []
    all_preferences: Dict[str, str] = {}

    # Build windows with overlap
    windows = []
    i = 0
    while i < len(recent):
        end = min(i + WINDOW_SIZE, len(recent))
        windows.append(recent[i:end])
        i += WINDOW_SIZE - OVERLAP
        if i >= len(recent):
            break

    print(f"[MemoryExtractor] Processing {len(recent)} messages in {len(windows)} windows...")

    for win_idx, window in enumerate(windows):
        conversation = _messages_to_text(window, user_name)
        if len(conversation.strip()) < 20:
            continue

        prompt = EXTRACTION_PROMPT.replace("{user_name}", user_name).replace("{conversation}", conversation)

        text = ""
        for model_name in _EXTRACTOR_MODELS:
            try:
                client = _get_client()
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=2048,
                    ),
                )
                if hasattr(response, "text") and response.text:
                    text = response.text
                elif getattr(response, "candidates", None) and len(response.candidates) > 0:
                    c = response.candidates[0]
                    if getattr(c, "content", None) and getattr(c.content, "parts", None) and c.content.parts:
                        text = getattr(c.content.parts[0], "text", None) or ""
                if text:
                    break  # success — stop trying fallback models
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    print(f"[MemoryExtractor] {model_name} quota exhausted, trying next model...")
                    time.sleep(1)
                    continue
                print(f"[MemoryExtractor] Window {win_idx + 1} error ({model_name}): {e}")
                break

        if not text:
            print(f"[MemoryExtractor] Window {win_idx + 1}: all models failed or returned empty, skipping.")
            continue

        parsed = _parse_json_from_response(text)
        if not parsed:
            continue

        # Merge window results
        for p in (parsed.get("people", []) if isinstance(parsed.get("people"), list) else []):
            name = (p.get("name") or "").strip().lower()
            if name and not any(ep.get("name", "").strip().lower() == name for ep in all_people):
                all_people.append(p)

        for r in (parsed.get("relationships", []) if isinstance(parsed.get("relationships"), list) else []):
            all_relationships.append(r)

        for f in (parsed.get("facts", []) if isinstance(parsed.get("facts"), list) else []):
            fact_text = (f.get("fact") or "").strip().lower()
            if fact_text and not any(ef.get("fact", "").strip().lower() == fact_text for ef in all_facts):
                all_facts.append(f)

        for k, v in (parsed.get("preferences", {}) if isinstance(parsed.get("preferences"), dict) else {}).items():
            if k and v is not None:
                all_preferences[k] = v

        print(f"[MemoryExtractor] Window {win_idx + 1}/{len(windows)}: +{len(parsed.get('people', []))}p, +{len(parsed.get('facts', []))}f")
        # Small pause between windows to respect rate limits
        if win_idx < len(windows) - 1:
            time.sleep(0.5)

    print(f"[MemoryExtractor] Total extracted: {len(all_people)} people, {len(all_facts)} facts, {len(all_preferences)} prefs, {len(all_relationships)} rels")

    return {
        "people": all_people,
        "relationships": all_relationships,
        "facts": all_facts,
        "preferences": all_preferences,
    }
