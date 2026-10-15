"""
Screen agent-model candidates against a FIXED qualification bar. Stops at the
first candidate that qualifies. Nothing here is tuned after results.

BAR (all must hold):
  1. clean corpus, tau=0.2, seeds 107..114: >= 7/8 conformant successful runs
  2. scenarios A-E (seed 7, as exp_cases.py) match expected verdict AND fault set
  3. zero projection failures and zero truncations across all 13 runs

PROVIDER RULE (fixed before any result): the first-party endpoint if one
serves the model; otherwise the status-0 endpoint with the highest 30-minute
uptime among those at or under the price ceiling, cheaper on ties. The exact
endpoint tag is pinned, fallback disabled.

Price ceiling $2 per 1M output tokens, checked on the /api/v1/models list price
and on the pinned endpoint. Cumulative screening cost is capped at $0.50,
estimated from returned token counts x pinned endpoint price; a candidate is
not started if its projected cost would breach the cap.

  OPENROUTER_API_KEY=... python3 experiments/screen_models.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr import LLM, make_task, run_pipeline, attribute  # noqa: E402
from faultattr.agents import finish_reasons, served_by, PROMPTS  # noqa: E402
from faultattr.projection import (project_planner,  # noqa: E402
                                  project_validator, ProjectionError)
from faultattr.attribute import (AGENT_FAULT, REPAIRABLE,  # noqa: E402
                                 INEXPRESSIBLE, NO_FAILURE)
from faultattr.llm import now_iso  # noqa: E402
from exp_cases import SCENARIOS  # noqa: E402

CANDIDATES = ["deepseek/deepseek-chat",
              "deepseek/deepseek-chat-v3.1",
              "google/gemini-2.0-flash-001",
              "mistralai/mistral-small-3.2-24b-instruct"]
FIRST_PARTY = {"deepseek": "deepseek", "google": "google",
               "mistralai": "mistral"}
OUT_CEILING = 2.0            # $ per 1M output tokens
COST_CAP = 0.50              # $ cumulative across the screen
CORPUS_SEEDS = list(range(107, 115))
CORPUS_MIN = 7
SCEN_SEED = 7
EXPECTED = {"A": (AGENT_FAULT, {"planner"}), "B": (AGENT_FAULT, {"observer"}),
            "C": (AGENT_FAULT, {"planner", "validator", "executor"}),
            "D": (REPAIRABLE, set()), "E": (INEXPRESSIBLE, set())}
WORKERS = 5
CALLS_PER_MODEL = (len(CORPUS_SEEDS) + len(SCENARIOS)) * 5

# Prior result, from results/qwen_20260922-110335/cases_20260922-110445.txt
# (not re-run). Reported alongside the screen so every model tried appears.
PRIOR = [{"model": "qwen/qwen3-235b-a22b-2507", "provider": "alibaba",
          "source": "results/qwen_20260922-110335/cases_20260922-110445.txt",
          "corpus_conformant": "1/8",
          "scenarios": {"A": "FAIL {planner, validator}", "B": "ok",
                        "C": "ok", "D": "FAIL AGENT_FAULT {validator}",
                        "E": "ok"},
          "projection_failures": 0, "truncations": 0,
          "qualifies": False,
          "note": "planner ignores separation (gap 0 in 3 of 4 sampled "
                  "violations); validator accepts infeasible plans"}]


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def pick_provider(model, endpoints):
    """The fixed provider rule. Returns (endpoint, reason)."""
    author = model.split("/")[0]
    fp = FIRST_PARTY.get(author, author)
    ok = [e for e in endpoints
          if float(e["pricing"]["completion"]) * 1e6 <= OUT_CEILING]
    first = [e for e in ok if (e.get("tag") or "").split("/")[0] == fp
             or e["provider_name"].lower() == fp]
    if first:
        return first[0], "first-party"
    live = [e for e in ok if (e.get("status") or 0) == 0]
    if not live:
        return None, "no status-0 endpoint under the ceiling"
    live.sort(key=lambda e: (-(e.get("uptime_last_30m") or 0),
                             float(e["pricing"]["completion"])))
    return live[0], "highest 30m uptime among status-0 under ceiling"


def gap_stats(raw_records, task_seed_tau):
    """
    On clean-corpus planner outputs: gaps of violating consecutive pairs,
    under the evaluator's definition next_start - (start + duration), split
    into gap 0 (or less), gap 1, other; and how many plans with a separation
    violation the validator ACCEPTED.
    """
    gaps = {"gap<=0": 0, "gap=1": 0, "other": 0}
    infeasible = accepted = 0
    for r in raw_records:
        task = make_task(tau=task_seed_tau, delta=0, seed=r["seed"])
        dur = {j.id: j.duration for j in task.jobs}
        try:
            starts = project_planner(r["planner_out"]).starts
        except ProjectionError:
            continue
        ivs = sorted((s, j) for j, s in starts.items() if j in dur)
        g = [b[0] - (a[0] + dur[a[1]]) for a, b in zip(ivs, ivs[1:])]
        bad = [x for x in g if x < 2]
        for x in bad:
            gaps["gap<=0" if x <= 0 else "gap=1" if x == 1 else "other"] += 1
        if bad:
            infeasible += 1
            try:
                dec = project_validator(r["validator_out"])["decision"]
            except ProjectionError:
                dec = "?"
            accepted += dec == "ACCEPT"
    return gaps, infeasible, accepted


def screen(model, endpoint, raw_path, prompt_version="v1"):
    tag = endpoint["tag"]
    llm = LLM(model=model, provider=tag)
    date = now_iso()

    jobs = ([("corpus", None, 0.2, False, False, [], s) for s in CORPUS_SEEDS]
            + [("scenario", lab[0], tau, dead, lying, inj, SCEN_SEED)
               for lab, tau, dead, lying, inj in SCENARIOS])

    def one(j):
        kind, scen, tau, dead, lying, inj, s = j
        task = make_task(tau=tau, delta=0, seed=s, dead_sensor=dead,
                         lying_sensor=lying)
        return j, run_pipeline(task, llm, inject=inj,
                               prompt_version=prompt_version)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(one, jobs))

    corpus = []
    proj_fail = trunc = bg_runs = api_err = 0
    raw_corpus = []
    with open(raw_path, "w", encoding="utf-8") as f:
        for (kind, scen, tau, dead, lying, inj, s), run in results:
            # A call with no reply (rate limit, outage) yields empty text and
            # so a projection error; count it as an API error, not as eps.
            api_err += sum(1 for i in run.invocations if not i.ok)
            pf = [(i.agent, i.meta["projection_error"])
                  for i in run.invocations
                  if i.ok and i.meta.get("projection_error")]
            tr = [i.agent for i in run.invocations
                  if i.meta.get("finish_reason") == "length"]
            proj_fail += len(pf)
            trunc += len(tr)
            if kind == "corpus":
                v = attribute(run)
                if v.kind == NO_FAILURE and not v.phi:
                    corpus.append(run)
            pl, va = run.by_agent("planner")[0], run.by_agent("validator")[0]
            rec = {
                "model": model, "provider": tag, "date": date,
                "prompt_version": run.prompt_version,
                "kind": kind, "scenario": scen, "seed": s, "tau": tau,
                "finish_reason": finish_reasons(run),
                "served_by": served_by(run),
                "projection_errors": pf, "truncated": tr,
                "planner_in": pl.prompt_in, "planner_out": pl.raw_out,
                "validator_in": va.prompt_in, "validator_out": va.raw_out,
            }
            f.write(json.dumps(rec) + "\n")
            if kind == "corpus":
                raw_corpus.append(rec)

    # background fault: any agent in the fault set that was NOT injected.
    # Rate over all 13 runs (corpus faults count against corpus runs; the
    # scenario verdict uses the clean corpus built above).
    for (kind, scen, tau, dead, lying, inj, s), run in results:
        v = attribute(run) if kind == "corpus" else attribute(run,
                                                              corpus=corpus)
        bg_runs += bool(set(v.phi) - set(inj))

    scen_out = {}
    for (kind, scen, *_r), run in results:
        if kind != "scenario":
            continue
        v = attribute(run, corpus=corpus)
        want_kind, want_phi = EXPECTED[scen]
        ok = v.kind == want_kind and set(v.phi) == want_phi
        scen_out[scen] = ("ok" if ok else
                          f"FAIL {v.kind} {set(v.phi) or '{}'}"
                          + (f" R={v.R_violations}" if not ok else ""))

    cost = (llm.prompt_tokens * float(endpoint["pricing"]["prompt"])
            + llm.completion_tokens * float(endpoint["pricing"]["completion"]))
    n_ok = len(corpus)
    measured = api_err == 0
    qualifies = (measured and n_ok >= CORPUS_MIN
                 and all(x == "ok" for x in scen_out.values())
                 and proj_fail == 0 and trunc == 0)
    corpus_fail = []
    for (kind, *_r, s), run in results:
        if kind == "corpus" and all(run is not c for c in corpus):
            v = attribute(run)
            corpus_fail.append(f"seed={s}: {v.kind} {v.phi or ''} "
                               f"R={v.R_violations}")
    gaps, infeasible, accepted = gap_stats(raw_corpus, 0.2)
    return {"model": model, "provider": tag, "date": date,
            "prompt_version": prompt_version,
            "corpus_conformant": f"{n_ok}/{len(CORPUS_SEEDS)}",
            "background_fault_rate": f"{bg_runs}/{len(results)}",
            "violation_gaps": gaps,
            "validator_accepted_infeasible": f"{accepted}/{infeasible}",
            "corpus_failures": corpus_fail, "scenarios": scen_out,
            "projection_failures": proj_fail, "truncations": trunc,
            "api_errors": api_err, "measured": measured,
            "served_by": sorted({served_by(r) for _, r in results}),
            "tokens": {"prompt": llm.prompt_tokens,
                       "completion": llm.completion_tokens},
            "cost_est": round(cost, 5), "qualifies": qualifies,
            "raw_file": os.path.relpath(raw_path, ROOT)}


# Providers pinned in the v1 screen (screen_20260922-111455 and the earlier
# Qwen run). --same-pins reuses them exactly instead of re-applying the rule,
# whose uptime inputs drift.
V1_PINS = {"deepseek/deepseek-chat": "streamlake",
           "deepseek/deepseek-chat-v3.1": "novita/fp8",
           "mistralai/mistral-small-3.2-24b-instruct": "deepinfra/fp8",
           "qwen/qwen3-235b-a22b-2507": "alibaba"}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt-version", default="v1", choices=sorted(PROMPTS))
    ap.add_argument("--run-all", action="store_true",
                    help="screen every candidate; do not stop at a qualifier")
    ap.add_argument("--same-pins", action="store_true",
                    help="pin the providers used in the v1 screen")
    ap.add_argument("--order", default=",".join(CANDIDATES),
                    help="comma-separated candidates, in selection order")
    a = ap.parse_args()
    order = [m.strip() for m in a.order.split(",") if m.strip()]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outdir = os.path.join(ROOT, "results", f"screen_{a.prompt_version}_{stamp}")
    os.makedirs(outdir, exist_ok=False)
    listing = {m["id"]: m for m in
               _get("https://openrouter.ai/api/v1/models")["data"]}

    log, tried, spent = [], [], 0.0
    P = lambda s="": (print(s, flush=True), log.append(s))  # noqa: E731
    if os.environ.get("FA_MOCK") == "1":
        P("MOCK MODE -- scripted agents; this checks plumbing, not models")
    P(f"MODEL SCREEN {stamp}  prompt_version={a.prompt_version}  "
      f"run_all={a.run_all}  same_pins={a.same_pins}")
    P(f"  bar: corpus >= {CORPUS_MIN}/8, A-E exact, 0 projection failures, "
      f"0 truncations; ceiling ${OUT_CEILING}/M out; cap ${COST_CAP}")
    P(f"  selection order: {order}")
    winner = None
    for model in order:
        P(f"\n=== {model}")
        m = listing.get(model)
        if not m:
            P("  SKIP: not listed on /api/v1/models")
            tried.append({"model": model, "skipped": "not listed"})
            continue
        out_price = float(m["pricing"]["completion"]) * 1e6
        P(f"  list price: in ${float(m['pricing']['prompt']) * 1e6:.3f}/M, "
          f"out ${out_price:.3f}/M")
        if out_price > OUT_CEILING:
            P(f"  SKIP: over ceiling (${out_price:.3f} > ${OUT_CEILING})")
            tried.append({"model": model, "skipped": "over price ceiling"})
            continue
        eps = _get(f"https://openrouter.ai/api/v1/models/{model}/endpoints"
                   )["data"]["endpoints"]
        if a.same_pins:
            want = V1_PINS.get(model)
            hits = [e for e in eps if e.get("tag") == want]
            ep, why = (hits[0], "same pin as v1") if hits else (
                None, f"v1 pin {want!r} no longer serves this model")
            if ep is not None and (float(ep["pricing"]["completion"]) * 1e6
                                   > OUT_CEILING):
                ep, why = None, f"v1 pin {want!r} is over the price ceiling"
        else:
            ep, why = pick_provider(model, eps)
        if ep is None:
            P(f"  SKIP: {why}")
            tried.append({"model": model, "skipped": why})
            continue
        pin_in = float(ep["pricing"]["prompt"])
        pin_out = float(ep["pricing"]["completion"])
        projected = CALLS_PER_MODEL * (1200 * pin_in + 400 * pin_out)
        P(f"  pin: {ep['tag']} ({why}); in ${pin_in * 1e6:.3f}/M out "
          f"${pin_out * 1e6:.3f}/M; projected ~${projected:.3f}")
        if spent + projected > COST_CAP:
            P(f"  STOP: projected cost would breach the ${COST_CAP} cap "
              f"(spent ${spent:.4f})")
            tried.append({"model": model, "skipped": "cost cap"})
            break
        slug = model.replace("/", "_")
        res = screen(model, ep, os.path.join(outdir, f"raw_{slug}.jsonl"),
                     prompt_version=a.prompt_version)
        spent += res["cost_est"]
        tried.append(res)
        P(f"  corpus conformant: {res['corpus_conformant']}")
        for ln in res["corpus_failures"]:
            P(f"    excluded {ln}")
        for s in "ABCDE":
            P(f"  {s}: {res['scenarios'][s]}")
        P(f"  background_fault_rate: {res['background_fault_rate']}   "
          f"violation gaps: {res['violation_gaps']}   validator accepted "
          f"infeasible: {res['validator_accepted_infeasible']}")
        P(f"  projection failures: {res['projection_failures']}   "
          f"truncations: {res['truncations']}   api errors: "
          f"{res['api_errors']}   served_by: {res['served_by']}")
        if not res["measured"]:
            P("  NOT MEASURED: calls returned no reply (API errors); the "
              "numbers above are not a screen result")
        P(f"  cost ~${res['cost_est']:.4f}  (cumulative ~${spent:.4f})")
        P(f"  QUALIFIES: {res['qualifies']}")
        if res["qualifies"] and winner is None:
            winner = model            # first qualifier in selection order
            if not a.run_all:
                break

    prior = PRIOR if a.prompt_version == "v1" else []
    P(f"\n=== SUMMARY  prompt_version={a.prompt_version}"
      + ("  (with prior Qwen result)" if prior else ""))
    for r in prior + tried:
        if "skipped" in r:
            P(f"  {r['model']:<42} skipped: {r['skipped']}")
        else:
            bad = [k for k, v in r["scenarios"].items() if v != "ok"]
            P(f"  {r['model']:<42} @ {r['provider']:<14} corpus "
              f"{r['corpus_conformant']}  A-E fails {bad or 'none'}  "
              f"bg {r.get('background_fault_rate', '?')}  "
              f"gaps {r.get('violation_gaps', '?')}  "
              f"val_acc {r.get('validator_accepted_infeasible', '?')}  "
              f"proj {r['projection_failures']}  trunc {r['truncations']}"
              f"  -> {'QUALIFIES' if r['qualifies'] else 'no' if r.get('measured', True) else 'NOT MEASURED (api errors)'}")
    P(f"\nwinner (first qualifier in selection order): "
      f"{winner or 'NONE'}   screening cost ~${spent:.4f}")

    with open(os.path.join(outdir, "screen_log.txt"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")
    with open(os.path.join(outdir, "summary.json"), "w",
              encoding="utf-8") as f:
        json.dump({"stamp": stamp, "prompt_version": a.prompt_version,
                   "order": order, "run_all": a.run_all,
                   "same_pins": a.same_pins, "winner": winner,
                   "spent_est": spent, "prior": prior, "tried": tried},
                  f, indent=2)
    print(f"\nwrote {os.path.relpath(outdir, ROOT)}")


if __name__ == "__main__":
    main()
