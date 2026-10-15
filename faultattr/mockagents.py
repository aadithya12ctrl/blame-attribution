"""
Deterministic scripted agents for FA_MOCK=1.

These are NOT a model of LLM behaviour. They exist so the contract evaluator
and verdict classifier can be exercised offline, and so seeded scenarios have
a known-good baseline. Any claim about attribution accuracy must come from
real model runs, not from these.
"""
from __future__ import annotations
import re
from typing import Dict, List

from .domain import SEP_MIN, BUSY, FREE, UNKNOWN

_SLOT = re.compile(r"slot=(\d+)\s+status=(BUSY|FREE|UNKNOWN)")
_JOB = re.compile(r"(J\d+)\s+duration=(\d+)")


def mock_reply(system: str, user: str) -> str:
    if "You are OBSERVER" in system:
        return _observer(user)
    if "You are ANALYZER" in system:
        return _analyzer(user)
    if "You are PLANNER" in system:
        return _planner(user)
    if "You are VALIDATOR" in system:
        return _validator(user)
    if "You are EXECUTOR" in system:
        return _executor(user)
    return ""


def _horizon(user: str) -> int:
    m = re.search(r"slots 0\.\.(\d+)", user)
    return int(m.group(1)) + 1 if m else 0


def _observer(user: str) -> str:
    h = _horizon(user)
    seen = {int(s): st for s, st in _SLOT.findall(user)}
    lines = ["STATE"]
    for s in range(h):
        lines.append(f"slot={s} status={seen.get(s, UNKNOWN)}")
    lines.append("END")
    return "\n".join(lines)


def _analyzer(user: str) -> str:
    busy, unk = [], []
    for s, st in _SLOT.findall(user):
        (busy if st == BUSY else unk if st == UNKNOWN else []).append(int(s))
    return ("ANALYSIS\n"
            f"unavailable={','.join(map(str, sorted(busy))) or 'none'}\n"
            f"unresolved={','.join(map(str, sorted(unk))) or 'none'}\n"
            "END")


def _planner(user: str) -> str:
    h = _horizon(user)
    jobs = [(j, int(d)) for j, d in _JOB.findall(user)]
    m = re.search(r"unavailable=([^\n]*)", user)
    bad = {int(x) for x in re.findall(r"\d+", m.group(1))} if m else set()

    lines, t = ["PLAN"], 0
    for jid, dur in jobs:
        while True:
            if t + dur > h:
                break
            if any(b in range(t, t + dur) for b in bad):
                t += 1
                continue
            break
        lines.append(f"{jid}={t}")
        t += dur + SEP_MIN
    lines.append("END")
    return "\n".join(lines)


def _validator(user: str) -> str:
    h = _horizon(user)
    jobs = {j: int(d) for j, d in _JOB.findall(user)}
    m = re.search(r"unavailable=([^\n]*)", user)
    bad = {int(x) for x in re.findall(r"\d+", m.group(1))} if m else set()
    plan = {k: int(v) for k, v in re.findall(r"^(J\d+)=(-?\d+)$", user,
                                             re.M)}
    reasons: List[str] = []
    ivs = sorted(((k, v, v + jobs.get(k, 0)) for k, v in plan.items()),
                 key=lambda t: t[1])
    for jid, s, e in ivs:
        if e > h:
            reasons.append(f"horizon:{jid}")
        if any(b in range(s, e) for b in bad):
            reasons.append(f"unavailable:{jid}")
    for a, b in zip(ivs, ivs[1:]):
        if b[1] - a[2] < SEP_MIN:
            reasons.append(f"gap:{a[0]}~{b[0]}")
    dec = "REJECT" if reasons else "ACCEPT"
    return (f"VERDICT\ndecision={dec}\n"
            f"reasons={','.join(reasons) or 'none'}\nEND")


def _executor(user: str) -> str:
    plan = re.findall(r"^(J\d+)=(-?\d+)$", user, re.M)
    return "ACTIONS\n" + "\n".join(f"{k}={v}" for k, v in plan) + "\nEND"
