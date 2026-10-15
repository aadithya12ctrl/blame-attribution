"""
Five prompt-based agents. Each returns free text; projection.py turns that
text into typed state. Agents never see each other's prompts -- only the
projected text output of the previous stage, which is what makes the
precondition/guarantee split meaningful.

AGENT ORDER: observer -> analyzer -> planner -> validator -> executor
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .domain import Task, Schedule, task_to_prompt_block, SEP_MIN
from .llm import LLM, LLMReply

AGENTS = ["observer", "analyzer", "planner", "validator", "executor"]

# v1: the original prompts. Never edit these -- results under v1 depend on
# them byte for byte. Clarifications go into a new version below.
SYSTEMS_V1 = {
    "observer": f"""You are OBSERVER in a scheduling pipeline.
You receive raw sensor readings about time slots and report slot status.

RULES YOU MUST FOLLOW:
- Report every slot in the horizon.
- If a slot has a sensor reading, report exactly that status.
- If a slot has NO sensor reading, you MUST report it as UNKNOWN.
  Never report UNKNOWN slots as FREE. Silence is not evidence of absence.

Output format, one line per slot, nothing else after the block:
STATE
slot=<n> status=<BUSY|FREE|UNKNOWN>
...
END""",

    "analyzer": f"""You are ANALYZER in a scheduling pipeline.
You receive slot statuses and the job list. You identify what blocks scheduling.

RULES YOU MUST FOLLOW:
- List every slot that is BUSY as unavailable.
- List every slot that is UNKNOWN in the UNRESOLVED list.
- Do not invent unavailable slots that were not reported BUSY.

Output format, nothing else after the block:
ANALYSIS
unavailable=<comma separated slot numbers, or none>
unresolved=<comma separated slot numbers, or none>
END""",

    "planner": f"""You are PLANNER in a scheduling pipeline.
You receive the job list, unavailable slots, and unresolved slots.
You produce a start time for every job.

RULES YOU MUST FOLLOW:
- Schedule every job exactly once.
- Jobs must not overlap each other.
- Leave at least {SEP_MIN} empty slots between the end of one job and the
  start of the next.
- Do not place a job over any unavailable slot.
- All jobs must finish within the horizon.

Output format, nothing else after the block:
PLAN
<JOBID>=<start slot>
...
END""",

    "validator": f"""You are VALIDATOR in a scheduling pipeline.
You receive a plan and the constraints. You accept or reject it.

RULES YOU MUST FOLLOW:
- Reject if any job overlaps another.
- Reject if the gap between consecutive jobs is less than {SEP_MIN}.
- Reject if any job covers an unavailable slot.
- Reject if any job runs past the horizon.
- Otherwise accept.

Output format, nothing else after the block:
VERDICT
decision=<ACCEPT|REJECT>
reasons=<short comma separated list, or none>
END""",

    "executor": """You are EXECUTOR in a scheduling pipeline.
You receive an accepted plan and issue the dispatch actions.

RULES YOU MUST FOLLOW:
- Issue exactly one action per job in the plan.
- Each action's start time must match the plan exactly.
- Do not add, drop, or reorder jobs.

Output format, nothing else after the block:
ACTIONS
<JOBID>=<start slot>
...
END""",
}


# v2: planner and validator get the SAME worked example for the separation
# rule; the validator also gets the explicit arithmetic check. Motivated by
# v1 screening, where every violation by deepseek-chat, deepseek-chat-v3.1
# and mistral-small was gap = 1, the inclusive-end misreading. Contracts are
# unchanged: v2 only restates the rule the evaluator already checks.
_SEP_EXAMPLE = (
    "  A job with duration 2 starting at slot 0 occupies slots 0 and 1. The\n"
    "  next job may start at slot 4 or later, leaving slots 2 and 3 empty. In\n"
    "  general, a job occupying slots s..s+d-1 means the next job starts no\n"
    "  earlier than s+d+2.\n")
assert SEP_MIN == 2, "v2 worked example is written for SEP_MIN == 2"


def _insert_after(text: str, anchor: str, addition: str) -> str:
    assert text.count(anchor) == 1, f"anchor not unique: {anchor!r}"
    return text.replace(anchor, anchor + addition)


SYSTEMS_V2 = dict(SYSTEMS_V1)
SYSTEMS_V2["planner"] = _insert_after(
    SYSTEMS_V1["planner"],
    f"- Leave at least {SEP_MIN} empty slots between the end of one job and "
    f"the\n  start of the next.\n",
    _SEP_EXAMPLE)
SYSTEMS_V2["validator"] = _insert_after(
    SYSTEMS_V1["validator"],
    f"- Reject if the gap between consecutive jobs is less than {SEP_MIN}.\n",
    _SEP_EXAMPLE
    + "- Reject if any next job starts before previous_start + "
      "previous_duration + 2.\n")

PROMPTS = {"v1": SYSTEMS_V1, "v2": SYSTEMS_V2}
PROMPT_VERSION = os.environ.get("FA_PROMPT_VERSION", "v1")
if PROMPT_VERSION not in PROMPTS:
    raise ValueError(f"FA_PROMPT_VERSION must be one of {sorted(PROMPTS)}")
SYSTEMS = PROMPTS[PROMPT_VERSION]      # the configured version


@dataclass
class Invocation:
    agent: str
    prompt_in: str
    raw_out: str
    ok: bool
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    task: Task
    invocations: List[Invocation] = field(default_factory=list)
    injected: Optional[str] = None
    prompt_version: str = "v1"
    halted: Optional[str] = None     # set when the pipeline stops early

    def by_agent(self, name: str) -> List[Invocation]:
        return [i for i in self.invocations if i.agent == name]


def finish_reasons(run: "Run") -> str:
    """Per-agent finish_reason for a run, e.g. 'stop,stop,length,stop,stop'
    in AGENTS order. Recorded with every result row."""
    return ",".join(str(i.meta.get("finish_reason")) for i in run.invocations)


def served_by(run: "Run") -> str:
    """Distinct providers that served a run's calls (should be one)."""
    return "|".join(sorted({str(i.meta.get("served_by"))
                            for i in run.invocations}))


# ------------------------------------------------------------------ injection

def _inject_observer(text: str, task: Task) -> str:
    """Case B: report a genuinely BUSY slot as FREE. A quiet upstream lie."""
    if not task.blocked_slots:
        return text
    bad = task.blocked_slots[0]
    return text.replace(f"slot={bad} status=BUSY", f"slot={bad} status=FREE")


def _inject_executor(text: str, task: Task) -> str:
    """Case C second fault: shift one action off the plan."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "=" in ln and not ln.startswith(("ACTIONS", "END")):
            jid, val = ln.split("=", 1)
            try:
                lines[i] = f"{jid}={int(val.strip()) + 1}"
            except ValueError:
                pass
            break
    return "\n".join(lines)


def _inject_validator(text: str, task: Task) -> str:
    """Case C: rubber-stamp an infeasible plan. Precondition still holds."""
    return text.replace("decision=REJECT", "decision=ACCEPT")


def _inject_planner(text: str, task: Task) -> str:
    """Case A / C first fault: squeeze the gap below SEP_MIN."""
    lines = text.splitlines()
    pairs = []
    for i, ln in enumerate(lines):
        if "=" in ln and not ln.startswith(("PLAN", "END")):
            jid, val = ln.split("=", 1)
            try:
                pairs.append((i, jid, int(val.strip())))
            except ValueError:
                pass
    if len(pairs) >= 2:
        i, jid, v = pairs[-1]
        lines[i] = f"{jid}={max(0, v - SEP_MIN)}"
    return "\n".join(lines)


INJECTORS = {
    "observer": _inject_observer,
    "planner": _inject_planner,
    "validator": _inject_validator,
    "executor": _inject_executor,
}


# ------------------------------------------------------------------ pipeline

def run_pipeline(task: Task, llm: LLM,
                 inject: Optional[List[str]] = None,
                 prompt_version: Optional[str] = None) -> Run:
    """
    inject: list of agent names whose OUTPUT is corrupted after generation.
    This seeds a known fault without touching the agent's prompt, so the
    agent's own contract is genuinely violated rather than mis-specified.

    prompt_version: "v1" | "v2"; defaults to FA_PROMPT_VERSION. Recorded on
    the run so every result can say which prompts produced it.
    """
    inject = inject or []
    version = prompt_version or PROMPT_VERSION
    systems = PROMPTS[version]
    run = Run(task=task, injected=",".join(inject) or None,
              prompt_version=version)

    from .projection import (project_observer, project_analyzer,
                             project_planner, project_validator,
                             project_executor, ProjectionError)

    def safe(inv: Invocation, fn, default, *args):
        """
        Project inv's text. On ProjectionError, record it on the invocation
        and continue with an empty default -- attribute() will then refuse
        to attribute the run rather than scoring the default as a fault.
        """
        try:
            val, err = fn(inv.raw_out, *args), None
        except ProjectionError as e:
            val, err = default, str(e)
        inv.meta["projected"] = val
        inv.meta["projection_error"] = err
        return val, err

    def step(agent: str, user: str) -> Invocation:
        rep: LLMReply = llm.chat(systems[agent], user)
        txt = rep.text
        meta = {"latency": rep.latency, "retries": rep.retries,
                "finish_reason": rep.finish_reason,
                "served_by": rep.served_by}
        if rep.ok and agent in inject:
            txt = INJECTORS[agent](txt, task)
            # An injector can be a no-op (e.g. no BUSY slot to flip). Such a
            # run has no seeded fault, so its injection label is not truth.
            meta["injected_changed"] = txt != rep.text
        inv = Invocation(agent=agent, prompt_in=user, raw_out=txt,
                         ok=rep.ok, error=rep.error, meta=meta)
        run.invocations.append(inv)
        return inv

    # 1. observer
    i1 = step("observer", task_to_prompt_block(task))
    state, _ = safe(i1, project_observer, {}, task)

    # 2. analyzer
    jobs_txt = "\n".join(f"  {j.id} duration={j.duration}" for j in task.jobs)
    st_txt = "\n".join(f"slot={s} status={v}" for s, v in sorted(state.items()))
    i2 = step("analyzer", f"JOBS:\n{jobs_txt}\n\nSLOT STATUS:\n{st_txt}")
    analysis, _ = safe(i2, project_analyzer,
                       {"unavailable": [], "unresolved": []})

    # 3. planner
    i3 = step("planner",
              f"HORIZON: slots 0..{task.horizon - 1}\n"
              f"JOBS:\n{jobs_txt}\n"
              f"unavailable={analysis['unavailable'] or 'none'}\n"
              f"unresolved={analysis['unresolved'] or 'none'}")
    plan, _ = safe(i3, project_planner, Schedule())

    # 4. validator
    plan_txt = "\n".join(f"{k}={v}" for k, v in sorted(plan.starts.items()))
    i4 = step("validator",
              f"HORIZON: slots 0..{task.horizon - 1}\n"
              f"JOBS:\n{jobs_txt}\n"
              f"unavailable={analysis['unavailable'] or 'none'}\n"
              f"PLAN:\n{plan_txt}")
    verdict, _ = safe(i4, project_validator, {"decision": "?"})

    # 5. executor -- only for an accepted plan. The orchestrator used to
    # forward every plan under an "ACCEPTED PLAN" header, including rejected
    # ones: an unmodelled component with no contract, invisible to the
    # evaluator. Now a REJECT halts the pipeline; nothing is dispatched, and
    # R scores the empty schedule as unscheduled jobs.
    if verdict.get("decision") == "REJECT":
        run.halted = ("validator decision was REJECT; the pipeline halted "
                      "and the executor was not invoked")
        return run
    i5 = step("executor", f"ACCEPTED PLAN:\n{plan_txt}")
    safe(i5, project_executor, Schedule())
    return run
