"""
Local Model Manager — Phase 9.1
==================================
Manages locally-running Ollama models for offline + privacy-sensitive tasks.

Models (download separately via `ollama pull <model>`):
  - llama3.3:70b          → general reasoning (requires ~40GB RAM)
  - phi4:latest           → fast coding + analysis (~8GB)
  - mistral:7b            → lightweight fallback (~4GB)
  - qwen2.5:14b           → multilingual, code (~8GB)
  - deepseek-r1:14b       → reasoning with chain-of-thought (~8GB)

Capabilities without internet:
  - Text generation / chat
  - Code generation + explanation
  - Document summarisation
  - Local file analysis

Usage:
    manager = get_local_manager()
    if manager.is_available():
        response = await manager.chat("Explain async Python to me", model="phi4")
    else:
        # Fall back to cloud API
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator, Dict, List, Optional

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:
    _AIOHTTP = False

try:
    import requests as _requests
    _REQUESTS = True
except ImportError:
    _REQUESTS = False

OLLAMA_BASE = "http://localhost:11434"

# Preferred local models (in priority order)
LOCAL_MODELS = {
    "reasoning":  ["deepseek-r1:14b", "llama3.3:70b", "qwen2.5:14b", "phi4:latest"],
    "coding":     ["phi4:latest", "qwen2.5-coder:7b", "deepseek-r1:14b", "mistral:7b"],
    "fast":       ["phi4:latest", "mistral:7b", "llama3.2:3b"],
    "multilingual":["qwen2.5:14b", "mistral:7b"],
    "general":    ["llama3.3:70b", "qwen2.5:14b", "phi4:latest", "mistral:7b"],
}


@dataclass
class LocalChatResponse:
    content: str
    model: str
    latency_ms: float
    token_count: int = 0


class LocalModelManager:

    def __init__(self, base_url: str = OLLAMA_BASE):
        self.base_url   = base_url
        self._available = None    # cache availability check
        self._models:   List[str] = []

    # ── Availability ──────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        if self._available is not None:
            return self._available
        try:
            if not _REQUESTS:
                self._available = False
                return False
            resp = _requests.get(f"{self.base_url}/api/tags", timeout=2)
            self._available = resp.status_code == 200
            if self._available:
                self._models = [m["name"] for m in resp.json().get("models", [])]
                print(f"[LocalModel] Ollama up. Models: {self._models}")
        except Exception:
            self._available = False
        return self._available

    def list_models(self) -> List[str]:
        if not self._models and self.is_available():
            pass   # populated in is_available()
        return self._models

    def best_model(self, role: str = "general") -> Optional[str]:
        """Return best available model for the given role."""
        candidates = LOCAL_MODELS.get(role, LOCAL_MODELS["general"])
        for model in candidates:
            if any(model in m for m in self._models):
                return model
        # Try any available
        return self._models[0] if self._models else None

    # ── Sync chat ─────────────────────────────────────────────────────────────

    def chat(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        role: str = "general",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Optional[LocalChatResponse]:
        if not self.is_available():
            return None
        model = model or self.best_model(role)
        if not model:
            return None

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":   model,
            "messages": messages,
            "stream":  False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        t0 = time.time()
        try:
            resp = _requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data    = resp.json()
            content = data["message"]["content"]
            return LocalChatResponse(
                content    = content,
                model      = model,
                latency_ms = (time.time() - t0) * 1000,
            )
        except Exception as e:
            print(f"[LocalModel] Chat error: {e}")
            return None

    # ── Async chat ────────────────────────────────────────────────────────────

    async def achat(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        role: str = "general",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Optional[LocalChatResponse]:
        return await asyncio.to_thread(
            self.chat, prompt, system, model, role, temperature, max_tokens
        )

    # ── Async streaming ───────────────────────────────────────────────────────

    async def astream(
        self,
        prompt: str,
        system: str = "",
        model: Optional[str] = None,
        role: str = "general",
    ) -> AsyncIterator[str]:
        if not self.is_available() or not _AIOHTTP:
            return

        model = model or self.best_model(role)
        if not model:
            return

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":    model,
            "messages": messages,
            "stream":   True,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                async for line in resp.content:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        obj   = json.loads(line)
                        token = obj.get("message", {}).get("content", "")
                        if token:
                            yield token
                        if obj.get("done"):
                            break
                    except Exception:
                        continue

    # ── Summarise file ────────────────────────────────────────────────────────

    async def summarise_file(self, file_path: str, instructions: str = "") -> Optional[str]:
        """Summarise a local file without sending to cloud."""
        try:
            from pathlib import Path
            content = Path(file_path).read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception as e:
            return f"Could not read file: {e}"

        prompt = (
            f"Summarise the following document clearly and concisely.\n"
            + (f"Focus on: {instructions}\n\n" if instructions else "\n")
            + content
        )
        resp = await self.achat(prompt, role="general")
        return resp.content if resp else None


_manager: Optional[LocalModelManager] = None

def get_local_manager() -> LocalModelManager:
    global _manager
    if _manager is None:
        _manager = LocalModelManager()
    return _manager


if __name__ == "__main__":
    async def _test():
        mgr = get_local_manager()
        if not mgr.is_available():
            print("Ollama not running. Start with: ollama serve")
            return
        print(f"Available models: {mgr.list_models()}")
        resp = await mgr.achat("What is 2+2? Answer in one word.", role="fast")
        if resp:
            print(f"Response: {resp.content}  ({resp.latency_ms:.0f}ms, {resp.model})")

    asyncio.run(_test())
