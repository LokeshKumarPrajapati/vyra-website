"""
cursor_intelligence.py
Vyra Cursor Intelligence — FastAPI route module

Exposes:
  GET  /cursor/hover           — lightweight hover (x,y only, pywinauto element detection)
  POST /cursor/analyze         — heavy analysis with screenshot (on-demand only)
  POST /cursor/analyze-region  — detailed analysis for Alt+Drag region
  POST /cursor/action          — execute a cursor action (Summarize, Explain, etc.)
  GET  /cursor/clipboard       — get clipboard history with smart type detection
  POST /cursor/workflow/log    — log a user action for workflow detection
  GET  /cursor/workflow/detect — detect repeating workflow patterns
"""

import asyncio
import base64
import json
import os
import time
from collections import deque
from typing import Optional, List

from fastapi import APIRouter, Query
from pydantic import BaseModel

from actions.context_detector import detect_context, analyze_region, get_element_at, detect_from_element_info, DEFAULT_ACTIONS

router = APIRouter(prefix="/cursor", tags=["cursor-intelligence"])

# ── /cursor/hover — ultra-lightweight, called at 600ms debounce, NO AI, NO screenshot ──
@router.get("/hover")
async def hover_detect(x: int = Query(...), y: int = Query(...)):
    """
    Fast element detection using only Win32/pywinauto.
    No screen capture, no AI — responds in < 5ms.
    Returns 'unknown' if nothing interesting detected (overlay stays hidden).
    """
    element = get_element_at(x, y)
    result  = detect_from_element_info(element)

    if result and result.get('type') not in ('unknown', None):
        return {**result, 'x': x, 'y': y, 'source': 'win32_fast'}

    return {'type': 'unknown'}

# ── Pydantic models ───────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    x:     int
    y:     int
    image: Optional[str] = None   # base64 PNG

class RegionAnalyzeRequest(BaseModel):
    x:     int
    y:     int
    image: str                    # base64 PNG (required for region)

class ActionRequest(BaseModel):
    action:  str
    context: dict = {}
    text:    Optional[str] = None
    image:   Optional[str] = None

class WorkflowLogRequest(BaseModel):
    action:    str
    target:    Optional[str] = None
    app:       Optional[str] = None
    timestamp: Optional[float] = None


# ── In-memory workflow log (ring buffer) ─────────────────────────────────────
_workflow_log: deque = deque(maxlen=200)


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/analyze")
async def analyze_cursor(req: AnalyzeRequest):
    """
    Called every time the cursor hovers for > 300ms.
    Returns context classification for the screen region.
    """
    result = await detect_context(req.x, req.y, req.image)

    # Don't surface 'unknown' to the overlay — save the API call cost
    if result.get('type') == 'unknown' or result.get('confidence', 0) < 0.4:
        return {"type": "unknown"}

    return result


@router.post("/analyze-region")
async def analyze_cursor_region(req: RegionAnalyzeRequest):
    """
    Called when user Alt+Drags a region.
    Returns a detailed natural-language analysis.
    """
    result = await analyze_region(req.image, req.x, req.y)
    return result


@router.post("/action")
async def execute_action(req: ActionRequest):
    """
    Execute a cursor intelligence action by forwarding to the main Vyra pipeline.
    Actions like 'Summarize', 'Explain Code', 'Translate', etc.
    """
    # Build a natural language prompt from the action + context
    prompt = _build_action_prompt(req.action, req.context, req.text)

    # Import the Vyra core to process the prompt
    try:
        import vyra
        # Use Vyra's text generation pipeline
        result = await vyra.process_text_query(prompt)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e), "prompt": prompt}


@router.get("/clipboard")
async def get_clipboard():
    """Get current clipboard content with type detection."""
    try:
        import pyperclip
        content = pyperclip.paste()
        if not content:
            return {"type": "empty", "content": ""}

        ctx_type = _classify_clipboard(content)
        return {
            "type":    ctx_type,
            "content": content[:500],   # cap at 500 chars for safety
            "full":    content,
        }
    except Exception as e:
        return {"type": "error", "error": str(e)}


@router.post("/workflow/log")
async def log_workflow_action(req: WorkflowLogRequest):
    """Log a cursor action for workflow pattern detection."""
    _workflow_log.append({
        "action":    req.action,
        "target":    req.target,
        "app":       req.app,
        "timestamp": req.timestamp or time.time(),
    })
    return {"logged": True, "total": len(_workflow_log)}


@router.get("/workflow/detect")
async def detect_workflow_patterns():
    """Detect repeating patterns in the logged actions."""
    if len(_workflow_log) < 6:
        return {"patterns": [], "message": "Not enough data yet"}

    # Simple n-gram pattern detection
    actions = [e["action"] for e in _workflow_log]
    patterns = _find_patterns(actions)

    return {
        "patterns": patterns[:3],  # top 3 patterns
        "log_size": len(_workflow_log),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_action_prompt(action: str, context: dict, text: Optional[str]) -> str:
    """Convert a cursor action into a Vyra-compatible prompt."""
    ctx_type = context.get("type", "")
    label    = context.get("label", "")

    prompts = {
        "Summarize":        f"Summarize this {ctx_type}: {label or text or '(screen content)'}",
        "Explain":          f"Explain this clearly: {text or label}",
        "Explain Code":     f"Explain this code: {text or label}",
        "Review Code":      f"Review this code for issues: {text or label}",
        "Optimize":         f"Optimize this code: {text or label}",
        "Generate Tests":   f"Generate unit tests for: {text or label}",
        "Rewrite":          f"Rewrite this more clearly: {text or ''}",
        "Translate":        f"Translate this to English: {text or ''}",
        "Analyze Image":    f"Analyze the image: {label}",
        "Extract Text":     f"Extract all text from: {label}",
        "Improve Quality":  f"Suggest improvements for: {label}",
        "Ask Questions":    f"Generate insightful questions about: {label or text}",
        "Extract Tasks":    f"Extract actionable tasks from: {label or text}",
        "Create Task":      f"Create a task for: {text or label}",
        "Fix Grammar":      f"Fix grammar in: {text}",
        "Make Formal":      f"Make this more formal: {text}",
        "Make Casual":      f"Make this more casual: {text}",
        "Extract Key Points": f"Extract key points from: {text or label}",
        "Create Task":      f"Create a task for: {label or text}",
        "Summarize Page":   f"Summarize the web page: {label}",
    }

    return prompts.get(action, f"{action}: {text or label or 'current screen content'}")


def _classify_clipboard(content: str) -> str:
    """Classify clipboard content type."""
    stripped = content.strip()
    if stripped.startswith(('http://', 'https://', 'www.')):
        return 'url'
    # Code heuristics
    code_indicators = ['def ', 'function ', 'const ', 'import ', 'class ', '() =>', '#!/', '<div', 'SELECT ']
    if any(ind in stripped for ind in code_indicators):
        return 'code'
    if len(stripped) > 200:
        return 'text'
    return 'text'


def _find_patterns(actions: List[str], min_len: int = 2, min_repeat: int = 2) -> List[dict]:
    """Find repeating n-gram patterns in an action sequence."""
    patterns = {}
    n = len(actions)

    for size in range(min_len, min(6, n // 2 + 1)):
        for i in range(n - size):
            gram = tuple(actions[i:i + size])
            count = 0
            for j in range(n - size):
                if tuple(actions[j:j + size]) == gram:
                    count += 1
            if count >= min_repeat:
                key = str(gram)
                if key not in patterns or patterns[key]['count'] < count:
                    patterns[key] = {
                        'actions': list(gram),
                        'count':   count,
                        'label':   ' → '.join(gram),
                    }

    return sorted(patterns.values(), key=lambda p: p['count'], reverse=True)
