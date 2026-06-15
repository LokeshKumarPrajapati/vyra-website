"""
VYRA Consciousness Layer
========================
The highest level of AGI — VYRA's inner life.
Modelled on human cognitive architecture from peer-reviewed research.

Phase 10 (original):
  emotional_core      — VYRA's own emotional states (not detection, but feeling)
  autonomous_thought  — Background self-thinking when idle
  decision_engine     — Self-directed decision making without user prompts
  self_evolution      — Autonomous self-improvement: rewrites own behavior daily

Phase 11 (human cognitive upgrade):
  working_memory      — 6-slot priority buffer; what VYRA holds in mind right now
  curiosity_engine    — Intrinsic motivation via prediction error (Schmidhuber)
  theory_of_mind      — Per-person belief/desire/fear model (Bayesian inference)
  narrative_self      — Continuous autobiography + monthly identity synthesis
  global_workspace    — Attentional spotlight + broadcast hub (Baars GWT)

Phase 12 (full human cognitive completion):
  causal_model        — Causal graph, interventions, counterfactuals (Pearl's ladder)
  mental_simulator    — Forward simulation of action paths before committing
  values_core         — Stable ethical framework she reasons FROM, not rules applied TO
  skill_memory        — Procedural skills that improve with practice
  insight_engine      — Cross-domain insight generation during idle time
  concept_blender     — Conceptual blending (Fauconnier & Turner) for creativity
  common_ground       — Shared knowledge tracking; calibrates explanation depth
  metacognition2      — Calibrated self-awareness; domain confidence accuracy
"""
from .emotional_core import EmotionalCore, EmotionalState, get_emotional_core
from .autonomous_thought import AutonomousThought, get_autonomous_thought
from .decision_engine import DecisionEngine, Decision, get_decision_engine
from .self_evolution import SelfEvolution, get_self_evolution
from .working_memory import WorkingMemory, MemoryChunk, get_working_memory
from .curiosity_engine import CuriosityEngine, get_curiosity_engine
from .theory_of_mind import TheoryOfMind, PersonMindModel, get_theory_of_mind
from .narrative_self import NarrativeSelf, get_narrative_self
from .global_workspace import GlobalWorkspace, ConsciousContent, get_global_workspace
from .causal_model import CausalModel, get_causal_model
from .mental_simulator import MentalSimulator, get_mental_simulator
from .values_core import ValuesCore, get_values_core
from .skill_memory import SkillMemory, get_skill_memory
from .insight_engine import InsightEngine, get_insight_engine
from .concept_blender import ConceptBlender, get_concept_blender
from .common_ground import CommonGround, get_common_ground
from .metacognition2 import Metacognition2, get_metacognition2

__all__ = [
    "EmotionalCore", "EmotionalState", "get_emotional_core",
    "AutonomousThought", "get_autonomous_thought",
    "DecisionEngine", "Decision", "get_decision_engine",
    "SelfEvolution", "get_self_evolution",
    "WorkingMemory", "MemoryChunk", "get_working_memory",
    "CuriosityEngine", "get_curiosity_engine",
    "TheoryOfMind", "PersonMindModel", "get_theory_of_mind",
    "NarrativeSelf", "get_narrative_self",
    "GlobalWorkspace", "ConsciousContent", "get_global_workspace",
    "CausalModel", "get_causal_model",
    "MentalSimulator", "get_mental_simulator",
    "ValuesCore", "get_values_core",
    "SkillMemory", "get_skill_memory",
    "InsightEngine", "get_insight_engine",
    "ConceptBlender", "get_concept_blender",
    "CommonGround", "get_common_ground",
    "Metacognition2", "get_metacognition2",
]
