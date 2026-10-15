"""
Contracts: P_a (what the agent may assume about its input history) and
G_a (what it must guarantee about its full history).

Both are predicates over histories, per section 3.4 -- in this pipeline each
agent is invoked once, so the histories are length 1, but the signatures keep
the general shape so multi-invocation agents drop in without a type change.

CONTRACT AUTHORING NOTE (case E): the precondition boundary below puts input
validation on the UPSTREAM producer, not the consumer. The analyzer assumes
its slot statuses are faithful and is NOT obliged to flag implausible input.
That is a policy choice, not a fact. Flip ANALYZER_VALIDATES_INPUT to see the
verdict change -- that is the point of writing it down.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .domain import Task, Schedule, SEP_MIN, BUSY, FREE, UNKNOWN
from .agents import Run, AGENTS

ANALYZER_VALIDATES_INPUT = False


@dataclass
class Check:
    ok: bool
    detail: str = ""


@dataclass
class Contract:
    name: str
    pre: Callable[[Run], Check]
    guar: Callable[[Run], Check]


def _proj(run: Run, agent: str):
    invs = run.by_agent(agent)
    return invs[0].meta.get("projected") if invs else None


def _ok(run: Run, agent: str) -> bool:
    invs = run.by_agent(agent)
    return bool(invs) and invs[0].ok


# ------------------------------------------------------------------ observer

def pre_observer(run: Run) -> Check:
    # Assumes: sensor feed is live. Readings may be MISSING (that is the
    # dead-sensor case) -- missing readings do NOT void the precondition,
    # because handling them is exactly what the guarantee is about.
    return Check(True, "feed live")


def guar_observer(run: Run) -> Check:
    st: Dict[int, str] = _proj(run, "observer") or {}
    if not st:
        return Check(False, "no parseable state")
    task = run.task
    reported = {o.slot: o.status for o in task.observations}

    for s in range(task.horizon):
        got = st.get(s, UNKNOWN)
        if s in reported:
            if got != reported[s]:
                return Check(False, f"slot {s}: reported {reported[s]}, "
                                    f"emitted {got}")
        else:
            # no reading -> must be UNKNOWN, never FREE
            if got != UNKNOWN:
                return Check(False, f"slot {s}: no reading, emitted {got} "
                                    f"(must be UNKNOWN)")
    if set(st) != set(range(task.horizon)):
        return Check(False, "incomplete slot coverage")
    return Check(True, "faithful and complete")


# ------------------------------------------------------------------ analyzer

def pre_analyzer(run: Run) -> Check:
    st = _proj(run, "observer") or {}
    task = run.task
    if not st or set(st) != set(range(task.horizon)):
        return Check(False, "slot status incomplete")
    if ANALYZER_VALIDATES_INPUT:
        return Check(True, "well-formed input (validation is analyzer's job)")
    # Policy: analyzer assumes its input is FAITHFUL, not merely well-formed.
    g = guar_observer(run)
    if not g.ok:
        return Check(False, f"upstream state unfaithful: {g.detail}")
    return Check(True, "faithful state received")


def guar_analyzer(run: Run) -> Check:
    a = _proj(run, "analyzer")
    st = _proj(run, "observer") or {}
    if a is None:
        return Check(False, "no parseable analysis")
    busy = {s for s, v in st.items() if v == BUSY}
    unk = {s for s, v in st.items() if v == UNKNOWN}

    if not busy.issubset(set(a["unavailable"])):
        return Check(False, f"missed unavailable slots "
                            f"{sorted(busy - set(a['unavailable']))}")
    if not set(a["unavailable"]).issubset(busy):
        return Check(False, f"invented unavailable slots "
                            f"{sorted(set(a['unavailable']) - busy)}")
    if not unk.issubset(set(a["unresolved"])):
        return Check(False, f"failed to surface unknown slots "
                            f"{sorted(unk - set(a['unresolved']))}")
    return Check(True, "complete and sound")


# ------------------------------------------------------------------- planner

def pre_planner(run: Run) -> Check:
    a = _proj(run, "analyzer")
    if a is None:
        return Check(False, "no analysis received")
    g = guar_analyzer(run)
    if not g.ok:
        return Check(False, f"conflict set not complete: {g.detail}")
    if a["unresolved"]:
        return Check(False, f"unresolved slots present: {a['unresolved']}")
    return Check(True, "complete conflict set, nothing unresolved")


def guar_planner(run: Run) -> Check:
    plan: Optional[Schedule] = _proj(run, "planner")
    a = _proj(run, "analyzer") or {"unavailable": []}
    task = run.task
    if plan is None or not plan.starts:
        return Check(False, "no parseable plan")

    ids = {j.id for j in task.jobs}
    if set(plan.starts) != ids:
        return Check(False, f"job set mismatch: {sorted(set(plan.starts))} "
                            f"vs {sorted(ids)}")

    ivs = plan.as_intervals(task.jobs)
    for jid, s, e in ivs:
        if s < 0 or e > task.horizon:
            return Check(False, f"{jid} runs outside horizon")
        for b in a["unavailable"]:
            if s <= b < e:
                return Check(False, f"{jid} covers unavailable slot {b}")
    for x, y in zip(ivs, ivs[1:]):
        gap = y[1] - x[2]
        if gap < 0:
            return Check(False, f"overlap {x[0]}~{y[0]}")
        if gap < SEP_MIN:
            return Check(False, f"gap {gap} < {SEP_MIN} between "
                                f"{x[0]} and {y[0]}")
    return Check(True, "feasible against the state it was given")


# ----------------------------------------------------------------- validator

def pre_validator(run: Run) -> Check:
    plan = _proj(run, "planner")
    if plan is None or not plan.starts:
        return Check(False, "plan not well-formed")
    return Check(True, "well-formed plan")


def guar_validator(run: Run) -> Check:
    v = _proj(run, "validator") or {}
    dec = v.get("decision", "?")
    if dec == "?":
        return Check(False, "no parseable verdict")
    feasible = guar_planner(run).ok
    if not feasible and dec == "ACCEPT":
        return Check(False, "accepted an infeasible plan")
    if feasible and dec == "REJECT":
        return Check(False, "rejected a feasible plan")
    return Check(True, f"correct {dec}")


# ------------------------------------------------------------------ executor

def pre_executor(run: Run) -> Check:
    v = _proj(run, "validator") or {}
    if v.get("decision") != "ACCEPT":
        return Check(False, "plan was not accepted")
    return Check(True, "validated plan")


def guar_executor(run: Run) -> Check:
    plan: Optional[Schedule] = _proj(run, "planner")
    acts: Optional[Schedule] = _proj(run, "executor")
    if acts is None or not acts.starts:
        return Check(False, "no parseable actions")
    if plan is None:
        return Check(False, "no plan to compare against")
    if acts.starts != plan.starts:
        diff = {k: (plan.starts.get(k), acts.starts.get(k))
                for k in set(plan.starts) | set(acts.starts)
                if plan.starts.get(k) != acts.starts.get(k)}
        return Check(False, f"actions diverge from plan: {diff}")
    return Check(True, "actions match plan exactly")


CONTRACTS: Dict[str, Contract] = {
    "observer":  Contract("observer",  pre_observer,  guar_observer),
    "analyzer":  Contract("analyzer",  pre_analyzer,  guar_analyzer),
    "planner":   Contract("planner",   pre_planner,   guar_planner),
    "validator": Contract("validator", pre_validator, guar_validator),
    "executor":  Contract("executor",  pre_executor,  guar_executor),
}
