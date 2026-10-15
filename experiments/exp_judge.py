"""
Experiment 4 -- LLM-as-judge baseline against the contract evaluator.

Five methods: the contract evaluator and four judge conditions
(forced/permissive x no-norms/norms, see faultattr.judge). Two conditions:

CONTROLLED  Traces come from the deterministic mock agents, which are correct
            by construction, plus the A-E injectors. With no background
            faults, the injection record is exact ground truth:
              A {planner}  B {observer}  C {planner, validator, executor}
              D {} MISSING_RULE           E {} UNFIXABLE_BY_RULES
            The judge sees the same trace format as for real agents. The
            report is the main table plus the error-pattern breakdown: WHERE
            the judge fails, by case.

NATURAL     Real agents (default deepseek/deepseek-chat @ streamlake, prompt
            v2), no injection, 30 runs over tau in {0.2, 0.4}. There is no
            ground truth, so the report is evaluator-vs-judge agreement per
            condition. 20 random runs go to natural_label_sheet.csv for HAND
            labelling (never pre-filled). Once labelled:
              python3 experiments/exp_judge.py --score-labels <sheet.csv>
            scores every method against the human labels.

Rule (README): infrastructure failures -- API errors, 429s, truncation -- are
never scored as model behaviour. Such runs are excluded and logged.

  FA_MOCK=1 python3 experiments/exp_judge.py              # plumbing only
  OPENROUTER_API_KEY=... python3 experiments/exp_judge.py --condition controlled
  OPENROUTER_API_KEY=... python3 experiments/exp_judge.py --condition natural
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import random
import statistics as st
import sys
import threading
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr import (LLM, make_task, run_pipeline, attribute,  # noqa: E402
                       requirement_violations, Schedule)
from faultattr.attribute import (AGENT_FAULT, REPAIRABLE,  # noqa: E402
                                 CORPUS_BLOCKED, INEXPRESSIBLE, NO_FAILURE,
                                 UNATTRIBUTABLE)
from faultattr.agents import AGENTS, finish_reasons, served_by  # noqa: E402
from faultattr.judge import (CONDITIONS, JUDGE_MAX_TOKENS,  # noqa: E402
                             forced, judge, make_judge_llm, render_trace,
                             rules_block)
from faultattr.llm import now_iso  # noqa: E402
from exp_cases import SCENARIOS, build_corpus  # noqa: E402

METHODS = ["evaluator"] + CONDITIONS
TRUTH = {"A": {"planner"}, "B": {"observer"},
         "C": {"planner", "validator", "executor"}, "D": set(), "E": set()}
TRUTH_CLASS = {"A": "AGENT_FAULT", "B": "AGENT_FAULT", "C": "AGENT_FAULT",
               "D": "MISSING_RULE", "E": "UNFIXABLE_BY_RULES"}
EVAL_CLASS = {AGENT_FAULT: "AGENT_FAULT", REPAIRABLE: "MISSING_RULE",
              CORPUS_BLOCKED: "MISSING_RULE", INEXPRESSIBLE:
              "UNFIXABLE_BY_RULES"}
CLASS_COLS = ["AGENT_FAULT", "MISSING_RULE", "UNFIXABLE_BY_RULES",
              "PARSE_FAIL"]

NATURAL_MODEL = "deepseek/deepseek-chat"
NATURAL_PROVIDER = "streamlake"            # same pin as both screens
NATURAL_PROMPT = "v2"
NATURAL_RUNS_PER_TAU = 15
NATURAL_SEED_BASE = {0.2: 4000, 0.4: 4100}  # disjoint from all other seeds
LABEL_SHEET_N = 20
LABEL_SHEET_SEED = 20260922                 # fixed, recorded in the sheet
YES, NO = {"y", "yes", "1", "true", "x"}, {"n", "no", "0", "false"}
# Judge outcomes that are infrastructure, not judgement (README rule):
# excluded from every rate, reported separately, never scored as wrong.
INFRA_STATUSES = {"api_error", "truncated"}


def has_class(method: str) -> bool:
    return method == "evaluator" or not forced(method)


def key_usage() -> float:
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.load(r)["data"]["usage"])


def _schedule(run) -> Schedule:
    ex = run.by_agent("executor")
    return (ex[0].meta.get("projected") if ex else None) or Schedule()


def infra_reason(run):
    """API error or truncation: never model behaviour (README rule)."""
    for inv in run.invocations:
        if not inv.ok:
            return f"api error at {inv.agent}: {inv.error}"
    for inv in run.invocations:
        if inv.meta.get("finish_reason") == "length":
            return f"truncated at {inv.agent} (finish_reason=length)"
    return None


def controlled_exclusion(run, inject):
    why = infra_reason(run)
    if why:
        return why
    for inv in run.invocations:
        if inv.meta.get("projection_error"):
            return (f"projection failure at {inv.agent}: "
                    f"{inv.meta['projection_error']}")
    for a in inject:
        invs = run.by_agent(a)
        if not invs:                    # e.g. executor after a halt
            return f"injected agent {a} was not invoked ({run.halted})"
        if not invs[0].meta.get("injected_changed"):
            return f"injector was a no-op at {a} (no seeded fault)"
    if not requirement_violations(run.task, _schedule(run)):
        return "R held -- the seeded fault did not produce a failure"
    return None


def judge_status(r):
    return ("api_error" if r.api_error else
            "truncated" if r.truncated else
            "parse_fail" if r.parse_error else "ok")


def pred_str(pred, status):
    return ("API_ERROR" if status == "api_error" else
            "TRUNCATED" if status == "truncated" else
            "PARSE_FAIL" if status == "parse_fail" else
            "|".join(sorted(pred)) or "{}")


def run_judges(pool, runs, jllm, label):
    """Judge every run under all four conditions, concurrently."""
    calls = [(i, c) for i in range(len(runs)) for c in CONDITIONS]
    print(f"[{label}] judging {len(runs)} runs x {len(CONDITIONS)} "
          f"conditions = {len(calls)} judge calls ...", flush=True)
    done, lock = [0], threading.Lock()

    def do(ic):
        i, c = ic
        r = judge(runs[i], c, jllm)
        with lock:
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == len(calls):
                print(f"  [{label}] judged {done[0]}/{len(calls)}", flush=True)
        return r

    return dict(zip(calls, pool.map(do, calls)))


def fmt_rate(vals):
    vals = [v for v in vals if v not in ("n/a", "")]
    return (f"{sum(bool(v) for v in vals) / len(vals):.2f} ({len(vals)})"
            if vals else "n/a")


LABEL_INSTRUCTION = ("Mark broke_rule against the written RULES only. "
                     "Record anything else in other_concern.")


def write_label_sheet(path, rows):
    """Label sheet: one instruction line, then the CSV header and rows."""
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([f"INSTRUCTIONS: {LABEL_INSTRUCTION}"])
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def read_label_sheet(path):
    """Rows of a label sheet, skipping any lines before the run_id header."""
    csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))   # traces are large
    with open(path, encoding="utf-8", newline="") as f:
        lines = list(csv.reader(f))
    start = next((i for i, r in enumerate(lines) if r and r[0] == "run_id"),
                 None)
    if start is None:
        raise SystemExit(f"{path}: no header row starting with run_id")
    header = lines[start]
    return [dict(zip(header, r)) for r in lines[start + 1:] if r]


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# =================================================================== CONTROLLED

def score_controlled(scen, method, pred, pcls, status):
    """exact / hit / none_correct / class_correct. API-error rows carry no
    judgement and are scored "" (excluded from every rate)."""
    de = scen in "DE"
    if status in INFRA_STATUSES:
        return "", "", "", ""
    ok = status == "ok"
    truth = TRUTH[scen]
    exact = ok and set(pred) == truth
    hit = "n/a" if de else (ok and bool(set(pred) & truth))
    none_correct = (ok and not pred) if de else "n/a"
    class_correct = ((ok and pcls == TRUTH_CLASS[scen])
                     if de and has_class(method) else "n/a")
    return exact, hit, none_correct, class_correct


def controlled(a, pool, jllm, jm, stamp, outdir, date):
    agents = LLM(mock=True)          # correct by construction, in every mode
    meta = {"condition": "controlled", "agent_model": "mock-deterministic",
            "agent_provider": "none", "judge_model": jm["model"],
            "judge_provider": jm["provider"], "prompt_version": "v1",
            "date": date}
    seeds = list(range(a.base_seed, a.base_seed + a.seeds))
    corpus = build_corpus(agents, range(107, 115), dead_frac=0.0)
    jobs = [(lab[0], tau, dead, lying, inj, s)
            for lab, tau, dead, lying, inj in SCENARIOS
            if lab[0] in a.scenarios for s in seeds]

    def gen(job):
        scen, tau, dead, lying, inj, s = job
        task = make_task(tau=tau, delta=0, seed=s, dead_sensor=dead,
                         lying_sensor=lying)
        return run_pipeline(task, agents, inject=inj, prompt_version="v1")

    runs = list(pool.map(gen, jobs))
    kept, excluded = [], []
    for job, run in zip(jobs, runs):
        why = controlled_exclusion(run, job[4])
        (excluded if why else kept).append((job, run, why))

    verdicts = [attribute(run, corpus=corpus) for _, run, _ in kept]
    jres = run_judges(pool, [run for _, run, _ in kept], jllm, "controlled")

    rows, raw_log = [], []
    for i, ((scen, *_r, seed), run, _) in enumerate(kept):
        v = verdicts[i]
        entries = [("evaluator", sorted(v.phi), EVAL_CLASS.get(v.kind, v.kind),
                    "ok", v.kind + (" -> MISSING_RULE (FLAGGED: corpus-"
                                    "blocked)" if v.kind == CORPUS_BLOCKED
                                    else ""), "", "")]
        for c in CONDITIONS:
            r = jres[(i, c)]
            s = judge_status(r)
            entries.append((c, r.agents, r.cls, s,
                            r.api_error or r.parse_error or r.reason,
                            str(r.finish_reason), str(r.served_by),
                            r.completion_tokens))
            raw_log.append({**meta, "scenario": scen, "seed": seed,
                            "condition": c, "status": s,
                            "finish_reason": r.finish_reason,
                            "served_by": r.served_by,
                            "completion_tokens": r.completion_tokens,
                            "error": r.api_error or r.parse_error,
                            "raw": r.raw})
        for method, pred, pcls, s, why, jfin, srv, *tok in entries:
            exact, hit, nc, cc = score_controlled(scen, method, pred, pcls, s)
            rows.append({
                "scenario": scen, "seed": seed, "method": method,
                "predicted": pred_str(pred, s),
                "truth": "|".join(sorted(TRUTH[scen])) or "{}",
                "exact": exact, "hit": hit, "none_correct": nc,
                "class_correct": cc, "judge_reason": why,
                "predicted_class": pcls or "",
                "truth_class": TRUTH_CLASS[scen], "status": s,
                "evaluator_kind": v.kind if method == "evaluator" else "",
                **meta, "pipeline_finish_reason": finish_reasons(run),
                "judge_finish_reason": jfin, "judge_served_by": srv,
                "judge_completion_tokens": tok[0] if tok else ""})

    L = []
    P = L.append
    P(f"CONTROLLED CONDITION  {stamp}   date {date}")
    P("agents: deterministic mock agents (correct by construction) + A-E "
      "injectors")
    P(f"judge:  {jm['model']} @ {jm['provider']}  (temperature 0, "
      f"max_tokens {JUDGE_MAX_TOKENS})")
    jf = Counter(r["judge_finish_reason"] for r in rows
                 if r["method"] != "evaluator")
    P(f"judge finish_reason: {dict(jf)}")
    P(f"seeds: {seeds[0]}..{seeds[-1]} ({len(seeds)})   Sigma_ok: "
      f"{len(corpus)} clean-only runs")
    if jm["model"].startswith("mock"):
        P("MOCK JUDGE: a deliberate strawman. These numbers test plumbing "
          "and scoring only.")
    P("")
    P("RUNS KEPT / EXCLUDED")
    for scen in "ABCDE":
        k = sum(1 for j, _, _ in kept if j[0] == scen)
        x = sum(1 for j, _, _ in excluded if j[0] == scen)
        P(f"  {scen}: kept {k:>2}   excluded {x:>2}")
    P("EXCLUDED-RUN LOG")
    for (scen, *_r, s), _, why in excluded:
        P(f"  {scen} seed={s}: {why}")
    if not excluded:
        P("  (none)")
    P("")

    def sel(scen, method, scored=True):
        return [r for r in rows if r["scenario"] == scen
                and r["method"] == method
                and (not scored or r["status"] not in INFRA_STATUSES)]

    def line(label, field, scen):
        return f"  {label:<7}" + "".join(
            f"{fmt_rate([r[field] for r in sel(scen, m)]):>12}"
            for m in METHODS)

    header = " " * 9 + "".join(f"{m:>12}" for m in METHODS)
    P("EXACT MATCH  (rate, n = runs with a judgement)")
    P(header)
    for scen in "ABCDE":
        P(line(scen, "exact", scen))
    P("")
    P("HIT (A-C)  /  NONE_CORRECT (D, E)  /  CLASS_CORRECT (D, E)")
    P(header)
    for scen in "ABC":
        P(line(f"{scen} hit", "hit", scen))
    for scen in "DE":
        P(line(f"{scen} none", "none_correct", scen))
        P(line(f"{scen} cls", "class_correct", scen))
    P("")

    P("ERROR PATTERN -- B (truth: observer). Who does each method blame?")
    for m in METHODS:
        cnt = Counter()
        for r in sel("B", m, scored=False):
            if r["status"] != "ok":
                cnt[f"({r['status']})"] += 1
            elif r["predicted"] == "{}":
                cnt["(none)"] += 1
            else:
                cnt.update(r["predicted"].split("|"))
        P(f"  {m:<10} " + (", ".join(f"{k}={v}" for k, v in cnt.most_common())
                            or "(no runs)"))
    P("")
    P("ERROR PATTERN -- C (truth: 3 agents). Mean predicted set size")
    for m in METHODS:
        sizes = [0 if r["predicted"] == "{}" else
                 len(r["predicted"].split("|"))
                 for r in sel("C", m) if r["status"] == "ok"]
        full = sum(1 for r in sel("C", m) if r["exact"] is True)
        P(f"  {m:<10} " + (f"mean={st.mean(sizes):.2f}  exact={full}/"
                            f"{len(sizes)}" if sizes else "(no runs)"))
    P("")
    P("ERROR PATTERN -- D vs E. Class predicted (rows = truth)")
    for m in [x for x in METHODS if has_class(x)]:
        P(f"  {m}")
        P("    " + " " * 22 + "".join(f"{c:>20}" for c in CLASS_COLS))
        for scen in "DE":
            cnt = Counter("PARSE_FAIL" if r["status"] == "parse_fail"
                          else r["predicted_class"] for r in sel(scen, m))
            P(f"    {scen} {TRUTH_CLASS[scen]:<20}"
              + "".join(f"{cnt.get(c, 0):>20}" for c in CLASS_COLS))
    P("  Agents blamed on D/E (truth: none):")
    for m in METHODS:
        cnt = Counter()
        for scen in "DE":
            for r in sel(scen, m):
                if r["status"] == "ok" and r["predicted"] != "{}":
                    cnt.update(r["predicted"].split("|"))
        P(f"    {m:<10} " + (", ".join(f"{k}={v}" for k, v in
                                        cnt.most_common()) or "(none)"))
    P("")
    P("JUDGE OUTCOMES per condition  (truncated and api-error calls are "
      "infrastructure:\n  excluded from every rate above, never scored as "
      "wrong)")
    gate_fail = []
    for c in CONDITIONS:
        rs = [r for r in rows if r["method"] == c]
        n = len(rs)
        ae = sum(1 for r in rs if r["status"] == "api_error")
        tr = sum(1 for r in rs if r["status"] == "truncated")
        pf = sum(1 for r in rs if r["status"] == "parse_fail")
        replied = n - ae                        # calls that returned text
        answered = replied - tr                 # replies that were complete
        toks = [r["judge_completion_tokens"] for r in rs
                if isinstance(r["judge_completion_tokens"], int)
                and r["status"] != "api_error"]
        tr_rate = tr / replied if replied else 0.0
        pf_rate = pf / answered if answered else 0.0
        P(f"  {c:<8} calls {n}  api_err {ae}  truncated {tr}/{replied} "
          f"({tr_rate:.2f})  parse_fail {pf}/{answered} ({pf_rate:.2f})  "
          f"out_tokens mean {st.mean(toks) if toks else 0:.0f} "
          f"max {max(toks) if toks else 0}")
        if tr_rate > 0.05 or pf_rate > 0.05:
            gate_fail.append(f"{c} (trunc {tr_rate:.2f}, parse {pf_rate:.2f})")
    P("  GATE (<= 5% truncation and <= 5% parse failure, every condition): "
      + ("FAILED: " + "; ".join(gate_fail) if gate_fail else "passed"))
    inc = [r for r in rows if r["method"] in ("J-P", "J-P-N")
           and r["status"] == "ok"
           and ((r["predicted_class"] == "AGENT_FAULT")
                != (r["predicted"] != "{}"))]
    P(f"  self-inconsistent permissive answers (class vs agent set): "
      f"{len(inc)}")
    P("")
    P("EVALUATOR vs INJECTION LABELS")
    dis = [r for r in rows if r["method"] == "evaluator"
           and r["exact"] is False]
    for r in dis:
        P(f"  {r['scenario']} seed={r['seed']}: evaluator {r['predicted']} "
          f"({r['evaluator_kind']}) vs label {r['truth']}")
    P("  all agree" if not dis else "")
    P(f"  CORPUS_BLOCKED mapped to MISSING_RULE (flagged): "
      f"{sum(1 for r in rows if r['evaluator_kind'] == CORPUS_BLOCKED)}")
    P("")
    P("CAVEATS")
    P("  1. The evaluator's agreement is with injection labels designed "
      "alongside\n     the contracts, on agents that are correct by "
      "construction. It is a sanity\n     check, NOT attribution accuracy "
      "on undesigned failures.")
    P("  2. The comparison of interest is the judge's error PATTERN by case.")
    P("  3. If J-P-N approaches the evaluator on B, D and E, the contribution "
      "is\n     formalization of norms the judge could already use -- a "
      "smaller claim.")

    text = "\n".join(L)
    print("\n" + text, flush=True)
    with open(os.path.join(outdir, f"controlled_table_{stamp}.txt"), "w",
              encoding="utf-8") as f:
        f.write(text + "\n")
    write_csv(os.path.join(outdir, f"controlled_rows_{stamp}.csv"), rows)
    with open(os.path.join(outdir, f"controlled_raw_{stamp}.jsonl"), "w",
              encoding="utf-8") as f:
        for rec in raw_log:
            f.write(json.dumps(rec) + "\n")
    return rows


# ====================================================================== NATURAL

def natural(a, pool, jllm, jm, stamp, outdir, date):
    agents = LLM(model=a.natural_model, provider=a.natural_provider)
    am = agents.describe()
    meta = {"condition": "natural", "agent_model": am["model"],
            "agent_provider": am["provider"], "judge_model": jm["model"],
            "judge_provider": jm["provider"],
            "prompt_version": NATURAL_PROMPT, "date": date}
    taus = [float(t) for t in a.natural_taus.split(",")]
    jobs = [(t, NATURAL_SEED_BASE.get(t, 4200 + int(t * 100)) + i)
            for t in taus for i in range(a.natural_runs_per_tau)]

    def gen(job):
        t, s = job
        return run_pipeline(make_task(tau=t, delta=0, seed=s), agents,
                            prompt_version=NATURAL_PROMPT)

    runs = list(pool.map(gen, jobs))
    recs = []
    for idx, ((t, s), run) in enumerate(zip(jobs, runs)):
        recs.append({"run_id": f"N{idx:03d}", "tau": t, "seed": s,
                     "run": run, "infra": infra_reason(run)})
    usable = [r for r in recs if not r["infra"]]
    # Sigma_ok from the natural runs themselves: same model, same prompts.
    first = {r["run_id"]: attribute(r["run"]) for r in usable}
    corpus = [r["run"] for r in usable
              if first[r["run_id"]].kind == NO_FAILURE
              and not first[r["run_id"]].phi]
    for r in usable:
        r["verdict"] = attribute(r["run"], corpus=corpus)
        r["R_failed"] = bool(requirement_violations(r["run"].task,
                                                    _schedule(r["run"])))
    # Judge only runs where R failed and the evaluator can attribute: the
    # judge's question presupposes a failure.
    judged = [r for r in usable if r["R_failed"]
              and r["verdict"].kind != UNATTRIBUTABLE]
    jres = run_judges(pool, [r["run"] for r in judged], jllm, "natural")
    for i, r in enumerate(judged):
        r["judges"] = {c: jres[(i, c)] for c in CONDITIONS}

    # ---- per-run records (predictions kept OUT of the label sheet)
    rows, store = [], []
    for r in recs:
        base = {"run_id": r["run_id"], "tau": r["tau"], "seed": r["seed"],
                **meta, "pipeline_finish_reason": finish_reasons(r["run"]),
                "served_by": served_by(r["run"]),
                "pipeline_halted": r["run"].halted or "",
                "excluded_infra": r["infra"] or ""}
        if r["infra"]:
            rows.append({**base, "method": "", "status": "excluded_infra"})
            store.append({**base})
            continue
        v = r["verdict"]
        ev_set, ev_cls = set(v.phi), EVAL_CLASS.get(v.kind, "")
        rec = {**base, "R_failed": r["R_failed"],
               # full trace for EVERY run, so any disagreement can be audited
               # later -- not only the runs sampled into the label sheet
               "trace": render_trace(r["run"], norms=True),
               "R_violations": requirement_violations(
                   r["run"].task, _schedule(r["run"])),
               "evaluator": {"kind": v.kind, "phi": sorted(v.phi),
                             "class": ev_cls}, "judges": {}}
        rows.append({**base, "method": "evaluator", "status": "ok",
                     "R_failed": r["R_failed"], "evaluator_kind": v.kind,
                     "predicted": "|".join(sorted(v.phi)) or "{}",
                     "predicted_class": ev_cls, "agree_exact": "n/a",
                     "agree_overlap": "n/a", "class_agree": "n/a",
                     "reason": v.kind, "judge_finish_reason": ""})
        for c in CONDITIONS:
            if "judges" not in r:
                why = ("n/a: no failure" if not r["R_failed"]
                       else "n/a: unattributable")
                rows.append({**base, "method": c, "status": why,
                             "R_failed": r["R_failed"],
                             "evaluator_kind": v.kind, "predicted": "",
                             "predicted_class": "", "agree_exact": "n/a",
                             "agree_overlap": "n/a", "class_agree": "n/a",
                             "reason": "", "judge_finish_reason": ""})
                continue
            j = r["judges"][c]
            s = judge_status(j)
            ok = s == "ok"
            jp = set(j.agents or [])
            rows.append({
                **base, "method": c, "status": s, "R_failed": True,
                "evaluator_kind": v.kind, "predicted": pred_str(j.agents, s),
                "predicted_class": j.cls or "",
                "agree_exact": "" if s in INFRA_STATUSES else (ok and jp == ev_set),
                "agree_overlap": "" if s in INFRA_STATUSES else (
                    ok and (bool(jp & ev_set) or (not jp and not ev_set))),
                "class_agree": ("n/a" if forced(c) else
                                "" if s in INFRA_STATUSES else
                                (ok and j.cls == ev_cls)),
                "reason": j.api_error or j.parse_error or j.reason,
                "judge_finish_reason": str(j.finish_reason)})
            rec["judges"][c] = {"agents": j.agents, "class": j.cls,
                                "status": s, "reason": j.reason,
                                "error": j.api_error or j.parse_error,
                                "finish_reason": j.finish_reason,
                                "raw": j.raw}
        store.append(rec)

    # ---- label sheet: 20 random usable runs, NOT pre-filled
    rng = random.Random(LABEL_SHEET_SEED)
    pick = sorted(rng.sample(usable, min(LABEL_SHEET_N, len(usable))),
                  key=lambda r: r["run_id"])
    sheet = []
    for r in pick:
        run = r["run"]
        row = {"run_id": r["run_id"], "tau": r["tau"], "seed": r["seed"],
               "agent_model": am["model"], "agent_provider": am["provider"],
               "prompt_version": NATURAL_PROMPT, "date": date,
               "selection_seed": LABEL_SHEET_SEED,
               "final_requirement_violations": "; ".join(
                   requirement_violations(run.task, _schedule(run))) or
               "none (R held)",
               "trace": render_trace(run, norms=True)}
        for ag in AGENTS:               # all five, even if one was not run
            invs = run.by_agent(ag)
            row[f"{ag}_rules"] = rules_block(ag, NATURAL_PROMPT)
            row[f"{ag}_input"] = (invs[0].prompt_in if invs else
                                  f"(NOT INVOKED: {run.halted})")
            row[f"{ag}_output"] = invs[0].raw_out if invs else ""
        for ag in AGENTS:
            row[f"{ag}_broke_rule"] = ""        # human: Y / N
        row["other_concern"] = ""               # human: free text
        row["labeler"] = ""
        row["notes"] = ""
        sheet.append(row)
    sheet_path = os.path.join(outdir, f"natural_label_sheet_{stamp}.csv")
    write_label_sheet(sheet_path, sheet)
    write_csv(os.path.join(outdir, f"natural_rows_{stamp}.csv"), rows)
    with open(os.path.join(outdir, f"natural_runs_{stamp}.jsonl"), "w",
              encoding="utf-8") as f:
        for rec in store:
            f.write(json.dumps(rec) + "\n")

    # ---- report
    L = []
    P = L.append
    P(f"NATURAL CONDITION  {stamp}   date {date}")
    P(f"agents: {am['model']} @ {am['provider']}   prompt {NATURAL_PROMPT}"
      f"   no injection")
    P(f"judge:  {jm['model']} @ {jm['provider']}")
    P(f"runs: {len(recs)} over tau {taus} ({a.natural_runs_per_tau} each)")
    P(f"  excluded (infrastructure; not scored): "
      f"{sum(1 for r in recs if r['infra'])}")
    for r in recs:
        if r["infra"]:
            P(f"    {r['run_id']} tau={r['tau']} seed={r['seed']}: "
              f"{r['infra']}")
    P(f"  R held (no failure; judge n/a):         "
      f"{sum(1 for r in usable if not r['R_failed'])}")
    P(f"    of which the evaluator found a contract violation: "
      f"{sum(1 for r in usable if not r['R_failed'] and r['verdict'].phi)}"
      f"   (own number: errors that did not become failures; the judge is "
      f"not asked about these, so no comparison)")
    P(f"  unattributable (projection failure):    "
      f"{sum(1 for r in usable if r['verdict'].kind == UNATTRIBUTABLE)}")
    P(f"  judged (R failed, attributable):        {len(judged)}")
    P(f"  Sigma_ok (from these runs):             {len(corpus)}")
    if jm["model"].startswith("mock"):
        P("MOCK: agents and judge are scripted; plumbing only.")
    P("")
    P("EVALUATOR on judged runs")
    P("  kinds:   " + str(dict(Counter(r["verdict"].kind for r in judged))))
    P("  blamed:  " + str(dict(Counter(a for r in judged
                                       for a in r["verdict"].phi)))
      + f"   empty fault set: "
        f"{sum(1 for r in judged if not r['verdict'].phi)}")
    P("")
    P("EVALUATOR vs JUDGE AGREEMENT (no ground truth; agreement is not "
      "accuracy)")
    P(f"  {'':<8}{'exact set':>14}{'overlap':>14}{'class':>14}"
      f"{'parse fail':>12}{'truncated':>11}{'api err':>9}")
    for c in CONDITIONS:
        rs = [x for x in rows if x["method"] == c
              and x["status"] in ({"ok", "parse_fail"} | INFRA_STATUSES)]
        P(f"  {c:<8}{fmt_rate([x['agree_exact'] for x in rs]):>14}"
          f"{fmt_rate([x['agree_overlap'] for x in rs]):>14}"
          f"{fmt_rate([x['class_agree'] for x in rs]):>14}"
          f"{sum(1 for x in rs if x['status'] == 'parse_fail'):>12}"
          f"{sum(1 for x in rs if x['status'] == 'truncated'):>11}"
          f"{sum(1 for x in rs if x['status'] == 'api_error'):>9}")
    P("")
    P("  Who each judge condition blames (judged runs):")
    for c in CONDITIONS:
        cnt = Counter()
        for x in rows:
            if x["method"] == c and x["status"] == "ok":
                cnt.update(["(none)"] if x["predicted"] == "{}"
                           else x["predicted"].split("|"))
        P(f"    {c:<8} " + (", ".join(f"{k}={v}" for k, v in
                                       cnt.most_common()) or "(none)"))
    P("")
    P(f"HAND-LABEL SHEET: {os.path.relpath(sheet_path, ROOT)}")
    P(f"  {len(sheet)} runs, random.Random({LABEL_SHEET_SEED}) over the "
      f"{len(usable)} non-excluded runs. Not pre-filled.")
    P(f"  Fill <agent>_broke_rule with Y/N for all five agents, then:")
    P(f"    python3 experiments/exp_judge.py --score-labels "
      f"{os.path.relpath(sheet_path, ROOT)}")
    P("  ACCURACY vs hand labels: pending (no labels yet).")

    text = "\n".join(L)
    print("\n" + text, flush=True)
    with open(os.path.join(outdir, f"natural_report_{stamp}.txt"), "w",
              encoding="utf-8") as f:
        f.write(text + "\n")
    return rows


# ================================================================= LABEL SCORING

def read_marks(path):
    """{run_id: set of agents marked as rule-breaking} from one filled sheet,
    plus the run_ids that are unusable and why."""
    human, incomplete, invalid = {}, [], []
    for row in read_label_sheet(path):
        marks = {ag: row.get(f"{ag}_broke_rule", "").strip().lower()
                 for ag in AGENTS}
        if any(m == "" for m in marks.values()):
            incomplete.append(row["run_id"])
            continue
        bad = [f"{ag}={m!r}" for ag, m in marks.items() if m not in YES | NO]
        if bad:
            invalid.append(f"{row['run_id']}: {bad}")
            continue
        human[row["run_id"]] = {ag for ag, m in marks.items() if m in YES}
    return human, incomplete, invalid


def inter_labeller(paths):
    """
    Agreement between two or more filled sheets on the runs they share.
    Per-agent agreement and Cohen's kappa over the 5 agent x N run
    judgements. A disagreement about whether a rule was broken is exactly the
    contested-boundary case (case E), measured rather than argued.
    """
    sheets = [(p, read_marks(p)[0]) for p in paths]
    print("\nINTER-LABELLER AGREEMENT")
    for i in range(len(sheets)):
        for j in range(i + 1, len(sheets)):
            (pa, a), (pb, b) = sheets[i], sheets[j]
            shared = sorted(set(a) & set(b))
            if not shared:
                print(f"  {os.path.basename(pa)} vs {os.path.basename(pb)}: "
                      f"no labelled runs in common")
                continue
            cells = [(r, ag) for r in shared for ag in AGENTS]
            ya = [ag in a[r] for r, ag in cells]
            yb = [ag in b[r] for r, ag in cells]
            n = len(cells)
            obs = sum(x == y for x, y in zip(ya, yb)) / n
            pa_y, pb_y = sum(ya) / n, sum(yb) / n
            exp = pa_y * pb_y + (1 - pa_y) * (1 - pb_y)
            kappa = (obs - exp) / (1 - exp) if exp < 1 else float("nan")
            same_set = sum(1 for r in shared if a[r] == b[r])
            print(f"  {os.path.basename(pa)} vs {os.path.basename(pb)}: "
                  f"{len(shared)} shared runs, {n} agent judgements")
            print(f"    per-agent agreement {obs:.3f}   Cohen's kappa "
                  f"{kappa:.3f}   identical fault sets {same_set}/"
                  f"{len(shared)}")
            dis = [(r, sorted(a[r] ^ b[r])) for r in shared if a[r] != b[r]]
            if dis:
                print("    disagreements (case E candidates: two humans "
                      "differ on whether a rule was broken)")
                for r, agents in dis:
                    print(f"      {r}: {sorted(a[r]) or '{}'} vs "
                          f"{sorted(b[r]) or '{}'}  (differ on {agents})")


def score_labels(sheet_path):
    """Score every method against a hand-filled label sheet. Accepts several
    comma-separated sheets; with more than one, also reports agreement."""
    paths = [p.strip() for p in sheet_path.split(",") if p.strip()]
    if len(paths) > 1:
        inter_labeller(paths)
        print("\nScoring against the FIRST sheet given: "
              f"{os.path.basename(paths[0])}")
    sheet_path = paths[0]
    d = os.path.dirname(os.path.abspath(sheet_path))
    stores = glob.glob(os.path.join(d, "natural_runs_*.jsonl"))
    if len(stores) != 1:
        raise SystemExit(f"expected one natural_runs_*.jsonl in {d}, "
                         f"found {stores}")
    runs = {r["run_id"]: r for r in
            (json.loads(ln) for ln in open(stores[0], encoding="utf-8"))}
    sheet = read_label_sheet(sheet_path)
    human, incomplete, invalid = {}, [], []
    for row in sheet:
        marks = {ag: row.get(f"{ag}_broke_rule", "").strip().lower()
                 for ag in AGENTS}
        if any(m == "" for m in marks.values()):
            incomplete.append(row["run_id"])
            continue
        bad = [f"{ag}={m!r}" for ag, m in marks.items() if m not in YES | NO]
        if bad:
            invalid.append(f"{row['run_id']}: {bad}")
            continue
        human[row["run_id"]] = {ag for ag, m in marks.items() if m in YES}

    print(f"label sheet: {len(sheet)} rows; labelled {len(human)}; "
          f"incomplete {len(incomplete)}; invalid {len(invalid)}")
    for x in invalid:
        print(f"  invalid: {x}")
    print("\nACCURACY vs HAND LABELS  (exact set of rule-breaking agents)")
    print(f"  {'method':<10}{'exact':>14}{'overlap':>14}   n")
    for m in METHODS:
        ex, ov = [], []
        for rid, h in human.items():
            r = runs.get(rid, {})
            if m == "evaluator":
                if "evaluator" not in r or \
                        r["evaluator"]["kind"] == UNATTRIBUTABLE:
                    continue
                p = set(r["evaluator"]["phi"])
            else:
                j = r.get("judges", {}).get(m)
                if not j or j["status"] in INFRA_STATUSES:
                    continue                  # not judged / infra: unscored
                p = set(j["agents"] or []) if j["status"] == "ok" else None
            ex.append(p is not None and p == h)
            ov.append(p is not None and (bool(p & h) or (not p and not h)))
        print(f"  {m:<10}{fmt_rate(ex):>14}{fmt_rate(ov):>14}   {len(ex)}")
    print("\n  Judges are scored only on labelled runs they judged (R failed);"
          "\n  the evaluator on every labelled attributable run.")


# ========================================================================= MAIN

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--condition", default="both",
                    choices=["controlled", "natural", "both"])
    ap.add_argument("--seeds", type=int, default=10,
                    help="controlled: seeds per scenario")
    ap.add_argument("--base-seed", type=int, default=7)
    ap.add_argument("--scenarios", default="ABCDE",
                    help="controlled: which scenarios to run, e.g. A")
    ap.add_argument("--natural-taus", default="0.2,0.4")
    ap.add_argument("--natural-runs-per-tau", type=int,
                    default=NATURAL_RUNS_PER_TAU)
    ap.add_argument("--natural-model", default=NATURAL_MODEL)
    ap.add_argument("--natural-provider", default=NATURAL_PROVIDER)
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--score-labels", default=None,
                    help="score a hand-filled natural label sheet and exit")
    a = ap.parse_args()

    if a.score_labels:
        score_labels(a.score_labels)
        return

    mock = os.environ.get("FA_MOCK") == "1"
    base = datetime.now().strftime("%Y%m%d-%H%M%S")
    stamp, n = base, 1
    while True:                                  # unique; never overwrite
        outdir = os.path.join(ROOT, "results",
                              f"judge_{stamp}" + ("_MOCK" if mock else ""))
        try:
            os.makedirs(outdir, exist_ok=False)
            break
        except FileExistsError:
            n += 1
            stamp = f"{base}-{n}"
    print("judge:")
    jllm = make_judge_llm()
    jm = ({"model": "mock-strawman", "provider": "mock"} if mock
          else jllm.describe())
    date = now_iso()
    usage0 = None if mock else key_usage()
    pool = ThreadPoolExecutor(max_workers=a.workers)
    if a.condition in ("controlled", "both"):
        controlled(a, pool, jllm, jm, stamp, outdir, date)
    if a.condition in ("natural", "both"):
        natural(a, pool, jllm, jm, stamp, outdir, date)
    pool.shutdown()
    if usage0 is not None:
        cost = key_usage() - usage0
        print(f"\nCOST this run: ${cost:.4f} (key usage delta; may lag)")
    print(f"\nwrote {os.path.relpath(outdir, ROOT)}")


if __name__ == "__main__":
    main()
