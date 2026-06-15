"""
Agent Mesh — Phase 6.1
========================
VYRA's multi-agent orchestrator. Receives a complex task, decomposes it,
dispatches to specialist agents in parallel, synthesizes results.

Specialist agents (each runs as an async coroutine):
  - ResearchAgent  : multi-source web research + synthesis
  - CodeAgent      : code generation, execution, debugging
  - DataAgent      : data analysis, charts, statistics
  - CommsAgent     : email, calendar, messaging
  - SystemAgent    : Windows OS control wrapper

All agents communicate via the MessageBus and report back to AgentMesh
(the conductor) which synthesizes the final response.

Usage:
    mesh   = get_mesh()
    result = await mesh.run(
        task="Research the top 5 AI chips of 2025 and create a comparison chart",
        context="User is a hardware investor",
    )
    print(result.synthesis)     # final combined answer
    print(result.agent_results) # per-agent raw outputs
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore
from agents.message_bus import get_bus, AgentMessage  # type: ignore

# ── Result data class ─────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    agent: str
    task: str
    output: str
    success: bool
    latency_ms: float
    error: str = ""

@dataclass
class MeshResult:
    original_task: str
    synthesis: str                        # final combined answer
    agent_results: List[AgentResult]
    total_latency_ms: float
    agents_used: List[str]
    parallel: bool = True


# ── Specialist agent stubs ────────────────────────────────────────────────────
# Each agent runs a focused LLM call with its own system prompt + tools.
# Full implementations live in research/, social/, etc.

AGENT_SYSTEM_PROMPTS = {
    "research": (
        "You are a research specialist. Find factual, well-sourced information. "
        "Be specific, cite sources when possible, flag uncertainty."
    ),
    "code": (
        "You are a software engineering specialist. Write clean, working code. "
        "Explain your implementation. Prefer Python unless specified."
    ),
    "data": (
        "You are a data analysis specialist. Perform rigorous analysis, "
        "suggest appropriate visualisations, explain findings clearly."
    ),
    "comms": (
        "You are a communication specialist. Draft professional, contextual messages. "
        "Be concise and appropriate for the relationship type."
    ),
    "system": (
        "You are a system administration specialist for Windows. "
        "Provide safe, reversible commands. Warn about risks."
    ),
}

DECOMPOSE_SYSTEM = """You are VYRA's task decomposition engine.
Break complex tasks into parallel sub-tasks for specialist agents.
Output valid JSON only.
Available agents: research, code, data, comms, system
Rule: only use agents that are actually needed for this specific task."""


class AgentMesh:

    def __init__(self):
        self.client = get_nvidia_client()

    async def run(
        self,
        task: str,
        context: str = "",
        max_agents: int = 4,
        parallel: bool = True,
    ) -> MeshResult:
        t0 = time.time()

        # 1. Decompose task into agent assignments
        assignments = await self._decompose(task, context, max_agents)

        if not assignments:
            # Fallback: single agent (VYRA core)
            result = await self._run_agent("research", task, context)
            return MeshResult(
                original_task   = task,
                synthesis       = result.output,
                agent_results   = [result],
                total_latency_ms= (time.time() - t0) * 1000,
                agents_used     = ["research"],
                parallel        = False,
            )

        # 2. Execute agents (parallel or sequential)
        if parallel:
            agent_results = await asyncio.gather(*[
                self._run_agent(a["agent"], a["sub_task"], context)
                for a in assignments
            ])
        else:
            agent_results = []
            for a in assignments:
                r = await self._run_agent(a["agent"], a["sub_task"], context)
                agent_results.append(r)

        # 3. Synthesise results into one coherent answer
        synthesis = await self._synthesise(task, list(agent_results))

        return MeshResult(
            original_task    = task,
            synthesis        = synthesis,
            agent_results    = list(agent_results),
            total_latency_ms = (time.time() - t0) * 1000,
            agents_used      = list({r.agent for r in agent_results}),
            parallel         = parallel,
        )

    # ── Decomposition ─────────────────────────────────────────────────────────

    async def _decompose(
        self, task: str, context: str, max_agents: int
    ) -> List[Dict[str, str]]:
        prompt = (
            f"Task: {task}\n"
            f"Context: {context or 'none'}\n"
            f"Max agents to use: {max_agents}\n\n"
            f"Decompose into parallel sub-tasks. Each sub-task should be:\n"
            f"  - Independent (can run in parallel)\n"
            f"  - Assigned to the best specialist agent\n"
            f"  - Specific and actionable\n\n"
            f"JSON array: [{{'agent':'research','sub_task':'...'}}, ...]\n"
            f"Only include agents that are truly needed. Simple tasks may need just 1."
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": DECOMPOSE_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="fast",
                max_tokens=512,
                temperature=0.3,
            )
            raw   = resp.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            items = [
                a for a in __import__("json").loads(raw[start:end])
                if a.get("agent") in AGENT_SYSTEM_PROMPTS
            ]
            return items[:max_agents]
        except Exception:
            return []

    # ── Agent runner ──────────────────────────────────────────────────────────

    async def _run_agent(self, agent: str, sub_task: str, context: str) -> AgentResult:
        t0     = time.time()
        system = AGENT_SYSTEM_PROMPTS.get(agent, AGENT_SYSTEM_PROMPTS["research"])
        prompt = f"Context: {context}\n\nTask: {sub_task}" if context else sub_task

        # Route to real agent if available
        if agent == "research":
            output = await self._call_research_agent(sub_task, context)
        elif agent == "code":
            output = await self._call_code_agent(sub_task, context)
        else:
            # Generic LLM-based agent
            try:
                resp = await self.client.achat(
                    [{"role": "system", "content": system},
                     {"role": "user",   "content": prompt}],
                    model="fast",
                    max_tokens=2048,
                )
                output = resp.content
            except Exception as e:
                return AgentResult(
                    agent=agent, task=sub_task, output="",
                    success=False, latency_ms=(time.time()-t0)*1000, error=str(e)
                )

        return AgentResult(
            agent=agent, task=sub_task, output=output,
            success=bool(output), latency_ms=(time.time()-t0)*1000,
        )

    async def _call_research_agent(self, task: str, context: str) -> str:
        try:
            from research.deep_research_agent import get_research_agent  # type: ignore
            agent  = get_research_agent()
            report = await agent.research(task, context=context)
            return report.synthesis
        except Exception:
            # Fallback to plain LLM
            resp = await self.client.achat(
                [{"role": "system", "content": AGENT_SYSTEM_PROMPTS["research"]},
                 {"role": "user", "content": task}],
                model="thinking",
                max_tokens=4096,
            )
            return resp.content

    async def _call_code_agent(self, task: str, context: str) -> str:
        resp = await self.client.athink(
            prompt=f"Context: {context}\n\nCoding task: {task}",
            system=AGENT_SYSTEM_PROMPTS["code"],
            max_tokens=4096,
        )
        return resp.answer

    # ── Synthesis ─────────────────────────────────────────────────────────────

    async def _synthesise(self, task: str, results: List[AgentResult]) -> str:
        if len(results) == 1:
            return results[0].output

        reports = "\n\n".join(
            f"=== {r.agent.upper()} AGENT ===\n{r.output}"
            for r in results if r.success
        )
        prompt = (
            f"Original task: {task}\n\n"
            f"Specialist agent reports:\n{reports}\n\n"
            f"Synthesise all findings into one comprehensive, well-structured response. "
            f"Integrate insights from all agents. Remove redundancy. "
            f"Present conclusions clearly."
        )
        resp = await self.client.athink(
            prompt=prompt,
            system="You are VYRA's synthesis engine. Create unified, coherent answers from multiple specialist agents.",
            max_tokens=8192,
        )
        return resp.answer


# ── Singleton ─────────────────────────────────────────────────────────────────

_mesh: Optional[AgentMesh] = None

def get_mesh() -> AgentMesh:
    global _mesh
    if _mesh is None:
        _mesh = AgentMesh()
    return _mesh


if __name__ == "__main__":
    async def _test():
        mesh   = get_mesh()
        result = await mesh.run(
            task    = "What are the top 3 Python web frameworks in 2025 and when should I choose each?",
            context = "User is a senior Python developer building a SaaS product",
        )
        print(f"Agents used: {result.agents_used}")
        print(f"Latency: {result.total_latency_ms:.0f}ms")
        print(f"\n=== SYNTHESIS ===\n{result.synthesis}")

    asyncio.run(_test())
