"""
SUPPLEMENTARY automated blind reader on the 10 abstention cases.

This is a PROXY for the human blind audit, never a substitute. An LLM
auditing another LLM's abstention is weaker evidence and partly circular:
the reader shares training data, failure modes and reading habits with the
judge whose abstention it is checking, and both are reading the same trace
through the same frozen rule set. Treat a high "abstention supported" rate
here as consistent with the abstention being principled, not as evidence
that it was.

Design, to keep it comparable to the human sheet:
  * the reader sees EXACTLY the text abstention_blind.csv shows a human --
    the task question, the step-numbered trace, and the frozen v1 RULES --
    with no benchmark label, no ground-truth answer and no method answer;
  * the same two separate questions (violated / explains) and the same
    classification rule as --score-blind;
  * a model from a different family than the judge (default
    qwen/qwen3-235b-a22b-2507, judge was openai/gpt-oss-120b);
  * temperature 0, 3 independent samples per case.

Writes abstention_blind_LLM.csv and _LLM_raw.jsonl. It never writes to the
human sheets.

  OPENROUTER_API_KEY=... python3 experiments/blind_reader_llm.py
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr.llm import LLM, now_iso, verify_provider  # noqa: E402
from faultattr.whowhen import verify_norms  # noqa: E402
from exp_whowhen import _read_sheet, classify, YES, NO, UNSURE  # noqa: E402

SHEET = os.path.join(ROOT, "results", "whowhen_abl_20260922-224740",
                     "abstention_blind.csv")
READER_MODEL = "qwen/qwen3-235b-a22b-2507"     # NOT the judge
READER_PROVIDER = "alibaba"
JUDGE_MODEL = "openai/gpt-oss-120b"            # for the record only
SAMPLES = 3
MAX_TOKENS = 2_000
CANON = {"orchestrator": "Orchestrator", "websurfer": "WebSurfer",
         "filesurfer": "FileSurfer", "coder": "Coder",
         "assistant": "Coder", "computerterminal": "ComputerTerminal"}

SYSTEM = ("You are auditing one run of a multi-agent system against the "
          "written rules its agents were given. Answer with a single JSON "
          "object and nothing else.")

ASK = """Two SEPARATE questions about this run, which produced a wrong final answer.

1. violated: was any written RULE above clearly violated? If yes, say which agent and which printed [step N].
2. explains: does THAT violation account for the wrong final answer? A rule broken that does not account for the failure is an error that did not become a fault for this failure, and should be marked explains = N, not Y.

Do not guess. If no rule was clearly violated, say so.

Answer with JSON only:
{"violated": "Y" or "N", "which_agent": "<Orchestrator|WebSurfer|FileSurfer|Coder|ComputerTerminal or empty>", "which_step": <printed step number or null>, "explains": "Y" or "N" or "unsure" (empty if violated is N), "justification": "<one or two sentences>"}"""


def build(row):
    return (f"TASK GIVEN TO THE SYSTEM: {row['question']}\n\n"
            f"TRACE (each entry is prefixed with its printed step number):\n\n"
            f"{row['history']}\n\n"
            f"WRITTEN RULES EACH AGENT WAS GIVEN:\n\n{row['rules']}\n\n"
            + ASK)


def parse(text, n_steps_hint=None):
    t = re.sub(r"^```[A-Za-z]*\s*\n?|\n?\s*```\s*$", "", text.strip()).strip()
    try:
        o = json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("no JSON object")
        o = json.loads(t[i:j + 1])
    v = str(o.get("violated", "")).strip().lower()
    if v not in YES | NO:
        raise ValueError(f"violated={v!r}")
    viol = v in YES
    ex = str(o.get("explains", "")).strip().lower()
    if viol:
        if ex in YES:
            ex = "y"
        elif ex in NO:
            ex = "n"
        elif ex in UNSURE:
            ex = "unsure"
        else:
            raise ValueError(f"explains={ex!r}")
    else:
        ex = ""
    ag = str(o.get("which_agent", "") or "").strip()
    ag = CANON.get(re.sub(r"\s*\(.*\)$", "", ag).lower().replace(" ", ""), ag)
    st = o.get("which_step")
    st = "" if st in (None, "") else str(re.sub(r"\D", "", str(st)) or "")
    return {"violated": viol, "explains": ex, "agent": ag if viol else "",
            "step": st if viol else "",
            "justification": str(o.get("justification", ""))[:600],
            "class": classify(viol, ex)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=SAMPLES)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--cost-cap", type=float, default=1.0)
    a = ap.parse_args()

    verify_norms("v1")                      # the rules in the sheet are v1
    rows = _read_sheet(SHEET)
    print(f"{len(rows)} abstention cases from {os.path.basename(SHEET)}: "
          f"{[r['case'] for r in rows]}")
    for r in rows:                          # the sheet must stay blind
        assert not any(k in r for k in ("label_agent", "method_verdict",
                                        "groundtruth")), "sheet not blind"

    llm = LLM(model=READER_MODEL, provider=READER_PROVIDER, temperature=0.0,
              max_tokens=MAX_TOKENS)
    ep = verify_provider(llm.model, llm.provider)
    p_in, p_out = (float(ep["pricing"]["prompt"]),
                   float(ep["pricing"]["completion"]))
    prompts = {r["case"]: build(r) for r in rows}
    est_in = sum(len(SYSTEM) + len(p) for p in prompts.values()) / 3.2
    proj = a.samples * (est_in * p_in + len(rows) * 500 * p_out)
    print(f"reader: {READER_MODEL} @ {READER_PROVIDER} (judge was "
          f"{JUDGE_MODEL}); {a.samples} samples x {len(rows)} cases; "
          f"projected ~${proj:.3f} (cap ${a.cost_cap})")
    if proj > a.cost_cap:
        raise SystemExit("projected cost exceeds the cap; not running")

    jobs = [(r["case"], s) for r in rows for s in range(a.samples)]

    def one(job):
        case, s = job
        rep = llm.chat(SYSTEM, prompts[case], temperature=0.0)
        rec = {"case": case, "sample": s, "status": None, "error": None,
               "finish_reason": rep.finish_reason, "served_by": rep.served_by,
               "prompt_tokens": rep.prompt_tokens,
               "completion_tokens": rep.completion_tokens, "raw": rep.text}
        if not rep.ok:
            rec["status"] = "api_error"; rec["error"] = rep.error
        elif rep.finish_reason == "length":
            rec["status"] = "truncated"
        else:
            try:
                rec.update(status="ok", **parse(rep.text))
            except (ValueError, json.JSONDecodeError) as e:
                rec["status"] = "parse_fail"; rec["error"] = str(e)
        return rec

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        recs = list(ex.map(one, jobs))
    cost = sum(r["prompt_tokens"] * p_in + r["completion_tokens"] * p_out
               for r in recs)

    out_dir = os.path.dirname(SHEET)
    meta = {"reader_model": READER_MODEL, "reader_provider": READER_PROVIDER,
            "judge_model_for_contrast": JUDGE_MODEL, "temperature": 0,
            "samples_per_case": a.samples, "date": now_iso(),
            "norms": "v1 (as printed in the sheet)",
            "status": "SUPPLEMENTARY automated proxy, not the human audit"}
    with open(os.path.join(out_dir, "abstention_blind_LLM_raw.jsonl"), "w",
              encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps({**meta, **r}) + "\n")

    per_case, rowsout = {}, []
    for r in rows:
        c = r["case"]
        ss = [x for x in recs if x["case"] == c]
        ok = [x for x in ss if x["status"] == "ok"]
        cls = [x["class"] for x in ok]
        maj = Counter(cls).most_common(1)[0] if cls else ("none", 0)
        unanimous = bool(cls) and len(set(cls)) == 1
        per_case[c] = {"majority": maj[0], "votes": maj[1], "n_ok": len(ok),
                       "unanimous": unanimous}
        rowsout.append({
            "case": c, **{f"sample{i}_class": (ok[i]["class"] if i < len(ok)
                                               else "") for i in range(3)},
            **{f"sample{i}_violated": ("Y" if ok[i]["violated"] else "N")
               if i < len(ok) else "" for i in range(3)},
            **{f"sample{i}_explains": (ok[i]["explains"] if i < len(ok)
                                       else "") for i in range(3)},
            "majority_class": maj[0], "majority_votes": f"{maj[1]}/{len(ok)}",
            "unanimous": unanimous,
            "agents_named": "|".join(sorted({x["agent"] for x in ok
                                             if x["agent"]})) or "",
            "steps_named": "|".join(sorted({x["step"] for x in ok
                                            if x["step"]})) or "",
            "justification_sample0": ok[0]["justification"] if ok else "",
            "n_ok": len(ok),
            "n_failed": len(ss) - len(ok), **meta})
    with open(os.path.join(out_dir, "abstention_blind_LLM.csv"), "w",
              newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["SUPPLEMENTARY automated proxy. An LLM auditing another "
                    "LLM's abstention is weaker evidence than the human "
                    "sheet and partly circular; reader shares failure modes "
                    "with the judge. NOT the human audit, and not to be "
                    "merged with it."])
        wd = csv.DictWriter(f, fieldnames=list(rowsout[0]))
        wd.writeheader(); wd.writerows(rowsout)

    c = Counter(v["majority"] for v in per_case.values())
    sup = c["supported_no_violation"] + c["supported_not_causal"]
    dec = len(per_case) - c["unresolved"]
    unan = sum(1 for v in per_case.values() if v["unanimous"])
    print(f"\nAUTOMATED PROXY ({a.samples} samples, temperature 0) -- NOT the "
          f"human audit")
    print(f"  no rule clearly violated                   : "
          f"{c['supported_no_violation']}")
    print(f"  rule violated, does NOT explain failure     : "
          f"{c['supported_not_causal']}")
    print(f"  rule violated AND explains failure          : "
          f"{c['unprincipled']}")
    print(f"  unresolved (explains unsure)                : {c['unresolved']}")
    if dec:
        print(f"  abstention supported (proxy): {sup}/{dec} = "
              f"{sup / dec:.2f} of decided cases")
    print(f"  sample agreement: {unan}/{len(per_case)} cases unanimous "
          f"across {a.samples} samples; disagreement rate "
          f"{1 - unan / len(per_case):.2f}")
    bad = [r for r in recs if r["status"] != "ok"]
    print(f"  infrastructure/parse failures: {len(bad)}"
          + (f" {Counter(r['status'] for r in bad)}" if bad else ""))
    print(f"  cost ${cost:.4f}")
    print(f"\n  per case: " + ", ".join(
        f"{c_}={v['majority'].replace('supported_', 's_')}"
        f"({v['votes']}/{v['n_ok']})" for c_, v in per_case.items()))
    print(f"\nwrote abstention_blind_LLM.csv and _raw.jsonl in "
          f"{os.path.relpath(out_dir, ROOT)}")
    print("Human sheets untouched.")


if __name__ == "__main__":
    main()
