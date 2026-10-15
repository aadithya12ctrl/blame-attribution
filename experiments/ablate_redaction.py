"""
Reason-redaction ablation on judged natural runs. NO new agent calls.

Question: does the judge's agreement with the evaluator depend on the
validator's stated reasons? In the natural condition the validator usually
REJECTs with a reason that names the problem, which may let the judge read
the answer off the trace.

For every judged run of a natural experiment whose agent text was stored,
the run is rebuilt from that text and checked for fidelity: its re-rendered
trace must equal the stored trace byte for byte, or the run is skipped. The
validator's output is then replaced by a decision-only block
    VERDICT / decision=<ACCEPT|REJECT> / END
and the run is re-judged under all four conditions with the same judge
model, provider and settings. Evaluator verdicts do not depend on reasons
(the contract checks the decision only), so the stored evaluator verdicts
are the reference. The unredacted arm is the stored judgments from the
original run. Runs without stored agent text are skipped and listed.

  OPENROUTER_API_KEY=... python3 experiments/ablate_redaction.py \
      --run-dir results/judge_20260922-200108
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr import make_task  # noqa: E402
from faultattr.agents import AGENTS, Invocation, Run  # noqa: E402
from faultattr.judge import (CONDITIONS, JUDGE_MAX_TOKENS,  # noqa: E402
                             forced, judge, make_judge_llm, render_trace)
from faultattr.llm import now_iso  # noqa: E402
from faultattr.projection import (project_observer,  # noqa: E402
                                  project_analyzer, project_planner,
                                  project_validator, project_executor,
                                  ProjectionError)
from exp_judge import (read_label_sheet, judge_status,  # noqa: E402
                       INFRA_STATUSES, fmt_rate)

PROJECT = {"observer": project_observer, "analyzer": project_analyzer,
           "planner": project_planner, "validator": project_validator,
           "executor": project_executor}
COST_PER_CALL = 0.0015       # observed ~$0.0013/call, rounded up
NOT_INVOKED = "(NOT INVOKED: "


def rebuild(row, prompt_version):
    """A Run from a label-sheet row's stored agent text."""
    task = make_task(tau=float(row["tau"]), delta=0, seed=int(row["seed"]))
    run = Run(task=task, prompt_version=prompt_version)
    for ag in AGENTS:
        inp = row[f"{ag}_input"]
        if inp.startswith(NOT_INVOKED):
            run.halted = inp[len(NOT_INVOKED):-1]
            continue
        inv = Invocation(agent=ag, prompt_in=inp, raw_out=row[f"{ag}_output"],
                         ok=True)
        try:
            args = (task,) if ag == "observer" else ()
            inv.meta["projected"] = PROJECT[ag](inv.raw_out, *args)
        except ProjectionError:
            inv.meta["projected"] = None
        run.invocations.append(inv)
    return run


def redact_validator(run):
    """Same run, validator output reduced to its decision."""
    red = Run(task=run.task, prompt_version=run.prompt_version,
              halted=run.halted)
    for inv in run.invocations:
        if inv.agent == "validator":
            dec = (inv.meta.get("projected") or {}).get("decision", "?")
            inv = Invocation(agent=inv.agent, prompt_in=inv.prompt_in,
                             raw_out=f"VERDICT\ndecision={dec}\nEND",
                             ok=True, meta=dict(inv.meta))
        red.invocations.append(inv)
    return red


def key_usage():
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return float(json.load(r)["data"]["usage"])


def agree(jp, ev, jcls, ecls, status, cond):
    if status in INFRA_STATUSES:
        return "", "", ""
    ok = status == "ok"
    exact = ok and jp == ev
    overlap = ok and (bool(jp & ev) or (not jp and not ev))
    cls = "n/a" if forced(cond) else (ok and jcls == ecls)
    return exact, overlap, cls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--cost-cap", type=float, default=0.25)
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    runs_path = glob.glob(os.path.join(a.run_dir, "natural_runs_*.jsonl"))[0]
    sheet_path = glob.glob(os.path.join(a.run_dir,
                                        "natural_label_sheet_*.csv"))[0]
    store = {r["run_id"]: r for r in
             (json.loads(ln) for ln in open(runs_path, encoding="utf-8"))}
    sheet = {r["run_id"]: r for r in read_label_sheet(sheet_path)}
    judged = [rid for rid, r in store.items() if r.get("judges")]

    items, skipped = [], []
    for rid in judged:
        rec = store[rid]
        row = sheet.get(rid)
        if row is None and "trace" not in rec:
            skipped.append((rid, "no stored agent text (not in label sheet)"))
            continue
        if row is None:
            skipped.append((rid, "trace stored but not per-agent text; "
                                 "rebuild unsupported"))
            continue
        run = rebuild(row, rec["prompt_version"])
        if render_trace(run, norms=True) != row["trace"]:
            skipped.append((rid, "rebuild does not reproduce stored trace"))
            continue
        items.append((rid, rec, redact_validator(run)))

    n_calls = len(items) * len(CONDITIONS)
    projected = n_calls * COST_PER_CALL
    print(f"judged runs: {len(judged)}  rebuilt: {len(items)}  skipped: "
          f"{len(skipped)}  -> {n_calls} judge calls, projected "
          f"~${projected:.3f} (cap ${a.cost_cap})")
    if projected > a.cost_cap:
        raise SystemExit("projected cost exceeds the cap; not running")

    jllm = make_judge_llm()
    jm = jllm.describe()
    date = now_iso()
    mock = os.environ.get("FA_MOCK") == "1"
    usage0 = None if mock else key_usage()
    calls = [(i, c) for i in range(len(items)) for c in CONDITIONS]
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = dict(zip(calls, ex.map(
            lambda ic: judge(items[ic[0]][2], ic[1], jllm), calls)))

    rows = []
    for i, (rid, rec, red) in enumerate(items):
        ev = set(rec["evaluator"]["phi"])
        ecls = rec["evaluator"]["class"]
        for c in CONDITIONS:
            u = rec["judges"][c]
            ue, uo, uc = agree(set(u["agents"] or []), ev, u["class"], ecls,
                               u["status"], c)
            r = res[(i, c)]
            s = judge_status(r)
            re_, ro, rc = agree(set(r.agents or []), ev, r.cls, ecls, s, c)
            rows.append({
                "run_id": rid, "tau": rec["tau"], "seed": rec["seed"],
                "condition": c, "evaluator_phi": "|".join(sorted(ev)) or "{}",
                "unredacted_pred": "|".join(sorted(u["agents"] or [])) or "{}",
                "unredacted_status": u["status"], "unredacted_exact": ue,
                "unredacted_overlap": uo, "unredacted_class": uc,
                "redacted_pred": ("|".join(sorted(r.agents or [])) or "{}")
                if s == "ok" else s.upper(),
                "redacted_status": s, "redacted_exact": re_,
                "redacted_overlap": ro, "redacted_class": rc,
                "redacted_reason": r.api_error or r.parse_error or r.reason,
                "judge_model": jm["model"], "judge_provider": jm["provider"],
                "judge_max_tokens": JUDGE_MAX_TOKENS, "date": date,
                "redacted_finish_reason": r.finish_reason,
                "redacted_completion_tokens": r.completion_tokens,
                "agent_model": rec["agent_model"],
                "agent_provider": rec["agent_provider"],
                "prompt_version": rec["prompt_version"]})

    L = []
    P = L.append
    P(f"REASON-REDACTION ABLATION  date {date}")
    P(f"source run: {a.run_dir}   agents: {items[0][1]['agent_model'] if items else '?'} "
      f"@ {items[0][1]['agent_provider'] if items else '?'} (no new agent calls)")
    P(f"judge: {jm['model']} @ {jm['provider']}  temperature 0, max_tokens "
      f"{JUDGE_MAX_TOKENS}  (same settings as the source run)")
    P(f"judged runs {len(judged)}; ablated {len(items)}; skipped "
      f"{len(skipped)}")
    for rid, why in skipped:
        P(f"  skipped {rid}: {why}")
    P("")
    P("AGREEMENT WITH THE EVALUATOR on the ablated runs  (unredacted -> "
      "redacted)")
    P(f"  {'':<8}{'exact set':>24}{'overlap':>24}{'class':>24}")
    for c in CONDITIONS:
        rs = [r for r in rows if r["condition"] == c]
        cell = lambda k: (f"{fmt_rate([r['unredacted_' + k] for r in rs])}"  # noqa: E731
                          f" -> {fmt_rate([r['redacted_' + k] for r in rs])}")
        P(f"  {c:<8}{cell('exact'):>24}{cell('overlap'):>24}"
          f"{cell('class'):>24}")
    P("")
    P("REDACTED JUDGE OUTCOMES (infrastructure excluded from rates)")
    for c in CONDITIONS:
        rs = [r for r in rows if r["condition"] == c]
        n = len(rs)
        cnt = {k: sum(1 for r in rs if r["redacted_status"] == k)
               for k in ("api_error", "truncated", "parse_fail")}
        toks = [r["redacted_completion_tokens"] for r in rs
                if r["redacted_status"] != "api_error"]
        P(f"  {c:<8} calls {n}  api_err {cnt['api_error']}  truncated "
          f"{cnt['truncated']}  parse_fail {cnt['parse_fail']}  out_tokens "
          f"mean {sum(toks) / len(toks) if toks else 0:.0f}")
    P("")
    P("CHANGED ANSWERS (unredacted -> redacted, vs evaluator)")
    for r in rows:
        if r["unredacted_pred"] != r["redacted_pred"]:
            P(f"  {r['run_id']} {r['condition']:<7} {r['unredacted_pred']} -> "
              f"{r['redacted_pred']}   evaluator {r['evaluator_phi']}")
    if usage0 is not None:
        P(f"\nCOST: ${key_usage() - usage0:.4f} (key usage delta; may lag)")
    P("\nCaveat: the unredacted arm is the stored judgments, not a fresh "
      "re-judge;\ntemperature-0 replies are not guaranteed identical across "
      "calls, so\nsmall differences can be judge noise rather than the "
      "redaction.")

    text = "\n".join(L)
    print(text)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(a.run_dir, f"ablation_redaction_{stamp}"
                       + ("_MOCK" if mock else ""))
    os.makedirs(out, exist_ok=False)
    with open(os.path.join(out, "ablation_report.txt"), "w",
              encoding="utf-8") as f:
        f.write(text + "\n")
    if rows:
        with open(os.path.join(out, "ablation_rows.csv"), "w", newline="",
                  encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    with open(os.path.join(out, "ablation_raw.jsonl"), "w",
              encoding="utf-8") as f:
        for (i, c), r in res.items():
            f.write(json.dumps({"run_id": items[i][0], "condition": c,
                                "judge_model": jm["model"],
                                "judge_provider": jm["provider"],
                                "date": date,
                                "finish_reason": r.finish_reason,
                                "status": judge_status(r), "raw": r.raw})
                    + "\n")
    print(f"\nwrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
