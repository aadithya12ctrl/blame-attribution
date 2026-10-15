"""
Experiment 1 -- the seeded case table.

Runs the A-E scenarios and prints the contract evaluator's verdict for
each. This is the table that carries the paper: it shows WHERE competing
methods fail and why, not just by how much.

Then re-scores D and E against a second corpus that contains dead-sensor
runs, because corpus composition decides between REPAIRABLE and
CORPUS_BLOCKED (Remark 5.3a). The table is not reportable without it.

  FA_MOCK=1 python3 experiments/exp_cases.py          # offline sanity check
  OPENROUTER_API_KEY=... python3 experiments/exp_cases.py
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from faultattr import make_task, LLM, run_pipeline, attribute, format_verdict  # noqa: E402
from faultattr.agents import finish_reasons, served_by  # noqa: E402
from faultattr.attribute import NO_FAILURE  # noqa: E402
from faultattr.domain import UNKNOWN  # noqa: E402
from faultattr.llm import now_iso  # noqa: E402
from faultattr.agents import PROMPT_VERSION  # noqa: E402

WORKERS = 5          # runs in parallel; agents stay sequential within a run

# (label, tau, dead_sensor, lying_sensor, injected agents)
# A runs at tau=0: no blocked slots, so the injected shift can only produce a
# separation violation (at 0.3 it can land on a blocked slot instead).
SCENARIOS = [
    ("A  direct violation",   0.00, False, False, ["planner"]),
    ("B  inherited drift",    0.30, False, False, ["observer"]),
    ("C  overdetermination",  0.30, False, False,
     ["planner", "validator", "executor"]),
    ("D  missing obligation", 0.30, True,  False, []),
    ("E  inexpressible",      0.30, False, True,  []),
]


def build_corpus(llm, seeds, dead_frac: float = 0.0,
                 log: list | None = None) -> list:
    """
    Sigma_ok: successful, conformant runs. Needed for (R3).

    dead_frac is NOT a tuning knob. The first round(dead_frac * len(seeds))
    tasks use a dead sensor, so the corpus can contain runs with UNKNOWN
    slots -- and whether it does decides whether scenario D's repairs are
    blocked by (R3). It decides the verdict. Report corpus composition with
    any case-3 (CORPUS_BLOCKED / REPAIRABLE) verdict.

    If `log` is given, one line per excluded run is appended to it.
    """
    seeds = list(seeds)
    n_dead = int(round(dead_frac * len(seeds)))

    def one(i_s):
        i, s = i_s
        task = make_task(tau=0.2, delta=0, seed=s, dead_sensor=i < n_dead)
        return s, i < n_dead, run_pipeline(task, llm)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(one, enumerate(seeds)))

    corpus = []
    for s, dead, run in results:
        v = attribute(run)
        if v.kind == NO_FAILURE and not v.phi:
            corpus.append(run)
        elif log is not None:
            why = (v.notes[0] if v.notes else "") if not v.phi else \
                f"fault set {v.phi}"
            log.append(f"seed={s} dead={dead}: {v.kind} {why} "
                       f"R={v.R_violations} finish={finish_reasons(run)}")
    return corpus


def _has_unknown(run) -> bool:
    obs = run.by_agent("observer")
    st = (obs[0].meta.get("projected") if obs else None) or {}
    return any(v == UNKNOWN for v in st.values())


def main(seed: int = 7, model: str | None = None) -> None:
    llm = LLM(**({"model": model} if model else {}))
    d = llm.describe()
    print(f"model={d['model']}  provider={d['provider']}  "
          f"prompt_version={PROMPT_VERSION}  date={now_iso()}\n")

    log1: list = []
    corpus = build_corpus(llm, range(seed + 100, seed + 108), dead_frac=0.0,
                          log=log1)
    print(f"Sigma_ok: {len(corpus)} conformant successful runs "
          f"(clean-only corpus: dead_frac=0.0, no UNKNOWN slots)")
    for ln in log1:
        print(f"  excluded from corpus: {ln}")
    print()

    def one(sc):
        label, tau, dead, lying, inject = sc
        task = make_task(tau=tau, delta=0, seed=seed,
                         dead_sensor=dead, lying_sensor=lying)
        return run_pipeline(task, llm, inject=inject)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        scen_runs = list(ex.map(one, SCENARIOS))

    runs = {}
    for (label, tau, dead, lying, inject), run in zip(SCENARIOS, scen_runs):
        runs[label[0]] = run
        v = attribute(run, corpus=corpus)
        print("=" * 70)
        print(f"{label}    injected = {inject or 'none'}")
        print("=" * 70)
        print(format_verdict(v))
        print(f"  finish_reason: {finish_reasons(run)}   "
              f"served_by: {served_by(run)}")
        print()

    # ------------------------------------------------ corpus sensitivity
    log2: list = []
    corpus2 = build_corpus(llm, range(seed + 200, seed + 208), dead_frac=0.75,
                           log=log2)
    n_unk = sum(1 for r in corpus2 if _has_unknown(r))
    print("=" * 70)
    print("CORPUS SENSITIVITY (Remark 5.3a)")
    print("=" * 70)
    for ln in log2:
        print(f"  excluded from corpus 2: {ln}")
    print(f"  corpus 1: {len(corpus)} runs, dead_frac=0.00, "
          f"{sum(1 for r in corpus if _has_unknown(r))} contain UNKNOWN slots")
    print(f"  corpus 2: {len(corpus2)} runs, dead_frac=0.75, "
          f"{n_unk} contain UNKNOWN slots  (disjoint seeds)")
    print("  Same runs, re-scored; only the corpus differs.\n")
    for key in ("D", "E"):
        v1 = attribute(runs[key], corpus=corpus)
        v2 = attribute(runs[key], corpus=corpus2)
        tag = "FLIPPED" if v1.kind != v2.kind else "stable"
        print(f"  {key}:  corpus1 -> {v1.kind:<24} corpus2 -> {v2.kind:<24}"
              f"  {tag}")


if __name__ == "__main__":
    main(seed=int(sys.argv[1]) if len(sys.argv) > 1 else 7,
         model=sys.argv[2] if len(sys.argv) > 2 else None)
