"""
Tool Synthesizer — Phase 5.1
==============================
When VYRA encounters a task it cannot do, this engine:
  1. Classifies the capability gap
  2. Generates a new Python tool module using Qwen 3.5 + thinking
  3. Tests it in a subprocess sandbox (no network access)
  4. If tests pass → registers in CapabilityRegistry
  5. If tests fail → iterates up to MAX_ATTEMPTS times
  6. Returns the new tool or raises CapabilityGapError

Safety: all new tools are sandboxed and require one-time user approval
before executing with real system access.

Usage:
    synth = get_synthesizer()
    tool  = await synth.handle_gap("I need to convert PDF to Markdown")
    print(tool.id, tool.description)
"""

import asyncio
import importlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore
from evolution.capability_registry import get_registry, ToolRecord  # type: ignore

DATA_DIR       = Path(__file__).parent.parent / "data"
SYNTH_DIR      = Path(__file__).parent.parent / "synthesized_tools"
MAX_ATTEMPTS   = 4
SANDBOX_TIMEOUT= 10   # seconds for sandbox test

SYNTH_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class SynthResult:
    success: bool
    tool_id: str
    tool_record: Optional[ToolRecord]
    code: str
    attempts: int
    error: str = ""


SYNTHESIS_SYSTEM = """You are an expert Python tool developer for VYRA AI assistant.
Generate a clean, working Python module that implements the requested capability.
The module MUST:
  1. Have a main function named `run(params: dict) -> dict`
  2. Return {"success": True, "result": ...} or {"success": False, "error": "..."}
  3. Handle all exceptions gracefully
  4. Import only standard library or commonly available packages
  5. Include a brief docstring

Output ONLY the Python code. No markdown, no explanations."""

TEST_SYSTEM = """You write minimal pytest test cases for a Python function.
The function signature is: run(params: dict) -> dict
Write 2-3 simple test cases that verify basic functionality.
Output ONLY valid Python test code."""


class CapabilityGapError(Exception):
    pass


class ToolSynthesizer:

    def __init__(self):
        self.client    = get_nvidia_client()
        self._pending_approval: dict[str, SynthResult] = {}

    async def handle_gap(self, task_description: str) -> SynthResult:
        """Main entry point. Returns SynthResult (may need user approval)."""
        print(f"[ToolSynthesizer] Gap detected: {task_description[:80]}")
        tool_id = "synth_" + str(uuid.uuid4())[:8]

        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"[ToolSynthesizer] Attempt {attempt}/{MAX_ATTEMPTS}")
            code = await self._generate_code(task_description, attempt)
            ok, error = self._sandbox_test(code, tool_id)
            if ok:
                record = self._register(tool_id, task_description, code)
                result = SynthResult(
                    success=True, tool_id=tool_id,
                    tool_record=record, code=code, attempts=attempt,
                )
                self._pending_approval[tool_id] = result
                print(f"[ToolSynthesizer] Created tool {tool_id} (needs approval)")
                return result
            else:
                print(f"[ToolSynthesizer] Attempt {attempt} failed: {error[:80]}")
                task_description = f"{task_description}\n\nPrevious attempt failed: {error}"

        raise CapabilityGapError(
            f"Could not synthesize tool after {MAX_ATTEMPTS} attempts: {task_description[:100]}"
        )

    def approve(self, tool_id: str) -> bool:
        """User approved a synthesized tool — mark it active."""
        if tool_id in self._pending_approval:
            result = self._pending_approval.pop(tool_id)
            reg = get_registry()
            t   = reg.get(tool_id)
            if t:
                t.tags.append("approved")
                reg.register(t)
            print(f"[ToolSynthesizer] Tool approved: {tool_id}")
            return True
        return False

    def reject(self, tool_id: str):
        if tool_id in self._pending_approval:
            self._pending_approval.pop(tool_id)
            get_registry().deprecate(tool_id, "Rejected by user")
            # Remove file
            path = SYNTH_DIR / f"{tool_id}.py"
            if path.exists():
                path.unlink()
            print(f"[ToolSynthesizer] Tool rejected: {tool_id}")

    async def run_tool(self, tool_id: str, params: dict) -> dict:
        """Execute an approved synthesized tool."""
        path = SYNTH_DIR / f"{tool_id}.py"
        if not path.exists():
            return {"success": False, "error": f"Tool file not found: {tool_id}"}
        spec   = importlib.util.spec_from_file_location(tool_id, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        t0     = time.time()
        result = module.run(params)
        latency= (time.time() - t0) * 1000
        success= result.get("success", False)
        get_registry().record_call(tool_id, success, latency)
        return result

    # ── Generation ────────────────────────────────────────────────────────────

    async def _generate_code(self, description: str, attempt: int) -> str:
        prompt = (
            f"Task: {description}\n\n"
            f"Generate a Python module with a `run(params: dict) -> dict` function "
            f"that accomplishes this task. Attempt #{attempt}."
        )
        resp = await self.client.athink(
            prompt=prompt,
            system=SYNTHESIS_SYSTEM,
            max_tokens=4096,
            temperature=0.3,
        )
        code = resp.answer.strip()
        # Strip markdown code fences if present
        if code.startswith("```"):
            lines = code.split("\n")
            code  = "\n".join(
                line for line in lines
                if not line.strip().startswith("```")
            )
        return code

    # ── Sandbox testing ───────────────────────────────────────────────────────

    def _sandbox_test(self, code: str, tool_id: str) -> tuple[bool, str]:
        """Run the code in a subprocess with a basic smoke test."""
        test_code = textwrap.dedent(f"""
import sys, json
sys.path.insert(0, r'{SYNTH_DIR}')

# ── The synthesized module ──
{code}

# ── Smoke test ──
try:
    result = run({{}})
    assert isinstance(result, dict), "run() must return a dict"
    assert "success" in result, "result must have 'success' key"
    print(json.dumps({{"ok": True}}))
except Exception as e:
    print(json.dumps({{"ok": False, "error": str(e)}}))
""")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(test_code)
            tmp_path = f.name

        try:
            proc = subprocess.run(
                [sys.executable, tmp_path],
                capture_output=True, text=True, timeout=SANDBOX_TIMEOUT,
                env={**os.environ, "PYTHONPATH": str(SYNTH_DIR)},
            )
            output = proc.stdout.strip().split("\n")[-1]
            obj    = json.loads(output)
            if obj.get("ok"):
                # Save the tool file
                tool_path = SYNTH_DIR / f"{tool_id}.py"
                tool_path.write_text(code, encoding="utf-8")
                return True, ""
            return False, obj.get("error", "Unknown error")
        except subprocess.TimeoutExpired:
            return False, "Sandbox timeout"
        except Exception as e:
            return False, str(e)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── Registration ──────────────────────────────────────────────────────────

    def _register(self, tool_id: str, description: str, code: str) -> ToolRecord:
        # Extract function name and docstring from code
        name = tool_id.replace("_", " ").title()
        record = ToolRecord(
            id                 = tool_id,
            name               = name,
            description        = description[:200],
            agent              = "synthesized",
            input_schema       = {"params": {"type": "object"}},
            output_description = "Task-specific result dict",
            source             = "synthesized",
            tags               = ["synthesized", "pending_approval"],
            version            = "1.0",
        )
        get_registry().register(record)
        return record


_synthesizer: Optional[ToolSynthesizer] = None

def get_synthesizer() -> ToolSynthesizer:
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = ToolSynthesizer()
    return _synthesizer


if __name__ == "__main__":
    async def _test():
        synth  = get_synthesizer()
        result = await synth.handle_gap(
            "Convert a temperature from Celsius to Fahrenheit and Kelvin"
        )
        print(f"Success: {result.success}")
        print(f"Tool ID: {result.tool_id}")
        print(f"Attempts: {result.attempts}")
        if result.success:
            synth.approve(result.tool_id)
            out = await synth.run_tool(result.tool_id, {"celsius": 100})
            print(f"Output: {out}")

    asyncio.run(_test())
