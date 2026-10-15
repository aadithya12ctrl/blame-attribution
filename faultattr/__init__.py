"""
Fault attribution harness.

Public surface used by experiments/. Everything else is reachable through the
submodules directly (faultattr.contracts, faultattr.projection, ...).
"""
from .domain import (Job, Observation, Task, Schedule, SEP_MIN,
                     BUSY, FREE, UNKNOWN, make_task, requirement_violations,
                     R_holds, margin, consumed_margin, exogenous_depletion,
                     task_to_prompt_block)
from .llm import LLM, LLMReply
from .agents import (AGENTS, SYSTEMS, PROMPTS, PROMPT_VERSION, Invocation,
                     Run, run_pipeline)
from .projection import (project_observer, project_analyzer, project_planner,
                         project_validator, project_executor, measure_epsilon,
                         ProjectionError)
from .contracts import CONTRACTS, Contract, Check, ANALYZER_VALIDATES_INPUT
from .attribute import (attribute, evaluate_contracts, format_verdict, Verdict,
                        AgentVerdict, AGENT_FAULT, REPAIRABLE, CORPUS_BLOCKED,
                        INEXPRESSIBLE, NO_FAILURE, UNATTRIBUTABLE)

__all__ = [
    "Job", "Observation", "Task", "Schedule", "SEP_MIN",
    "BUSY", "FREE", "UNKNOWN", "make_task", "requirement_violations",
    "R_holds", "margin", "consumed_margin", "exogenous_depletion",
    "task_to_prompt_block",
    "LLM", "LLMReply",
    "AGENTS", "SYSTEMS", "PROMPTS", "PROMPT_VERSION", "Invocation", "Run",
    "run_pipeline",
    "project_observer", "project_analyzer", "project_planner",
    "project_validator", "project_executor", "measure_epsilon",
    "ProjectionError",
    "CONTRACTS", "Contract", "Check", "ANALYZER_VALIDATES_INPUT",
    "attribute", "evaluate_contracts", "format_verdict", "Verdict",
    "AgentVerdict", "AGENT_FAULT", "REPAIRABLE", "CORPUS_BLOCKED",
    "INEXPRESSIBLE", "NO_FAILURE", "UNATTRIBUTABLE",
]
