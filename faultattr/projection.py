"""
Projection layer: free text -> typed state.

This is where epsilon lives (Definition 8.2). Every verdict the framework
produces is only as good as this layer, and the bound 2nk*eps means it must
be measured and reported, not assumed. measure_epsilon() below does that.

Every project_* function either returns a well-formed value or raises
ProjectionError. None of them returns an empty result on failure: an empty
result would be scored by the contracts as a guarantee violation, turning a
parse failure into a spurious agent fault.
"""
from __future__ import annotations
import re
from typing import Dict, List

from .domain import Task, Schedule, BUSY, FREE, UNKNOWN

_SLOT = re.compile(r"slot\s*=\s*(\d+)\s+status\s*=\s*(BUSY|FREE|UNKNOWN)", re.I)
_KV = re.compile(r"^\s*([A-Za-z]\w*)\s*=\s*(-?\d+)\s*$")
_LIST = re.compile(r"(\w+)\s*=\s*([^\n]*)")
_JOB_KV = re.compile(r"\b(J\d+)\s*=\s*(-?\d+)")


class ProjectionError(ValueError):
    """
    The text could not be turned into typed state.

    A parse failure is projection error -- it counts toward eps (Definition
    8.2) -- and is never a contract violation. The agent may have produced a
    perfectly conforming answer that this layer failed to read; charging it
    with a fault would attribute the evaluator's error to the agent.
    """


def _between(text: str, start: str, end: str = "END") -> str:
    """
    Body of the last START ... END block in text, or "" if there is none.

    Markers are matched anchored to line starts, so prose such as
    "Let me plan:" or "Ends at slot 4" cannot open or close a block. Only if
    no anchored START exists do we fall back to word-boundary matches. The
    candidates are tried last-to-first because models reason first and emit
    the required block at the end.
    """
    anchored = list(re.finditer(rf"^\s*{start}\s*$", text, re.M | re.I))
    cands = anchored or list(re.finditer(rf"\b{start}\b", text, re.I))
    end_re = re.compile(rf"^\s*{end}\b", re.M | re.I)
    for m in reversed(cands):
        rest = text[m.end():]
        e = end_re.search(rest)
        block = rest[:e.start()] if e else rest
        if block.strip():
            return block
    return ""


def project_observer(text: str, task: Task) -> Dict[int, str]:
    block = _between(text, "STATE") or text
    out: Dict[int, str] = {}
    for m in _SLOT.finditer(block):
        out[int(m.group(1))] = m.group(2).upper()
    if not out:
        raise ProjectionError("observer: no slot=<n> status=<S> lines")
    for s in range(task.horizon):
        out.setdefault(s, UNKNOWN)
    return out


def _parse_int_list(raw: str) -> List[int]:
    raw = raw.strip()
    if not raw or raw.lower() in {"none", "[]", "-"}:
        return []
    return sorted({int(x) for x in re.findall(r"\d+", raw)})


def project_analyzer(text: str) -> Dict[str, List[int]]:
    block = _between(text, "ANALYSIS") or text
    res = {"unavailable": [], "unresolved": []}
    found = False
    for m in _LIST.finditer(block):
        k = m.group(1).lower()
        if k in res:
            res[k] = _parse_int_list(m.group(2))
            found = True
    if not found:
        raise ProjectionError("analyzer: neither unavailable= nor unresolved=")
    return res


def _job_starts(text: str, marker: str) -> Dict[str, int]:
    """JOBID=int lines from the marker block, else anywhere in the text."""
    starts: Dict[str, int] = {}
    for ln in _between(text, marker).splitlines():
        m = _KV.match(ln)
        if m and m.group(1).upper() not in {marker, "END"}:
            starts[m.group(1).upper()] = int(m.group(2))
    if not starts:
        # Recovery: the block is missing or malformed, but the assignments
        # may still be present. Later assignments override earlier ones.
        for jid, v in _JOB_KV.findall(text):
            starts[jid.upper()] = int(v)
    if not starts:
        raise ProjectionError(f"{marker.lower()}: no JOBID=<int> assignments")
    return starts


def project_planner(text: str) -> Schedule:
    return Schedule(starts=_job_starts(text, "PLAN"))


def project_validator(text: str) -> Dict[str, object]:
    block = _between(text, "VERDICT") or text
    if re.search(r"decision\s*=\s*ACCEPT", block, re.I):
        return {"decision": "ACCEPT"}
    if re.search(r"decision\s*=\s*REJECT", block, re.I):
        return {"decision": "REJECT"}
    raise ProjectionError("validator: no decision=ACCEPT|REJECT")


def project_executor(text: str) -> Schedule:
    return Schedule(starts=_job_starts(text, "ACTIONS"))


# ---------------------------------------------------------------- epsilon

def measure_epsilon(runs) -> Dict[str, object]:
    """
    Projection error, measured two ways.

    PARSE failures are measured at every stage: the fraction of invocations
    whose text raised ProjectionError. No ground truth is needed for that.

    VALUE errors (text parsed, but to the wrong state) need truth that is
    independent of the agent. Only the observer has it: the task knows which
    slots are really BUSY. Downstream value errors remain unmeasured -- report
    that limitation rather than hiding it.

    eps_used_for_bound is the worse of the two measured rates.
    """
    from .agents import AGENTS

    n_inv = {a: 0 for a in AGENTS}
    n_fail = {a: 0 for a in AGENTS}
    total = wrong = 0
    for run in runs:
        for a in AGENTS:
            for inv in run.by_agent(a):
                n_inv[a] += 1
                if inv.meta.get("projection_error"):
                    n_fail[a] += 1

        invs = run.by_agent("observer")
        if not invs or invs[0].meta.get("projection_error"):
            continue
        proj = invs[0].meta.get("projected") or {}
        truth = {s: (BUSY if s in run.task.blocked_slots else FREE)
                 for s in range(run.task.horizon)}
        if run.task.dead_sensor_slot is not None:
            truth[run.task.dead_sensor_slot] = UNKNOWN  # correct report
        for s, t in truth.items():
            total += 1
            if proj.get(s, UNKNOWN) != t:
                wrong += 1

    out: Dict[str, object] = {
        "observer_slot_error_rate": (wrong / total) if total else float("nan"),
        "observer_slots_checked": total,
    }
    rates = {}
    for a in AGENTS:
        rates[a] = (n_fail[a] / n_inv[a]) if n_inv[a] else float("nan")
        out[f"{a}_parse_failure_rate"] = rates[a]
    out["invocations_per_agent"] = min(n_inv.values()) if n_inv else 0
    measured = [out["observer_slot_error_rate"], *rates.values()]
    measured = [x for x in measured if x == x]            # drop NaN
    out["eps_used_for_bound"] = max(measured) if measured else float("nan")
    out["note"] = ("parse failures are measured at every stage; only the "
                   "observer has independent ground truth, so downstream "
                   "VALUE errors remain unmeasured")
    return out
