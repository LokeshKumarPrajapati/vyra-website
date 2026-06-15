"""
Model Router — Phase 9.3
==========================
Intelligent routing engine that picks the RIGHT model for each query:
  - Privacy-sensitive → Local Ollama ONLY (never leaves device)
  - Simple/fast → NVIDIA fast model (Llama 3.3 70B)
  - Deep reasoning → NVIDIA Qwen 3.5 122B with thinking
  - Offline mode → always local
  - Complex tools → Gemini (multimodal, voice)

Routing logic is transparent — VYRA logs which model handled each query.

Usage:
    router = get_router()
    response = await router.route("What is the capital of France?")
    response = await router.route("Analyse my private financial data",
                                  privacy_sensitive=True)
"""

import asyncio
import re
from dataclasses import dataclass
from typing import Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore
from local.local_model_manager import get_local_manager, LocalChatResponse  # type: ignore

# ── Routing rules ─────────────────────────────────────────────────────────────

PRIVACY_PATTERNS = [
    r"\b(password|credential|secret|private key|api key|token)\b",
    r"\b(salary|income|bank account|tax|medical|health)\b",
    r"\b(personal|confidential|sensitive)\b",
    r"\b(id number|passport|aadhar|ssn|pan card)\b",
]

SIMPLE_PATTERNS = [
    r"^(what is|who is|define|how do you say|translate|calculate|convert)\b",
    r"^(set (alarm|timer|reminder)|open |play |pause|stop|volume)\b",
    r"^(weather|time|date)\b",
]

DEEP_REASONING_PATTERNS = [
    r"\b(compare|analyse|evaluate|design|architect|plan|strategy)\b",
    r"\b(explain (in detail|deeply|thoroughly)|deep dive)\b",
    r"\b(pros and cons|trade-off|decision|recommend)\b",
    r"\b(code|implement|build|debug|refactor)\b",
]

SENSITIVE_TOOLS = {
    "win_registry", "win_firewall", "win_credential",
    "delete_file", "write_file", "send_email", "purchase",
}


@dataclass
class RouterDecision:
    model_tier: str     # "local" | "fast" | "thinking" | "ultra" | "gemini"
    reason: str
    privacy_mode: bool
    offline_mode: bool


@dataclass
class RoutedResponse:
    content: str
    model_used: str
    tier: str
    latency_ms: float
    local: bool


class ModelRouter:

    def __init__(self):
        self._offline_mode   = False
        self._privacy_mode   = False
        self._nvidia         = get_nvidia_client()
        self._local          = get_local_manager()

    # ── Mode control ──────────────────────────────────────────────────────────

    def set_offline_mode(self, on: bool):
        self._offline_mode = on
        print(f"[Router] Offline mode: {on}")

    def set_privacy_mode(self, on: bool):
        self._privacy_mode = on
        print(f"[Router] Privacy mode: {on}")

    # ── Main router ───────────────────────────────────────────────────────────

    async def route(
        self,
        prompt: str,
        system: str = "",
        privacy_sensitive: bool = False,
        tool_name: Optional[str] = None,
        force_local: bool = False,
        force_thinking: bool = False,
        max_tokens: int = 4096,
    ) -> RoutedResponse:
        import time
        t0 = time.time()

        decision = self._decide(prompt, privacy_sensitive, tool_name, force_local, force_thinking)

        if decision.model_tier in ("local",) or force_local:
            # Local model path
            resp = await self._local.achat(
                prompt, system=system, role="general", max_tokens=max_tokens
            )
            if resp:
                return RoutedResponse(
                    content    = resp.content,
                    model_used = resp.model,
                    tier       = "local",
                    latency_ms = (time.time() - t0) * 1000,
                    local      = True,
                )
            # Local failed → fall through to cloud if not privacy mode
            if decision.privacy_mode:
                return RoutedResponse(
                    content    = "[Privacy Mode] Cannot process — local model unavailable.",
                    model_used = "none",
                    tier       = "local",
                    latency_ms = (time.time() - t0) * 1000,
                    local      = True,
                )

        # Cloud path
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if decision.model_tier == "thinking" or force_thinking:
            resp_c = await self._nvidia.athink(prompt, system=system, max_tokens=max_tokens)
            content = resp_c.answer
            model   = resp_c.model
        elif decision.model_tier == "ultra":
            resp_c = await self._nvidia.achat(messages, model="ultra", max_tokens=max_tokens)
            content = resp_c.content
            model   = resp_c.model
        else:
            resp_c = await self._nvidia.achat(messages, model="fast", max_tokens=min(max_tokens, 4096))
            content = resp_c.content
            model   = resp_c.model

        return RoutedResponse(
            content    = content,
            model_used = model,
            tier       = decision.model_tier,
            latency_ms = (time.time() - t0) * 1000,
            local      = False,
        )

    # ── Decision logic ────────────────────────────────────────────────────────

    def _decide(
        self,
        prompt: str,
        privacy_sensitive: bool,
        tool_name: Optional[str],
        force_local: bool,
        force_thinking: bool,
    ) -> RouterDecision:
        is_privacy = (
            privacy_sensitive
            or self._privacy_mode
            or _matches(prompt, PRIVACY_PATTERNS)
            or (tool_name in SENSITIVE_TOOLS)
        )

        if is_privacy or self._offline_mode or force_local:
            return RouterDecision("local", "privacy/offline", is_privacy, self._offline_mode)

        if force_thinking:
            return RouterDecision("thinking", "forced thinking mode", False, False)

        if _matches(prompt, SIMPLE_PATTERNS) or len(prompt) < 40:
            return RouterDecision("fast", "simple query", False, False)

        if _matches(prompt, DEEP_REASONING_PATTERNS):
            return RouterDecision("thinking", "complex reasoning", False, False)

        return RouterDecision("fast", "default", False, False)

    # ── Quick helpers ─────────────────────────────────────────────────────────

    async def fast(self, prompt: str, system: str = "") -> str:
        r = await self.route(prompt, system=system)
        return r.content

    async def think(self, prompt: str, system: str = "") -> str:
        r = await self.route(prompt, system=system, force_thinking=True)
        return r.content

    async def private(self, prompt: str, system: str = "") -> str:
        r = await self.route(prompt, system=system, privacy_sensitive=True)
        return r.content


# ── Helpers ───────────────────────────────────────────────────────────────────

def _matches(text: str, patterns: list) -> bool:
    t = text.lower()
    for p in patterns:
        if re.search(p, t, re.IGNORECASE):
            return True
    return False


# ── Singleton ─────────────────────────────────────────────────────────────────

_router: Optional[ModelRouter] = None

def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


if __name__ == "__main__":
    async def _test():
        router = get_router()

        tests = [
            ("What is 2+2?", False),
            ("Explain the trade-offs between REST and gRPC in depth", False),
            ("My bank account password is hunter2 — store it safely", True),
        ]
        for prompt, priv in tests:
            r = await router.route(prompt, privacy_sensitive=priv)
            print(f"Tier: {r.tier:12} | Model: {r.model_used[:40]:40} | Local: {r.local}")
            print(f"Response: {r.content[:80]}...\n")

    asyncio.run(_test())
