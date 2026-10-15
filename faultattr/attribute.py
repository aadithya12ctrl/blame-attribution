"""
The attribution engine.

Computes Phi (the fault set) and classifies the verdict per Theorem 5.2:

  1 AGENT_FAULT     Phi != empty
  2 REPAIRABLE      Phi empty, an expressible corpus-consistent repair exists
  3 CORPUS_BLOCKED  Phi empty, repairs exist but all contradict the corpus
  4 INEXPRESSIBLE   Phi empty, no expressible repair over any agent's history

Cases 2-4 also carry the D1/D2 split by exogenous share (Definition 7.8).

Runs where any agent's output failed to project get UNATTRIBUTABLE instead,
before contracts are evaluated: a parse failure is eps, not a fault.

IMPORTANT SCOPE NOTE: the repair search here is a stub. Enumerating
max_rep properly is gap 1 in the framework and is NOT solved. What this
does is check a small, hand-written catalogue of candidate strengthenings
against (R2)/(R3)/(R4), which is enough to separate cases 2/3/4 on the
seeded scenarios and nothing more. Do not report it as a repair algorithm.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .agents import Run, AGENTS
from .contracts import CONTRACTS, Check, guar_observer
from .domain import (R_holds, requirement_violations, margin,
                     consumed_margin, exogenous_depletion, Schedule, UNKNOWN)

AGENT_FAULT = "AGENT_FAULT"
REPAIRABLE = "REPAIRABLE_INADEQUACY"
CORPUS_BLOCKED = "CORPUS_BLOCKED"
INEXPRESSIBLE = "INEXPRESSIBLE"
NO_FAILURE = "NO_FAILURE"
# Not a verdict about the run: the evaluator could not read some agent's
# output, so contracts cannot be evaluated. Counts toward eps, not faults.
UNATTRIBUTABLE = "UNATTRIBUTABLE_PROJECTION_FAILURE"


@dataclass
class AgentVerdict:
    agent: str
    pre_ok: bool
    guar_ok: bool
    at_fault: bool
    pre_detail: str = ""
    guar_detail: str = ""


@dataclass
class Verdict:
    kind: str
    phi: List[str] = field(default_factory=list)
    per_agent: List[AgentVerdict] = field(default_factory=list)
    R_violations: List[str] = field(default_factory=list)
    margin: float = 0.0
    cons_total: float = 0.0
    exo: float = 0.0
    d_class: Optional[str] = None        # "D1" | "D2" | None
    repairs: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def evaluate_contracts(run: Run) -> List[AgentVerdict]:
    out = []
    for a in AGENTS:
        c = CONTRACTS[a]
        p: Check = c.pre(run)
        g: Check = c.guar(run)
        out.append(AgentVerdict(agent=a, pre_ok=p.ok, guar_ok=g.ok,
                                at_fault=(p.ok and not g.ok),
                                pre_detail=p.detail, guar_detail=g.detail))
    return out


# ------------------------------------------------- candidate repair catalogue

def _candidate_repairs(run: Run) -> List[Dict[str, object]]:
    """
    Hand-written candidate strengthenings. Each entry says which agent would
    own it, whether it is expressible over that agent's observable history
    (R4), and a predicate used to test (R2)/(R3).
    """
    task = run.task
    obs_state = (run.by_agent("observer")[0].meta.get("projected")
                 if run.by_agent("observer") else {}) or {}
    analysis = (run.by_agent("analyzer")[0].meta.get("projected")
                if run.by_agent("analyzer") else {}) or {}

    cands = []

    # Candidate 1: planner must refuse to plan when anything is unresolved.
    # Expressible: planner sees `unresolved` in its input.
    cands.append({
        "id": "planner_blocks_on_unresolved",
        "owner": "planner",
        "expressible": True,
        # catches this run iff there WERE unresolved slots
        "catches": bool(analysis.get("unresolved")),
        "text": "PLANNER must not emit a plan when unresolved != none; "
                "escalate to degraded mode instead.",
    })

    # Candidate 2: analyzer must escalate unknowns rather than merely list them.
    cands.append({
        "id": "analyzer_escalates_unknown",
        "owner": "analyzer",
        "expressible": True,
        "catches": any(v == UNKNOWN for v in obs_state.values()),
        "text": "ANALYZER must raise a blocking flag when any slot is UNKNOWN.",
    })

    # Candidate 3: somebody must guarantee state corresponds to reality.
    # NOT expressible: no agent's input contains ground truth. When this is
    # the only candidate that catches the run, the verdict is INEXPRESSIBLE.
    cands.append({
        "id": "state_matches_reality",
        "owner": None,
        "expressible": False,
        "catches": True,
        "text": "Some agent must guarantee that reported slot status "
                "corresponds to physical occupancy. No agent observes this, "
                "so this is an instrumentation gap (Remark 5.3b, case 4a), "
                "not a contract anyone can be given.",
    })
    return cands


def _repair_blocked_by_corpus(cand: Dict[str, object], corpus: List[Run]) -> bool:
    """
    (R3): would this strengthening misattribute any successful run?
    Approximated by checking whether the strengthening's trigger condition
    also fires on runs that satisfied R.
    """
    if not corpus:
        return False
    cid = cand["id"]
    for ok_run in corpus:
        analysis = (ok_run.by_agent("analyzer")[0].meta.get("projected")
                    if ok_run.by_agent("analyzer") else {}) or {}
        st = (ok_run.by_agent("observer")[0].meta.get("projected")
              if ok_run.by_agent("observer") else {}) or {}
        if cid == "planner_blocks_on_unresolved" and analysis.get("unresolved"):
            return True
        if cid == "analyzer_escalates_unknown" and any(
                v == UNKNOWN for v in st.values()):
            return True
    return False


# ----------------------------------------------------------------- main entry

def attribute(run: Run, corpus: Optional[List[Run]] = None,
              exo_threshold: float = 0.15) -> Verdict:
    """
    corpus: successful, conformant runs (Sigma_ok). Used for (R3).
    exo_threshold: per-run proxy for the D1/D2 split. The framework prefers a
      corpus-level model comparison (Definition 7.8); this per-run threshold is
      a stand-in and should be reported as such.
    """
    corpus = corpus or []

    failed = [(i.agent, i.meta["projection_error"]) for i in run.invocations
              if i.meta.get("projection_error")]
    if failed:
        v = Verdict(kind=UNATTRIBUTABLE)
        for agent, err in failed:
            v.notes.append(f"projection failed at {agent}: {err}")
        v.notes.append("run excluded from attribution statistics; it counts "
                       "toward eps, not toward the fault rate")
        return v

    per_agent = evaluate_contracts(run)
    phi = [v.agent for v in per_agent if v.at_fault]

    exec_sched: Schedule = (run.by_agent("executor")[0].meta.get("projected")
                            if run.by_agent("executor") else Schedule())
    if exec_sched is None:
        exec_sched = Schedule()

    viol = requirement_violations(run.task, exec_sched)
    M = margin(run.task, exec_sched)
    cons = consumed_margin(run.task, exec_sched)
    cons_total = sum(cons.values())
    exo = exogenous_depletion(run.task, exec_sched)
    depletion = 1.0 - M
    # exo is measured directly, not taken as a residual; the residual is kept
    # only to prove the accounting closes. A non-zero value means margin()
    # and consumed_margin() have diverged and exo would be absorbing the gap.
    identity_residual = depletion - cons_total - exo
    assert abs(identity_residual) < 1e-9, (
        f"depletion identity does not close: residual={identity_residual}")

    v = Verdict(kind=NO_FAILURE, phi=phi, per_agent=per_agent,
                R_violations=viol, margin=M, cons_total=cons_total, exo=exo)

    if not viol:
        v.notes.append("R holds; no failure to attribute")
        if phi:
            v.notes.append(f"contract violations without failure: {phi} "
                           f"(an error that did not become a failure)")
        return v

    if phi:
        v.kind = AGENT_FAULT
        return v

    # Phi is empty and R failed -> inadequacy. Classify D1/D2 and repairability.
    v.d_class = "D2" if exo <= exo_threshold else "D1"
    v.notes.append(f"depletion={depletion:.3f} cons={cons_total:.3f} "
                   f"exo={exo:.3f} (threshold {exo_threshold})")

    cands = _candidate_repairs(run)
    catching = [c for c in cands if c["catches"]]
    expressible = [c for c in catching if c["expressible"]]

    if not expressible:
        v.kind = INEXPRESSIBLE
        v.repairs = [f"[not expressible] {c['text']}" for c in catching]
        v.notes.append("no strengthening expressible over any agent's "
                       "observable history (Theorem 5.2 case 4)")
        return v

    allowed = [c for c in expressible
               if not _repair_blocked_by_corpus(c, corpus)]
    if not allowed:
        v.kind = CORPUS_BLOCKED
        v.repairs = [f"[blocked by corpus] {c['text']}" for c in expressible]
        v.notes.append(f"all {len(expressible)} expressible repairs "
                       f"misattribute some run in Sigma_ok (|corpus|="
                       f"{len(corpus)}); verdict is corpus-relative")
        return v

    v.kind = REPAIRABLE
    v.repairs = [f"[owner={c['owner']}] {c['text']}" for c in allowed]
    if len(allowed) > 1:
        v.notes.append(f"{len(allowed)} incomparable minimal repairs -- "
                       f"set-valued output is correct here, not a hedge")
    return v


def format_verdict(v: Verdict) -> str:
    L = [f"VERDICT: {v.kind}" + (f"  [{v.d_class}]" if v.d_class else "")]
    if v.kind == UNATTRIBUTABLE:          # nothing was evaluated; say only why
        return "\n".join(L + [f"  note: {n}" for n in v.notes])
    if v.phi:
        L.append(f"  fault set: {v.phi}")
    L.append("  contracts:")
    for a in v.per_agent:
        mark = "FAULT" if a.at_fault else ("excused" if not a.pre_ok else "ok")
        L.append(f"    {a.agent:<10} P={'T' if a.pre_ok else 'F'} "
                 f"G={'T' if a.guar_ok else 'F'}  {mark}")
        if not a.pre_ok:
            L.append(f"        pre:  {a.pre_detail}")
        if not a.guar_ok:
            L.append(f"        guar: {a.guar_detail}")
    if v.R_violations:
        L.append(f"  R violations: {v.R_violations}")
    L.append(f"  margin={v.margin:.3f} cons={v.cons_total:.3f} exo={v.exo:.3f}")
    for r in v.repairs:
        L.append(f"  repair candidate: {r}")
    for n in v.notes:
        L.append(f"  note: {n}")
    return "\n".join(L)
