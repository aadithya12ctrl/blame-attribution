"""
Experiment 3 -- projection error rate (Definition 8.2, Proposition 8.3).

Every verdict the framework produces is bounded by how reliably free text is
turned into typed state. Run this FIRST on any new model. If eps is high, the
attribution results are not interpretable and no amount of contract quality
fixes that.

The bound quoted is the unconditional union bound 2nk*eps. The tighter product
form requires independent evaluation errors, which almost certainly does not
hold here (one misprojected slot flips several predicates), so it is not used.

  OPENROUTER_API_KEY=... python3 experiments/exp_epsilon.py --n 30
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faultattr import make_task, LLM, run_pipeline  # noqa: E402
from faultattr.projection import measure_epsilon  # noqa: E402
from faultattr.agents import AGENTS  # noqa: E402
from faultattr.llm import now_iso  # noqa: E402
from faultattr.agents import PROMPT_VERSION  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--model", default=None)
    ap.add_argument("--dead-sensor-frac", type=float, default=0.3)
    ap.add_argument("--workers", type=int, default=5,
                    help="runs in parallel; agents stay sequential per run")
    a = ap.parse_args()

    llm = LLM(**({"model": a.model} if a.model else {}))
    meta = {**llm.describe(), "prompt_version": PROMPT_VERSION,
            "date": now_iso()}
    print(f"  model={meta['model']} provider={meta['provider']} "
          f"prompt_version={PROMPT_VERSION} date={meta['date']}")

    def one(i):
        dead = (i % 10) < int(a.dead_sensor_frac * 10)
        task = make_task(tau=0.3, delta=i % 3, seed=1000 + i,
                         dead_sensor=dead)
        return run_pipeline(task, llm)

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        runs = list(ex.map(one, range(a.n)))

    # finish_reason and serving provider, per agent, recorded with the result
    finish = {ag: dict(Counter(str(inv.meta.get("finish_reason"))
                               for r in runs for inv in r.by_agent(ag)))
              for ag in AGENTS}
    served = dict(Counter(str(inv.meta.get("served_by"))
                          for r in runs for inv in r.invocations))

    eps = measure_epsilon(runs)
    e = eps["eps_used_for_bound"]

    n_agents = len(AGENTS)
    k = 1                      # one invocation per agent in this pipeline
    bound = min(1.0, 2 * n_agents * k * e)

    print("\n" + "=" * 60)
    print("PROJECTION ACCURACY")
    print("=" * 60)
    for key, val in eps.items():
        print(f"  {key}: {val}")
    print(f"  finish_reason by agent: {finish}")
    print(f"  served_by: {served}")

    rule3 = None
    if e == 0:
        # Zero observed errors is not zero error. The binding sample size is
        # invocations per agent: parse failures are measured per invocation.
        N = eps["invocations_per_agent"]
        e3 = 3.0 / N if N else float("nan")
        rule3 = min(1.0, 2 * n_agents * k * e3)
        print(f"\n  no projection errors observed in N={N} invocations per "
              f"agent; eps = 0 is NOT a result.")
        print(f"  rule of three (95%):  eps <~ 3/N = {e3:.4f}")
        print(f"  union bound on P[Phi_hat != Phi]  <~  2*n*k*eps"
              f"  =  2*{n_agents}*{k}*{e3:.4f}  =  {rule3:.4f}")
        if rule3 >= 1.0:
            print("  BOUND IS VACUOUS at this N. Increase --n before "
                  "reporting attribution accuracy.")
    else:
        print(f"\n  union bound on P[Phi_hat != Phi]  <=  2*n*k*eps"
              f"  =  2*{n_agents}*{k}*{e:.4f}  =  {bound:.4f}")
        if bound >= 1.0:
            print("  BOUND IS VACUOUS. Report this; do not report attribution "
                  "accuracy as if it were interpretable.")
    print("\n  NOTE: parse failures are measured at every stage. Only the "
          "observer has\n  ground truth independent of the agent, so "
          "downstream VALUE errors are NOT\n  measured. State this "
          "limitation rather than implying full coverage.")

    # Timestamped name: a re-run never overwrites an earlier result.
    out = f"epsilon_{meta['date'].replace(':', '').replace('+0000', 'Z')}.json"
    json.dump({**meta, **eps, "finish_reason_by_agent": finish,
               "served_by": served, "union_bound": bound,
               "rule_of_three_bound": rule3}, open(out, "w"), indent=2)
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()
