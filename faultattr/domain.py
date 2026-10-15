"""
Domain: scheduling N jobs on a single shared resource over T time slots.

Chosen because it gives a scalar margin M(rho) with a linear decomposition,
which is exactly the scope condition in Remark 7.7 of the framework. Do not
extend to multi-constraint requirements without revisiting that.

Requirement R:
  - every job scheduled exactly once
  - no two jobs overlap on the resource
  - consecutive jobs separated by at least SEP_MIN
  - all jobs finish within the horizon T
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

SEP_MIN = 2  # minimum gap between consecutive jobs, in slots

BUSY, FREE, UNKNOWN = "BUSY", "FREE", "UNKNOWN"


@dataclass
class Job:
    id: str
    duration: int


@dataclass
class Observation:
    """A raw sensor reading about one time slot."""
    slot: int
    status: str          # BUSY | FREE
    timestamp: int


@dataclass
class Task:
    """One problem instance."""
    jobs: List[Job]
    horizon: int
    observations: List[Observation]
    blocked_slots: List[int]      # ground truth: slots genuinely occupied
    tau: float                    # margin parameter used to generate it
    delta: int                    # difficulty parameter
    seed: int
    dead_sensor_slot: Optional[int] = None   # sensor emits nothing (D1 case)
    lying_sensor_slot: Optional[int] = None  # sensor emits a WRONG reading

    def demand(self) -> int:
        n = len(self.jobs)
        return sum(j.duration for j in self.jobs) + max(0, n - 1) * SEP_MIN

    def capacity(self) -> int:
        return self.horizon - len(self.blocked_slots)

    def slack(self) -> int:
        return self.capacity() - self.demand()


# ---------------------------------------------------------------- generation

def make_task(tau: float, delta: int, seed: int,
              dead_sensor: bool = False,
              lying_sensor: bool = False) -> Task:
    """
    tau   in [0,1]: margin parameter. tau=0 comfortable, tau=1 at the boundary.
    delta in {0,1,2,...}: difficulty. More jobs at (approximately) fixed margin.

    tau and delta are varied independently -- this is the control for the
    difficulty confound (Definition 9.2). Changing delta adjusts the horizon
    to hold the slack ratio fixed.
    """
    rng = random.Random(seed)
    n_jobs = 3 + delta
    jobs = [Job(id=f"J{i+1}", duration=rng.choice([1, 2, 2, 3]))
            for i in range(n_jobs)]

    demand = sum(j.duration for j in jobs) + (n_jobs - 1) * SEP_MIN

    # slack_ratio goes from 0.60 (roomy) down to 0.00 (exactly tight)
    slack_ratio = 0.60 * (1.0 - tau)
    capacity = int(round(demand * (1.0 + slack_ratio)))

    # Blocked slots scale with tau so that tightening the margin also
    # fragments the horizon. Slack alone does not provoke violations: greedy
    # left-packing achieves exactly `demand`, so any non-negative slack
    # succeeds and the fault rate is flat in tau.
    n_blocked = int(round(tau * 2.0 * len(jobs)))
    horizon = capacity + n_blocked

    # Spread them evenly (with jitter) rather than sampling uniformly.
    # Uniformly sampled blocks cluster, which leaves one long free run that
    # absorbs every job -- clustered blocks do not fragment the horizon, and
    # fragmentation is what makes a tight margin bite.
    blocked: List[int] = []
    if n_blocked:
        step = horizon / (n_blocked + 1)
        for i in range(n_blocked):
            s = int(round((i + 1) * step)) + rng.choice([-1, 0, 0, 1])
            blocked.append(min(horizon - 1, max(0, s)))
        blocked = sorted(set(blocked))

    obs = [Observation(slot=s,
                       status=BUSY if s in blocked else FREE,
                       timestamp=100 + s)
           for s in range(horizon)]

    dead_slot = lying_slot = None
    if dead_sensor and blocked:
        # A genuinely BUSY slot whose sensor emits nothing at all.
        # Downstream CAN see the gap, so an expressible repair exists.
        dead_slot = blocked[0]
        obs = [o for o in obs if o.slot != dead_slot]
    elif lying_sensor and blocked:
        # A genuinely BUSY slot whose sensor confidently reports FREE.
        # Nothing any agent observes distinguishes this from a real FREE,
        # so NO expressible repair exists -- Theorem 5.2 case 4.
        lying_slot = blocked[0]
        obs = [Observation(o.slot, FREE, o.timestamp) if o.slot == lying_slot
               else o for o in obs]

    return Task(jobs=jobs, horizon=horizon, observations=obs,
                blocked_slots=blocked, tau=tau, delta=delta, seed=seed,
                dead_sensor_slot=dead_slot, lying_sensor_slot=lying_slot)


# ---------------------------------------------------------------- requirement

@dataclass
class Schedule:
    starts: Dict[str, int] = field(default_factory=dict)

    def as_intervals(self, jobs: List[Job]):
        by_id = {j.id: j for j in jobs}
        out = []
        for jid, st in self.starts.items():
            if jid in by_id:
                out.append((jid, st, st + by_id[jid].duration))
        return sorted(out, key=lambda t: t[1])


def requirement_violations(task: Task, sched: Schedule) -> List[str]:
    """Ground-truth check of R against the TRUE world state."""
    v = []
    ivs = sched.as_intervals(task.jobs)
    ids = {i[0] for i in ivs}

    for j in task.jobs:
        if j.id not in ids:
            v.append(f"unscheduled:{j.id}")

    for jid, s, e in ivs:
        if s < 0 or e > task.horizon:
            v.append(f"horizon:{jid}")
        for b in task.blocked_slots:
            if s <= b < e:
                v.append(f"blocked_slot:{jid}@{b}")

    for a, b in zip(ivs, ivs[1:]):
        if b[1] < a[2]:
            v.append(f"overlap:{a[0]}~{b[0]}")
        elif b[1] - a[2] < SEP_MIN:
            v.append(f"separation:{a[0]}~{b[0]}")

    return v


def R_holds(task: Task, sched: Schedule) -> bool:
    return not requirement_violations(task, sched)


def _hidden_slots(task: Task) -> set:
    return {task.dead_sensor_slot, task.lying_sensor_slot} - {None}


def _cliff(magnitude: int, total_slack: int) -> float:
    """
    Charge for one violation of R: 1 + magnitude / slack, or 0 if none.

    Remark 7.3: R has a cliff. Crossing the constraint boundary is a
    rejection, not a proportional cost, so every violation costs at least the
    whole budget -- that is what puts M below zero whenever R fails
    (Definition 7.4's sign convention). The magnitude term only orders
    violations among themselves; it never makes one cheap.
    """
    return 1.0 + magnitude / total_slack if magnitude > 0 else 0.0


def _blocked_covered(s: int, e: int, slots) -> int:
    return sum(1 for b in slots if s <= b < e)


def consumed_margin(task: Task, sched: Schedule) -> Dict[str, float]:
    """
    Per-job share of margin depletion attributable to AGENT DECISIONS.

    This is the single source of truth for the accounting; margin() is
    derived from it and exogenous_depletion(), so the depletion identity
        1 - M = sum(cons) + exo
    holds exactly by construction. Units: 1.0 = the whole slack budget.

    Non-violating slack use is charged proportionally, in slots / slack:
      - extra gap before the job beyond SEP_MIN (for the first job: its
        start offset from slot 0)
    Violations of R are charged by the cliff rule, 1 + magnitude / slack
    (Remark 7.3 -- see _cliff), with magnitude in slots:
      - gap shortfall: SEP_MIN - gap, when gap < SEP_MIN (includes overlap)
      - blocked overlap: VISIBLE blocked slots the job covers
      - horizon overrun: slots the job places outside [0, horizon)
      - unscheduled: the job's duration
    A collision with a slot the agents could not know was occupied (dead or
    lying sensor) is NOT charged here -- it is exogenous depletion. Charging
    it to an agent would make D1 empty by construction, which is exactly the
    defect the depletion identity exists to prevent.

    Linear decomposition, valid only because this domain has a single
    linearly-composing constraint (Remark 7.7).
    """
    total_slack = max(1, task.slack())
    ivs = sched.as_intervals(task.jobs)
    cons = {j.id: 0.0 for j in task.jobs}
    scheduled = {jid for jid, _, _ in ivs}
    for j in task.jobs:
        if j.id not in scheduled:
            cons[j.id] += _cliff(j.duration, total_slack)

    hidden = _hidden_slots(task)
    visible = [b for b in task.blocked_slots if b not in hidden]
    prev_end = None
    for jid, s, e in ivs:
        if prev_end is None:
            cons[jid] += max(0, s) / total_slack     # leading offset
        else:
            gap = s - prev_end
            cons[jid] += max(0, gap - SEP_MIN) / total_slack
            cons[jid] += _cliff(max(0, SEP_MIN - gap), total_slack)
        cons[jid] += _cliff(max(0, -s) + max(0, e - task.horizon),
                            total_slack)
        cons[jid] += _cliff(_blocked_covered(s, e, visible), total_slack)
        prev_end = e
    return cons


def exogenous_depletion(task: Task, sched: Schedule) -> float:
    """
    Depletion no agent decision explains: collisions with slots whose sensor
    was dead or lying. exo(rho) in Definition 7.8. Same cliff rule as
    consumed_margin (Remark 7.3): 1 + covered hidden slots / slack, per job.
    """
    total_slack = max(1, task.slack())
    hidden = _hidden_slots(task)
    return sum(_cliff(_blocked_covered(s, e, hidden), total_slack)
               for _, s, e in sched.as_intervals(task.jobs))


def margin(task: Task, sched: Schedule) -> float:
    """
    Scalar system margin M(rho): 1 at nominal (all slack unused), falling as
    slack is spent, and below 0 whenever R fails -- every violation costs at
    least the whole budget under the cliff rule (Remark 7.3, see _cliff).

    Defined as 1 - sum(cons) - exo so the depletion identity holds exactly.
    There is deliberately no separate accounting here: an independent
    formula would drift from consumed_margin() and the gap would land in exo.
    """
    return (1.0 - sum(consumed_margin(task, sched).values())
            - exogenous_depletion(task, sched))


def task_to_prompt_block(task: Task) -> str:
    lines = [f"HORIZON: slots 0..{task.horizon - 1}",
             f"MIN_GAP_BETWEEN_JOBS: {SEP_MIN}", "JOBS:"]
    for j in task.jobs:
        lines.append(f"  {j.id} duration={j.duration}")
    lines.append("SENSOR_READINGS:")
    for o in sorted(task.observations, key=lambda o: o.slot):
        lines.append(f"  slot={o.slot} status={o.status} t={o.timestamp}")
    return "\n".join(lines)
