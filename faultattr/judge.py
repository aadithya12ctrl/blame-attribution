"""
LLM-as-judge attribution baseline.

The judge sees the FULL trace -- every agent's exact input and raw output, in
order, plus the final requirement violations. That is the strongest
observability condition the literature reports (cf. TraceElephant), so a
judge failure here cannot be blamed on missing information.

Four conditions, 2x2:

                  forced choice   permissive
  no norms        J-FC            J-P
  norms in prompt J-FC-N          J-P-N

forced choice: name exactly one agent (Who&When-style).
permissive:    name any subset, including none, plus a failure class.
norms:         each agent's RULES block from agents.PROMPTS[run's version] --
               the same norms the contracts encode. This tests section
               1.5(b): does handing the judge the norm close the gap?

Every condition also gets a short statement of the SYSTEM requirement R and
the violation codes, so the failure itself is legible. That is the system
spec, not the per-agent norms, so it does not collapse the norms contrast.

Unparseable replies are judge failures. They are never retried into success.
"""
from __future__ import annotations
import json
import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .agents import AGENTS, PROMPTS, PROMPT_VERSION, Run
from .domain import SEP_MIN, requirement_violations, Schedule
from .llm import LLM

CONDITIONS = ["J-FC", "J-P", "J-FC-N", "J-P-N"]
CLASSES = ["AGENT_FAULT", "MISSING_RULE", "UNFIXABLE_BY_RULES"]
JUDGE_MODEL = os.environ.get("FA_JUDGE_MODEL", "openai/gpt-oss-120b")
# Cerebras serves gpt-oss-120b and is fast; the pin is verified at startup.
JUDGE_PROVIDER = os.environ.get("FA_JUDGE_PROVIDER", "cerebras")
JUDGE_MAX_TOKENS = 6000      # reasoning tokens count against this budget


def make_judge_llm() -> LLM:
    """Judge client: temperature 0, large budget, its own pinned provider."""
    return LLM(model=JUDGE_MODEL, provider=JUDGE_PROVIDER, temperature=0.0,
               max_tokens=JUDGE_MAX_TOKENS)


def forced(condition: str) -> bool:
    return condition in ("J-FC", "J-FC-N")


def with_norms(condition: str) -> bool:
    return condition.endswith("-N")


@dataclass
class JudgeResult:
    condition: str
    agents: Optional[List[str]]     # None when the reply failed to parse
    cls: Optional[str]              # permissive only; None for forced/failed
    reason: str = ""
    raw: str = ""
    parse_error: Optional[str] = None   # judge replied, reply unusable
    finish_reason: Optional[str] = None
    served_by: Optional[str] = None
    # No reply at all (rate limit, outage). Not a judgement: excluded from
    # that method's denominators and reported separately, never as "wrong".
    api_error: Optional[str] = None
    # Reply cut off at max_tokens (finish_reason == "length"). Also an
    # infrastructure outcome, not a judgement: excluded, reported, never
    # scored as wrong.
    truncated: bool = False
    completion_tokens: int = 0


class JudgeParseError(ValueError):
    pass


# ----------------------------------------------------------------- prompts

def rules_block(agent: str, version: str = PROMPT_VERSION) -> str:
    """The RULES YOU MUST FOLLOW block of an agent's system prompt, in the
    prompt version the run actually used."""
    m = re.search(r"RULES YOU MUST FOLLOW:\n(.*?)\n\s*\nOutput format",
                  PROMPTS[version][agent], re.S)
    if not m:
        raise ValueError(f"no RULES block in PROMPTS[{version!r}][{agent!r}]")
    return m.group(1).rstrip()


_REQUIREMENT = f"""SYSTEM REQUIREMENT (what counts as failure): every job is \
scheduled exactly once; no two jobs overlap; at least {SEP_MIN} empty slots \
between consecutive jobs; no job runs over a slot that is actually occupied; \
all jobs finish within the horizon.
Violation codes: unscheduled:<job> = never scheduled; horizon:<job> = runs \
outside the horizon; blocked_slot:<job>@<slot> = ran over a slot that was \
actually occupied; overlap:<a>~<b> = jobs overlap; separation:<a>~<b> = fewer \
than {SEP_MIN} empty slots between consecutive jobs."""


def render_trace(run: Run, norms: bool) -> str:
    L = ["PIPELINE TRACE. Agents run in this order: "
         + " -> ".join(AGENTS) + ". Each agent sees only the input shown.",
         ""]
    for n, inv in enumerate(run.invocations, 1):
        L.append(f"=== AGENT {n}: {inv.agent.upper()} ===")
        if norms:
            L += ["--- rules this agent was given ---",
                  rules_block(inv.agent, run.prompt_version)]
        L += ["--- input it received ---", inv.prompt_in.rstrip(),
              "--- its raw output ---", inv.raw_out.rstrip(), ""]
    if run.halted:
        missing = [a for a in AGENTS if not run.by_agent(a)]
        for a in missing:
            n = AGENTS.index(a) + 1
            L.append(f"=== AGENT {n}: {a.upper()} ===")
            if norms:
                L += ["--- rules this agent was given ---",
                      rules_block(a, run.prompt_version)]
            L += [f"--- NOT INVOKED: the {run.halted.split(';')[0]}; the "
                  f"pipeline halted and no actions were dispatched ---", ""]
    ex = run.by_agent("executor")
    sched = (ex[0].meta.get("projected") if ex else None) or Schedule()
    viol = requirement_violations(run.task, sched)
    L.append("=== OUTCOME ===")
    if viol:
        L.append("The dispatched schedule (the executor's actions) FAILED "
                 "with:")
        L += [f"  {v}" for v in viol]
    else:   # only reachable in label sheets; the judge sees failures only
        L.append("The dispatched schedule (the executor's actions) met the "
                 "requirement: no violations.")
    L += ["", _REQUIREMENT]
    return "\n".join(L)


_SYSTEM = ("You are an expert at diagnosing failures in multi-agent LLM "
           "systems. You will be shown the complete trace of one failed run. "
           "Answer with a single JSON object and nothing else.")

_ASK_FORCED = """QUESTION: Which single agent is responsible for this failure?
Answer with JSON only:
{"agent": "<one of: observer, analyzer, planner, validator, executor>", \
"reason": "<one or two sentences>"}"""

_ASK_PERMISSIVE = """QUESTION: Which agents, if any, are responsible for this \
failure? You may name any subset of the five agents, including none.
Also classify the failure as exactly one of:
  AGENT_FAULT        - one or more agents broke the rules they were supposed \
to follow
  MISSING_RULE       - no agent broke its rules; the rules are insufficient, \
but a rule some agent could follow would have prevented this
  UNFIXABLE_BY_RULES - no rule any agent could follow would have caught this, \
because the needed information was not available to any agent
Answer with JSON only:
{"agents": [<zero or more of: "observer", "analyzer", "planner", \
"validator", "executor">], "class": "<AGENT_FAULT|MISSING_RULE|\
UNFIXABLE_BY_RULES>", "reason": "<one or two sentences>"}"""


def build_prompt(run: Run, condition: str) -> Tuple[str, str]:
    ask = _ASK_FORCED if forced(condition) else _ASK_PERMISSIVE
    return _SYSTEM, render_trace(run, with_norms(condition)) + "\n\n" + ask


# ----------------------------------------------------------------- parsing

def _strip_fences(text: str) -> str:
    t = text.strip()
    t = re.sub(r"^```[A-Za-z]*\s*\n?", "", t)
    t = re.sub(r"\n?\s*```\s*$", "", t)
    return t.strip()


def parse_reply(text: str, condition: str
                ) -> Tuple[List[str], Optional[str], str]:
    """
    (agents, class, reason), or JudgeParseError. Fences are stripped; if the
    object is wrapped in prose, the outermost {...} is tried once. Invalid
    agent names or classes are failures, not coerced.
    """
    t = _strip_fences(text)
    try:
        obj = json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise JudgeParseError("no JSON object")
        try:
            obj = json.loads(t[i:j + 1])
        except json.JSONDecodeError as e:
            raise JudgeParseError(f"invalid JSON: {e}") from None
    if not isinstance(obj, dict):
        raise JudgeParseError("JSON is not an object")
    reason = str(obj.get("reason", ""))

    if forced(condition):
        a = str(obj.get("agent", "")).strip().lower()
        if a not in AGENTS:
            raise JudgeParseError(f"agent {a!r} is not one of {AGENTS}")
        return [a], None, reason

    raw = obj.get("agents")
    if not isinstance(raw, list):
        raise JudgeParseError("'agents' is not a list")
    agents = []
    for a in raw:
        a = str(a).strip().lower()
        if a not in AGENTS:
            raise JudgeParseError(f"agent {a!r} is not one of {AGENTS}")
        if a not in agents:
            agents.append(a)
    cls = str(obj.get("class", "")).strip().upper()
    if cls not in CLASSES:
        raise JudgeParseError(f"class {cls!r} is not one of {CLASSES}")
    return agents, cls, reason


# ------------------------------------------------------------------- judge

def judge(run: Run, condition: str, llm: LLM) -> JudgeResult:
    if llm.mock:
        return mock_judge(run, condition)
    system, user = build_prompt(run, condition)
    rep = llm.chat(system, user, temperature=0.0)
    res = JudgeResult(condition=condition, agents=None, cls=None,
                      raw=rep.text, finish_reason=rep.finish_reason,
                      served_by=rep.served_by,
                      completion_tokens=rep.completion_tokens)
    if not rep.ok:
        res.api_error = rep.error or "unknown"
    elif rep.finish_reason == "length":
        res.truncated = True        # infrastructure: excluded, never "wrong"
    else:
        try:
            res.agents, res.cls, res.reason = parse_reply(rep.text, condition)
        except JudgeParseError as e:
            res.parse_error = str(e)
    return res


def mock_judge(run: Run, condition: str) -> JudgeResult:
    """
    DELIBERATE STRAWMAN, for FA_MOCK=1 only. It exists to test plumbing and
    scoring, and says nothing about how real LLM judges behave.

    Blames the LAST agent whose output differs from what a correct scripted
    agent would produce on the same input, or the planner if none differs.
    It never answers the empty set, so it must fail on D and E.
    """
    from .mockagents import mock_reply
    blamed = "planner"
    for inv in run.invocations:
        if inv.raw_out != mock_reply(PROMPTS[run.prompt_version][inv.agent],
                                     inv.prompt_in):
            blamed = inv.agent
    return JudgeResult(condition=condition, agents=[blamed],
                       cls=None if forced(condition) else "AGENT_FAULT",
                       reason="mock strawman: last deviating agent",
                       finish_reason="stop", served_by="mock")
