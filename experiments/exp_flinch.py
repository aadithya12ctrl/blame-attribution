"""
Experiment 2 -- the flinch hypothesis (Hypothesis 10.2).

Two sweeps, run independently. This separation IS the experiment; without the
second arm you cannot tell strain from difficulty, and reporting the first arm
alone would be the exact error the framework accuses LLM judges of.

  ARM 1 (tau):   tighten the margin at fixed complexity
  ARM 2 (delta): raise complexity at fixed margin

Tests, with slopes multiplied by their manipulated ranges so the criterion is
invariant to how either axis is parameterized:

  (H1)  s_tau * range(tau)  >  0
  (H2)  |s_delta * range(delta)| / |s_tau * range(tau)|  <=  gamma

PRE-REGISTER YOUR PSI CANDIDATES. The set below is fixed in code on purpose:
"there exists psi" over a family searched post hoc is close to unfalsifiable.
If you add a candidate, say so in the writeup and correct for multiplicity.

  FA_MOCK=1 python3 experiments/exp_flinch.py            # plumbing check only
  OPENROUTER_API_KEY=... python3 experiments/exp_flinch.py --k 5 --seeds 6
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics as st
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faultattr import make_task, LLM, run_pipeline, attribute  # noqa: E402
from faultattr.agents import PROMPTS, finish_reasons, served_by  # noqa: E402
from faultattr.llm import now_iso  # noqa: E402
from faultattr.agents import PROMPT_VERSION  # noqa: E402
from faultattr.attribute import UNATTRIBUTABLE  # noqa: E402
from faultattr.projection import project_planner, ProjectionError  # noqa: E402

# ----------------------------------------------------- pre-registered psi set

HEDGES = ["might", "maybe", "unclear", "assum", "unsure", "possibly",
          "appears", "seems", "cannot determine", "ambiguous", "if ",
          "however", "note that", "uncertain", "not possible", "conflict"]
ASKS = ["could you", "please clarify", "need more", "which ", "?"]


def psi_metrics(texts: List[str]) -> Dict[str, float]:
    """All psi candidates, computed together. Fixed set -- do not extend
    silently."""
    low = [t.lower() for t in texts]
    hedge = [sum(t.count(h) for h in HEDGES) for t in low]
    ask = [sum(t.count(a) for a in ASKS) for t in low]
    length = [len(t.split()) for t in texts]

    # extra-block verbosity: words outside the required PLAN...END block
    extra = []
    for t in texts:
        m = re.search(r"PLAN(.*?)END", t, re.S | re.I)
        inside = len(m.group(1).split()) if m else 0
        extra.append(max(0, len(t.split()) - inside))

    # sampling disagreement: fraction of sampled plans that differ from modal
    def plan_key(t):
        try:
            return tuple(sorted(project_planner(t).starts.items()))
        except ProjectionError:
            return ()
    plans = [plan_key(t) for t in texts]
    parse_fail = sum(1 for p in plans if not p) / max(1, len(plans))
    good = [p for p in plans if p]
    if len(good) > 1:
        modal = max(set(good), key=good.count)
        disagree = sum(1 for p in good if p != modal) / len(good)
    else:
        disagree = 0.0

    return {
        "psi_hedge": st.mean(hedge),
        "psi_ask": st.mean(ask),
        "psi_len": st.mean(length),
        "psi_extra": st.mean(extra),
        "psi_disagree": disagree,
        "psi_parsefail": parse_fail,
    }


PSI_KEYS = ["psi_hedge", "psi_ask", "psi_len", "psi_extra",
            "psi_disagree", "psi_parsefail"]


# --------------------------------------------------------------------- sweeps

def planner_prompt(task, llm) -> str:
    """Run the pipeline up to the planner and return the planner's input."""
    run = run_pipeline(task, llm)
    return run.by_agent("planner")[0].prompt_in, run


def sweep(llm, taus, deltas, seeds, k, arm: str,
          workers: int = 5) -> List[dict]:
    """
    arm is written into every row; analyse() selects arms by it alone.
    Configs run in parallel; within a config the pipeline and the k samples
    stay sequential. Rows come back in config order.
    """
    meta = {**llm.describe(), "prompt_version": PROMPT_VERSION,
            "date": now_iso()}
    configs = [(tau, delta, seed) for tau in taus for delta in deltas
               for seed in seeds]

    def one(cfg):
        tau, delta, seed = cfg
        task = make_task(tau=tau, delta=delta, seed=seed)
        prompt, run = planner_prompt(task, llm)
        reps = llm.sample(PROMPTS[run.prompt_version]["planner"], prompt, k)
        return cfg, task, run, reps

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(one, configs))

    rows = []
    for (tau, delta, seed), task, run, reps in results:
        texts = [r.text for r in reps if r.ok]
        if not texts:
            continue
        m = psi_metrics(texts)
        v = attribute(run)
        fin = Counter(str(r.finish_reason) for r in reps if r.ok)
        rows.append({
            "arm": arm,
            "tau": tau, "delta": delta, "seed": seed, "k": len(texts),
            "slack": task.slack(), "n_jobs": len(task.jobs),
            "planner_at_fault": int("planner" in v.phi),
            "any_fault": int(bool(v.phi)),
            "R_failed": int(bool(v.R_violations)),
            "unattributable": int(v.kind == UNATTRIBUTABLE),
            "verdict": v.kind,
            **m,
            "model": meta["model"], "provider": meta["provider"],
            "prompt_version": run.prompt_version, "date": meta["date"],
            "pipeline_finish_reason": finish_reasons(run),
            "sample_finish_reason": "|".join(f"{f}:{n}" for f, n in
                                             sorted(fin.items())),
            "served_by": served_by(run),
        })
        print(f"  tau={tau:.2f} delta={delta} seed={seed} "
              f"fault={'planner' in v.phi} "
              f"{'UNATTRIB ' if v.kind == UNATTRIBUTABLE else ''}"
              f"hedge={m['psi_hedge']:.1f} dis={m['psi_disagree']:.2f} "
              f"samples[{rows[-1]['sample_finish_reason']}]")
    return rows


def slope(xs, ys) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return 0.0 if den == 0 else sum((x - mx) * (y - my)
                                    for x, y in zip(xs, ys)) / den


def analyse(rows, taus, deltas, gamma) -> dict:
    """Range-standardized (H1)/(H2). See Hypothesis 10.2."""
    r_tau = max(taus) - min(taus)
    r_del = max(deltas) - min(deltas) if len(deltas) > 1 else 0

    # Membership by label, never by parameter value: inferring it from
    # delta==min / tau==min put the shared corner cell in both regressions.
    arm1 = [r for r in rows if r["arm"] == "tau"]
    arm2 = [r for r in rows if r["arm"] == "delta"]
    assert len(arm1) + len(arm2) == len(rows), "arms overlap or rows unlabeled"

    out = {"_n": {"arm1_tau": len(arm1), "arm2_delta": len(arm2),
                  "total": len(rows)}}
    for key in PSI_KEYS:
        s_tau = slope([r["tau"] for r in arm1], [r[key] for r in arm1])
        s_del = (slope([r["delta"] for r in arm2], [r[key] for r in arm2])
                 if r_del else 0.0)
        e_tau, e_del = s_tau * r_tau, s_del * r_del
        ratio = abs(e_del) / abs(e_tau) if abs(e_tau) > 1e-12 else float("inf")
        out[key] = {
            "effect_tau": round(e_tau, 4),
            "effect_delta": round(e_del, 4),
            "ratio": round(ratio, 4) if ratio != float("inf") else None,
            "H1_pass": bool(e_tau > 0),
            "H2_pass": bool(ratio <= gamma),
            "FLINCH": bool(e_tau > 0 and ratio <= gamma),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5, help="samples per config")
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--gamma", type=float, default=0.2)
    ap.add_argument("--model", default=None)
    ap.add_argument("--out", default="flinch.csv")
    ap.add_argument("--workers", type=int, default=5,
                    help="configs in parallel; sequential within a config")
    a = ap.parse_args()

    taus = [0.0, 0.2, 0.4, 0.6, 0.8, 0.95]
    deltas = [0, 1, 2, 3]
    seeds = list(range(a.seeds))
    seeds2 = [s + 500 for s in seeds]      # disjoint block: no shared cells
    tau_arm2 = 0.3

    llm = LLM(**({"model": a.model} if a.model else {}))
    meta = {**llm.describe(), "prompt_version": PROMPT_VERSION,
            "date": now_iso()}
    print(f"model={meta['model']}  provider={meta['provider']}  "
          f"prompt_version={PROMPT_VERSION}  date={meta['date']}")

    print("ARM 1: tightening margin at fixed complexity")
    rows = sweep(llm, taus, [0], seeds, a.k, arm="tau", workers=a.workers)
    print(f"\nARM 2: raising complexity at fixed margin (tau={tau_arm2})")
    rows += sweep(llm, [tau_arm2], deltas, seeds2, a.k, arm="delta",
                  workers=a.workers)

    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    res = analyse(rows, taus, deltas, a.gamma)
    n = res.pop("_n")
    print(f"\nrows: arm1(tau)={n['arm1_tau']}  arm2(delta)={n['arm2_delta']}"
          f"  total={n['total']}  (disjoint)")

    # Activation curve (Definition 9.3), arm 1 only. Unattributable runs are
    # projection failures and are excluded from the denominator.
    print("\nACTIVATION CURVE  (planner fault rate by tau, arm 1)")
    any_fault = False
    for t in taus:
        g = [r for r in rows if r["arm"] == "tau" and r["tau"] == t
             and not r["unattributable"]]
        nf = sum(r["planner_at_fault"] for r in g)
        any_fault |= nf > 0
        excl = sum(1 for r in rows if r["arm"] == "tau" and r["tau"] == t
                   and r["unattributable"])
        print(f"  tau={t:.2f}  faults={nf}/{len(g)}"
              + (f"  ({excl} unattributable excluded)" if excl else ""))
    if not any_fault:
        print("  WARNING: zero faults at every tau. tau*(alpha) is not "
              "estimable and the\n  flinch test is UNINTERPRETABLE on this "
              "domain -- void, not negative.")

    print("\n" + "=" * 66)
    print(f"HYPOTHESIS 10.2  (gamma = {a.gamma}, "
          f"{len(PSI_KEYS)} pre-registered candidates)")
    print("=" * 66)
    for k, r in res.items():
        flag = "FLINCH" if r["FLINCH"] else ("H1 only" if r["H1_pass"]
                                             else "-")
        print(f"  {k:<15} eff_tau={r['effect_tau']:>8}  "
              f"eff_delta={r['effect_delta']:>8}  ratio={r['ratio']}  {flag}")

    winners = [k for k, r in res.items() if r["FLINCH"]]
    print("\n" + ("PASS: " + ", ".join(winners) if winners else
                  "NO CANDIDATE PASSES BOTH CLAUSES"))
    print(f"Multiplicity: {len(PSI_KEYS)} candidates tested. "
          f"Correct for this before claiming a result.")
    json.dump({"_meta": meta, **res, "_n": n},
              open(a.out.replace(".csv", "_analysis.json"), "w"), indent=2)
    print(f"\nwrote {a.out} and analysis json")


if __name__ == "__main__":
    main()
