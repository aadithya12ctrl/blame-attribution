"""
Who&When Hand-Crafted: norms + open verdict space vs the Who&When All-at-Once
baseline, with ablations. Same judge (gpt-oss-120b @ Cerebras, temp 0).

ARMS (all on the same 58 cases; steps printed and cited in every arm)
  M      method:   norms v1 + ground truth, open verdict, JSON
  B      baseline: Who&When All-at-Once, no norms, no ground truth, forced
  ABL-1  baseline + ground truth                       (isolates norms)
  ABL-2  method with norms v2 (O4, O8 removed)         (Orchestrator artifact)
  ABL-3  method WITHOUT ground truth (norms v1)        (answer key's effect)
  ABL-4  method with norms v3 (O4 as a process rule)   (checkable w/o GT)

2x2 (norms x ground truth):  B = no/no, ABL-1 = no/yes, ABL-3 = yes/no,
M = yes/yes. Within a norms row the verdict space and output format are
fixed, so the ground-truth effect is clean. Across rows they are not: the
norms rows use the open verdict and JSON, the no-norms rows are forced and
free-text (the Who&When format). The norms effect is therefore confounded
with verdict space and format.

PRE-REGISTERED (fixed before results): headline numbers include cases 20,
22 and 49 (label step belongs to another agent); a sensitivity figure
excludes them. Any case that cannot fit the judge's context in ANY arm is
excluded from EVERY arm and listed.

Integrity: v1 norms verified against the pre-data freeze; v2/v3 verified
against their post-hoc locks and required to derive from v1. Truncation,
API errors and context overflow are infrastructure: excluded, reported,
never scored.

  OPENROUTER_API_KEY=... python3 experiments/exp_whowhen.py --limit 3   # dry run
  OPENROUTER_API_KEY=... python3 experiments/exp_whowhen.py             # all arms
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr.judge import JUDGE_MODEL, JUDGE_PROVIDER  # noqa: E402
from faultattr.llm import LLM, now_iso, verify_provider  # noqa: E402
from faultattr.whowhen import (verify_norms, load_hand_crafted,  # noqa: E402
                               rules_blocks)

WW_MAX_TOKENS = 32_000        # raised from 6,000: 3 pilot replies truncated
CTX_MARGIN = 1_024
INFRA = {"api_error", "truncated", "context_too_long"}
LABEL_INCONSISTENT = {20, 22, 49}
DRY_SEED = 2026
PILOT_RAW = os.path.join(ROOT, "results", "whowhen_20260922-215346",
                         "raw.jsonl")
ARMS = {  # prompt family, norms version, ground truth
    "M":     ("method",   "v1", True),
    "B":     ("baseline", None, False),
    "ABL-1": ("baseline", None, True),
    "ABL-2": ("method",   "v2", True),
    "ABL-3": ("method",   "v1", False),
    "ABL-4": ("method",   "v3", True),
    # rule-count experiment (PREREG_rulecount_20261002.md): same prompt and
    # ground truth as M; only the norm set's rules-per-agent differs.
    "N-BAL":  ("method", "nbal",  True),
    "N-ORCH": ("method", "norch", True),
    "N-WEB":  ("method", "nweb",  True),
}
ARM_DESC = {"M": "method: norms v1 + GT", "B": "baseline (Who&When)",
            "ABL-1": "baseline + GT", "ABL-2": "method, norms v2 (no O4/O8)",
            "ABL-3": "method, norms v1, no GT",
            "ABL-4": "method, norms v3 (O4 process rule)",
            "N-BAL": "norms N-BAL: 3 rules per agent",
            "N-ORCH": "norms N-ORCH: 8 Orchestrator rules, 2 each elsewhere",
            "N-WEB": "norms N-WEB: 8 WebSurfer rules, 2 each elsewhere"}
CANON = {"orchestrator": "Orchestrator", "websurfer": "WebSurfer",
         "filesurfer": "FileSurfer", "coder": "Coder",
         "assistant": "Coder",               # Magentic-One's Coder role name
         "computerterminal": "ComputerTerminal"}


def canon(name):
    """'Orchestrator (thought)' -> Orchestrator; 'Assistant' -> Coder."""
    if name is None:
        return None
    s = re.sub(r"[*`\"']", "", str(name)).strip()
    s = re.sub(r"\s*\(.*\)\s*$", "", s).strip().lower().replace(" ", "")
    return CANON.get(s)


def chat_content(case, numbered=True):
    """Who&When's 'role: content' rendering; numbered adds '[step i] '."""
    return "\n".join((f"[step {i}] " if numbered else "")
                     + f"{e.get('role', 'Unknown Agent')}: "
                       f"{e.get('content', '')}"
                     for i, e in enumerate(case["history"]))


# ------------------------------------------------------------------ prompts

BASE_SYSTEM = "You are a helpful assistant skilled in analyzing conversations."
METHOD_SYSTEM = ("You are an expert at diagnosing failures in multi-agent "
                 "LLM systems. Answer with a single JSON object and nothing "
                 "else.")
NUM_NOTE = ("Each entry is prefixed with its printed step number, [step N] "
            "(the human's request is [step 0]). Your step must be one of "
            "these printed step numbers.")


def baseline_prompt(case, gt=False, numbered=True):
    # Who&When all_at_once, verbatim; the ground-truth line is theirs too.
    return (
        "You are an AI assistant tasked with analyzing a multi-agent "
        "conversation history when solving a real world problem. "
        f"The problem is:  {case['question']}\n"
        + (f"The Answer for the problem is: {case['groundtruth']}\n"
           if gt else "")
        + "Identify which agent made an error, at which step, and explain "
        "the reason for the error. "
        + (NUM_NOTE + " " if numbered else "")
        + "Here's the conversation:\n\n" + chat_content(case, numbered) +
        "\n\nBased on this conversation, please predict the following:\n"
        "1. The name of the agent who made a mistake that should be directly "
        "responsible for the wrong solution to the real world problem. If "
        "there are no agents that make obvious mistakes, decide one single "
        "agent in your mind. Directly output the name of the Expert.\n"
        "2. In which step the mistake agent first made mistake. For example, "
        "in a conversation structured as follows: "
        """
            {
                "agent a": "xx",
                "agent b": "xxxx",
                "agent c": "xxxxx",
                "agent a": "xxxxxxx"
            },
            """
        "each entry represents a 'step' where an agent provides input. The "
        "'x' symbolizes the speech of each agent. If the mistake is in agent "
        "c's speech, the step number is 2. If the second speech by 'agent a' "
        "contains the mistake, the step number is 3, and so on. Please "
        "determine the step number where the first mistake occurred."
        + (" Your answer must be one of the printed step numbers."
           if numbered else "") + "\n"
        "3. The reason for your prediction."
        "Please answer in the format: Agent Name: (Your prediction)\n Step "
        "Number: (Your prediction)\n Reason for Mistake: \n")


def method_prompt(case, rules, gt=True, numbered=True):
    return (
        "The following conversation is a Magentic-One team attempting to "
        "solve a real world problem. It produced a wrong answer.\n"
        f"The problem is:  {case['question']}\n"
        + (f"The correct answer is: {case['groundtruth']}\n" if gt else "")
        + "\n"
        + (NUM_NOTE if numbered else
           "Each entry is one step, numbered from 0 in order of appearance "
           "(the first entry, the human's request, is step 0).")
        + " Orchestrator entries appear as 'Orchestrator (...)'; the Coder "
        "appears as 'Assistant'.\n\nHere's the conversation:\n\n"
        + chat_content(case, numbered)
        + "\n\nThese are the written RULES each agent was given:\n\n" + rules
        + "\n\nQUESTION: Did an agent clearly violate one of its stated RULES "
        "in a way that is directly responsible for the wrong answer? If so, "
        "give that agent, the step of its FIRST such violation, and the rule. "
        "If no stated rule was clearly violated, answer UNDERDETERMINED with "
        "agent and step null. Do not guess and do not force an answer.\n"
        "Answer with JSON only:\n"
        '{"agent": <one of Orchestrator, WebSurfer, FileSurfer, Coder, '
        'ComputerTerminal, or null>, "step": <printed step number or null>, '
        '"verdict": "RULE_VIOLATION" | "UNDERDETERMINED", '
        '"rule_violated": "<rule id and text, or empty>", '
        '"reason": "<one or two sentences>"}')


def build_prompt(arm, case, rules_by_version):
    fam, ver, gt = ARMS[arm]
    if fam == "method":
        return METHOD_SYSTEM, method_prompt(case, rules_by_version[ver], gt)
    return BASE_SYSTEM, baseline_prompt(case, gt)


# ------------------------------------------------------------------ parsing

def _json_obj(text):
    t = re.sub(r"^```[A-Za-z]*\s*\n?|\n?\s*```\s*$", "", text.strip()).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j <= i:
            raise ValueError("no JSON object")
        return json.loads(t[i:j + 1])


def parse_method(text, n_steps):
    o = _json_obj(text)
    v = str(o.get("verdict", "")).strip().upper()
    if v == "UNDERDETERMINED":
        return {"verdict": v, "agent": None, "step": None,
                "rule_violated": "", "reason": str(o.get("reason", ""))}
    if v != "RULE_VIOLATION":
        raise ValueError(f"verdict {v!r} not RULE_VIOLATION|UNDERDETERMINED")
    a = canon(o.get("agent"))
    if a is None:
        raise ValueError(f"agent {o.get('agent')!r} is not a team agent")
    raw = o.get("step")
    m = re.search(r"\d+", str(raw)) if raw is not None else None
    if not m:
        raise ValueError(f"step {raw!r} is not an integer")
    s = int(m.group(0))
    if not 0 <= s < n_steps:
        raise ValueError(f"step {s} outside 0..{n_steps - 1}")
    return {"verdict": v, "agent": a, "step": s,
            "rule_violated": str(o.get("rule_violated", "")),
            "reason": str(o.get("reason", ""))}


def parse_baseline(text, n_steps):
    t = re.sub(r"[*#`]", "", text)
    ma = re.search(r"Agent Name:\s*(.+)", t)
    ms = re.search(r"Step Number:\s*(?:\[?\s*step\s*)?(\d+)", t, re.I)
    if not ma or not ms:
        raise ValueError("missing 'Agent Name:' or 'Step Number:'")
    a = canon(ma.group(1).strip().splitlines()[0])
    if a is None:
        raise ValueError(f"agent {ma.group(1).strip()[:40]!r} not a team agent")
    s = int(ms.group(1))
    if not 0 <= s < n_steps:
        raise ValueError(f"step {s} outside 0..{n_steps - 1}")
    mr = re.search(r"Reason for Mistake:\s*(.*)", t, re.S)
    return {"verdict": "ANSWERED", "agent": a, "step": s, "rule_violated": "",
            "reason": (mr.group(1).strip() if mr else "")[:600]}


def fail_cause(err):
    e = err or ""
    m = re.search(r"step (\d+) outside 0\.\.(\d+)", e)
    if m and int(m.group(1)) == int(m.group(2)) + 1:
        # the Orchestrator's final answer, which the history does not record
        return "step one past the last (final answer, not in the trace)"
    return ("step out of range" if "outside" in e else
            "step missing / not an integer" if "not an integer" in e
            or "Step Number" in e else
            "agent not a team agent" if "not a team agent" in e else
            "bad verdict" if "verdict" in e else "malformed output")


# ------------------------------------------------------------------ judging

def call(llm, arm, case, system, user, est_tokens):
    rec = {"arm": arm, "case": case["_case"], "prompt_chars":
           len(system) + len(user), "est_prompt_tokens": est_tokens,
           "prompt_tokens": 0, "completion_tokens": 0, "finish_reason": None,
           "served_by": None, "status": None, "error": None, "raw": "",
           "verdict": None, "agent": None, "step": None, "rule_violated": "",
           "reason": ""}
    rep = llm.chat(system, user, temperature=0.0)
    rec.update(prompt_tokens=rep.prompt_tokens,
               completion_tokens=rep.completion_tokens,
               finish_reason=rep.finish_reason, served_by=rep.served_by,
               raw=rep.text)
    if not rep.ok:
        rec.update(status="api_error", error=rep.error)
    elif rep.finish_reason == "length":
        rec.update(status="truncated")
    else:
        fam = ARMS[arm][0]
        try:
            p = (parse_method if fam == "method" else parse_baseline)(
                rep.text, len(case["history"]))
            rec.update(status="ok", **p)
        except (ValueError, json.JSONDecodeError) as e:
            rec.update(status="parse_fail", error=str(e))
    return rec


def score(rec, case):
    la, ls = canon(case["mistake_agent"]), int(case["mistake_step"])
    ans = rec["status"] == "ok" and rec["verdict"] != "UNDERDETERMINED"
    rec.update(label_agent=la, label_step=ls, answered=ans,
               agent_correct=ans and rec["agent"] == la,
               step_correct=ans and rec["step"] == ls)
    return rec


# ------------------------------------------------------------------ report

def pct(k, d):
    return f"{k}/{d} = {k / d:.3f}" if d else "n/a"


def metrics(recs, exclude=frozenset()):
    rs = [r for r in recs if r["case"] not in exclude]
    scor = [r for r in rs if r["status"] not in INFRA]
    ans = [r for r in scor if r["answered"]]
    return {"n": len(rs), "scor": len(scor), "ans": len(ans),
            "cov": len(ans) / len(scor) if scor else 0,
            "ag_ans": (sum(r["agent_correct"] for r in ans), len(ans)),
            "st_ans": (sum(r["step_correct"] for r in ans), len(ans)),
            "ag_all": (sum(r["agent_correct"] for r in scor), len(scor)),
            "st_all": (sum(r["step_correct"] for r in scor), len(scor)),
            "infra": Counter(r["status"] for r in rs if r["status"] in INFRA),
            "pf": Counter(fail_cause(r["error"]) for r in scor
                          if r["status"] == "parse_fail")}


def arm_block(arm, recs, by_case):
    m, s = metrics(recs), metrics(recs, LABEL_INCONSISTENT)
    L = [f"{arm}  ({ARM_DESC[arm]})",
         f"  calls {m['n']}: infrastructure excluded {sum(m['infra'].values())}"
         f" {dict(m['infra']) or ''}; parse failures "
         f"{sum(m['pf'].values())} {dict(m['pf']) or ''}",
         f"  coverage (answered / scorable):    {pct(m['ans'], m['scor'])}",
         f"  agent accuracy  answered / all:    {pct(*m['ag_ans'])}   |   "
         f"{pct(*m['ag_all'])}",
         f"  step accuracy   answered / all:    {pct(*m['st_ans'])}   |   "
         f"{pct(*m['st_all'])}",
         f"  sensitivity, excl. cases 20/22/49: agent all "
         f"{pct(*s['ag_all'])}, step all {pct(*s['st_all'])}",
         "  blamed agents (answered): " + str(dict(Counter(
             r["agent"] for r in recs if r["answered"]).most_common()))]
    und = [r for r in recs if r["status"] == "ok"
           and r["verdict"] == "UNDERDETERMINED"]
    if ARMS[arm][0] == "method":
        L.append(f"  abstentions (UNDERDETERMINED): {len(und)}")
        for r in und:
            c = by_case[r["case"]]
            L.append(f"    case {r['case']}  label {r['label_agent']} @ "
                     f"{r['label_step']}: {c['mistake_reason'][:200]}")
    inf = [r for r in recs if r["status"] in INFRA]
    for r in inf:
        L.append(f"  infra: case {r['case']} {r['status']} {r['error'] or ''}")
    return L


AUDIT_VERDICTS = ["label_right", "method_right", "both_defensible", "neither"]
YES, NO = {"y", "yes", "1", "true"}, {"n", "no", "0", "false"}
ALLOW_PARTIAL = [False]        # set from --allow-partial


def _read_sheet(path, key="case"):
    csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))
    with open(path, encoding="utf-8", newline="") as f:
        lines = list(csv.reader(f))
    i = next(j for j, r in enumerate(lines) if r and r[0] == key)
    return [dict(zip(lines[i], r)) for r in lines[i + 1:] if r]


UNSURE = {"unsure", "u", "?", "maybe", "unclear"}
RUN_LOG = os.path.join(ROOT, "results", "label_scoring_runs.log")


def log_run(kind, paths, allow_partial, note=""):
    """Append every scoring invocation, so a later --allow-partial is in the
    record rather than in someone's memory."""
    os.makedirs(os.path.dirname(RUN_LOG), exist_ok=True)
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(f"{now_iso()}  {kind}  allow_partial={allow_partial}  "
                f"{paths}  {note}\n")


def classify(v, ex):
    """
    Two separate questions, per the framework's own error/fault split:
      violated = N                 -> abstention supported (no rule broken)
      violated = Y, explains = N   -> abstention supported (an error that did
                                      not become a fault FOR THIS failure)
      violated = Y, explains = Y   -> abstention unprincipled
      violated = Y, explains = ?   -> unresolved, reported separately
    """
    if not v:
        return "supported_no_violation"
    return {"y": "unprincipled", "n": "supported_not_causal"}.get(
        ex, "unresolved")


def score_blind(paths, allow_partial=False):
    """Stage-1 blind abstention audit. The labeller sees the trace and the
    RULES, never the benchmark label or the method's answer."""
    plist = [x.strip() for x in paths.split(",") if x.strip()]
    log_run("score-blind", ",".join(os.path.basename(p) for p in plist),
            allow_partial)
    sheets = []
    for p in plist:
        rows = _read_sheet(p)
        marks, blank, bad = {}, [], []
        for r in rows:
            v = (r.get("violated") or "").strip().lower()
            ex = (r.get("explains") or "").strip().lower()
            if not v:
                blank.append(r["case"]); continue
            if v not in YES | NO:
                bad.append(f"{r['case']} violated={v!r}"); continue
            viol = v in YES
            if viol and not ex:
                blank.append(f"{r['case']} (explains)"); continue
            if viol and ex not in YES | NO | UNSURE:
                bad.append(f"{r['case']} explains={ex!r}"); continue
            marks[int(r["case"])] = {
                "violated": viol,
                "explains": ("y" if ex in YES else "n" if ex in NO
                             else "unsure") if viol else "",
                "agent": (r.get("which_agent") or "").strip(),
                "step": (r.get("which_step") or "").strip()}
            marks[int(r["case"])]["class"] = classify(
                viol, marks[int(r["case"])]["explains"])
        print(f"{os.path.basename(p)}: {len(rows)} rows, labelled "
              f"{len(marks)}, blank {len(blank)}, invalid {len(bad)}")
        for x in bad:
            print(f"  invalid: {x}")
        if blank and not allow_partial:
            print(f"  REFUSING to print aggregates: {len(blank)} unfilled "
                  f"({blank}). Label every row first -- reading the totals "
                  f"early is the pressure this sheet exists to measure. Use "
                  f"--allow-partial to override (it is logged).")
            return
        sheets.append((p, marks))
    if not sheets:
        return
    _, m0 = sheets[0]
    n = len(m0)
    if not n:
        return
    c = Counter(v["class"] for v in m0.values())
    sup = c["supported_no_violation"] + c["supported_not_causal"]
    unp, unres = c["unprincipled"], c["unresolved"]
    print(f"\nSTAGE 1 (blind) on {n} abstention cases")
    print(f"  no rule clearly violated                     : "
          f"{c['supported_no_violation']}")
    print(f"  rule violated, does NOT explain the failure   : "
          f"{c['supported_not_causal']}   (error, not a fault for this "
          f"failure -- supports the abstention)")
    print(f"  rule violated AND explains the failure        : {unp}"
          f"   (abstention unprincipled)")
    print(f"  rule violated, explains unsure                : {unres}")
    dec = n - unres
    if dec:
        print(f"\n  Abstaining principled: {sup}/{dec} = {sup / dec:.2f} of "
              f"decided cases")
        print(f"  Bounds if every 'unsure' went each way: "
              f"{sup / n:.2f} (all unsure count against) to "
              f"{(sup + unres) / n:.2f} (all count for)")
    for c_, v in sorted(m0.items()):
        if v["class"] == "unprincipled":
            print(f"    unprincipled: case {c_} -- {v['agent'] or '?'} @ step "
                  f"{v['step'] or '?'}")
    for p1, m1 in sheets[1:]:
        shared = sorted(set(m0) & set(m1))
        if not shared:
            print(f"\n  {os.path.basename(p1)}: no cases in common")
            continue
        def kappa(f):
            ya = [f(m0[c_]) for c_ in shared]
            yb = [f(m1[c_]) for c_ in shared]
            obs = sum(x == y for x, y in zip(ya, yb)) / len(shared)
            pa, pb = sum(ya) / len(shared), sum(yb) / len(shared)
            e = pa * pb + (1 - pa) * (1 - pb)
            return obs, ((obs - e) / (1 - e) if e < 1 else float("nan"))
        ov, kv = kappa(lambda d: d["violated"])
        ou, ku = kappa(lambda d: d["class"] == "unprincipled")
        print(f"\n  vs {os.path.basename(p1)}: {len(shared)} shared cases")
        print(f"    'violated'    agreement {ov:.2f}, kappa {kv:.2f}")
        print(f"    'unprincipled' agreement {ou:.2f}, kappa {ku:.2f}")
        for c_ in shared:
            if m0[c_]["class"] != m1[c_]["class"]:
                print(f"    case {c_}: A {m0[c_]['class']} vs B "
                      f"{m1[c_]['class']}  <- case E, measured")


def score_audit(path):
    """
    Tabulate a hand-filled label_audit.csv (method vs Who&When label).

    Two numbers matter. (1) Among rows where the method ABSTAINED, the share
    marked method_right is the rate at which abstaining was principled.
    (2) The share of ALL rows marked both_defensible or neither is evidence
    that the benchmark encodes one annotation convention rather than a fact
    about the trace -- the section 2.6 divergence claim, reached from the
    other direction.
    """
    csv.field_size_limit(min(2 ** 31 - 1, sys.maxsize))
    with open(path, encoding="utf-8", newline="") as f:
        lines = list(csv.reader(f))
    start = next(i for i, r in enumerate(lines) if r and r[0] == "case")
    hdr, rows = lines[start], [dict(zip(lines[start], r))
                               for r in lines[start + 1:] if r]
    log_run("score-audit", os.path.basename(path), ALLOW_PARTIAL[0])
    filled = [r for r in rows if r.get("human_verdict", "").strip()]
    bad = [f"{r['case']}={r['human_verdict']!r}" for r in filled
           if r["human_verdict"].strip().lower() not in AUDIT_VERDICTS]
    print(f"label audit: {len(rows)} rows; filled {len(filled)}; "
          f"unfilled {len(rows) - len(filled)}; invalid {len(bad)}")
    for b in bad:
        print(f"  invalid: {b}")
    if len(filled) < len(rows) and not ALLOW_PARTIAL[0]:
        print(f"  REFUSING to print aggregates: {len(rows) - len(filled)} "
              f"rows still unfilled. Use --allow-partial to override.")
        return
    use = [r for r in filled if r["human_verdict"].strip().lower()
           in AUDIT_VERDICTS]
    if not use:
        print("  nothing scorable yet")
        return
    cnt = Counter(r["human_verdict"].strip().lower() for r in use)
    print(f"\n  {'verdict':<18}{'count':>7}{'share':>8}")
    for v in AUDIT_VERDICTS:
        print(f"  {v:<18}{cnt.get(v, 0):>7}{cnt.get(v, 0) / len(use):>8.2f}")
    abst = [r for r in use if r.get("method_verdict") == "UNDERDETERMINED"]
    ans = [r for r in use if r.get("method_verdict") != "UNDERDETERMINED"]
    if abst:
        ok = sum(1 for r in abst if r["human_verdict"].strip().lower()
                 in ("method_right", "both_defensible"))
        print(f"\n  abstentions audited: {len(abst)}; abstaining judged "
              f"principled (method_right or both_defensible): {ok}/{len(abst)}"
              f" = {ok / len(abst):.2f}")
    if ans:
        lr = sum(1 for r in ans if r["human_verdict"].strip().lower()
                 == "label_right")
        print(f"  answered-but-disagreeing rows: {len(ans)}; label upheld "
              f"{lr}/{len(ans)} = {lr / len(ans):.2f}")
    conv = sum(cnt.get(v, 0) for v in ("both_defensible", "neither"))
    print(f"\n  both_defensible or neither: {conv}/{len(use)} = "
          f"{conv / len(use):.2f}")
    print("  A large share here is evidence the annotation is one convention "
          "among several\n  (section 2.6), not a fact the trace fixes.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score-audit", default=None,
                    help="tabulate a hand-filled label_audit.csv and exit")
    ap.add_argument("--score-blind", default=None,
                    help="score stage-1 blind abstention sheet(s); "
                         "comma-separated for inter-labeller agreement")
    ap.add_argument("--allow-partial", action="store_true",
                    help="print aggregates from a partly filled sheet")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--cases", default=None,
                    help="comma-separated case numbers, e.g. to complete an "
                         "arm whose calls failed on infrastructure")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cost-cap", type=float, default=3.0)
    a = ap.parse_args()
    ALLOW_PARTIAL[0] = a.allow_partial
    if a.score_blind:
        score_blind(a.score_blind, a.allow_partial)
        return
    if a.score_audit:
        score_audit(a.score_audit)
        return
    arms = [x.strip() for x in a.arms.split(",")]

    lock = verify_norms("v1")                  # BEFORE any record is loaded
    locks = {"v1": lock}
    for v in ("v2", "v3", "nbal", "norch", "nweb"):
        locks[v] = verify_norms(v)
    cases = load_hand_crafted(lock)
    rules = {v: rules_blocks(v) for v in locks}
    if a.cases:
        want = {int(x) for x in a.cases.split(",")}
        cases = [c for c in cases if c["_case"] in want]
        missing = want - {c["_case"] for c in cases}
        if missing:
            raise SystemExit(f"unknown cases: {sorted(missing)}")
    if a.limit:
        cases = sorted(random.Random(DRY_SEED).sample(cases, a.limit),
                       key=lambda c: c["_case"])
    by_case = {c["_case"]: c for c in cases}

    llm = LLM(model=JUDGE_MODEL, provider=JUDGE_PROVIDER, temperature=0.0,
              max_tokens=WW_MAX_TOKENS)
    ep = verify_provider(llm.model, llm.provider)
    ctx = int(ep.get("context_length") or 131_072)
    max_out = int(ep.get("max_completion_tokens") or WW_MAX_TOKENS)
    p_in, p_out = (float(ep["pricing"]["prompt"]),
                   float(ep["pricing"]["completion"]))
    if WW_MAX_TOKENS > max_out:
        raise SystemExit(f"max_tokens {WW_MAX_TOKENS} > endpoint max {max_out}")

    # calibrate chars/token per case from the pilot's actual token counts
    ratio = {}
    if os.path.exists(PILOT_RAW):
        for ln in open(PILOT_RAW, encoding="utf-8"):
            r = json.loads(ln)
            if r.get("prompt_tokens"):
                ratio.setdefault(r["case"], []).append(
                    r["prompt_chars"] / r["prompt_tokens"])
    ratio = {k: min(v) for k, v in ratio.items()}   # conservative
    prompts = {(arm, c["_case"]): build_prompt(arm, c, rules)
               for arm in arms for c in cases}
    est = {k: int(sum(map(len, v)) / ratio.get(k[1], 3.2))
           for k, v in prompts.items()}
    limit_prompt = ctx - WW_MAX_TOKENS - CTX_MARGIN
    too_long = sorted({k[1] for k, t in est.items() if t > limit_prompt})
    longest = max(est.items(), key=lambda kv: kv[1])
    print(f"context {ctx:,}; max_tokens {WW_MAX_TOKENS:,}; prompt limit "
          f"{limit_prompt:,}; longest est prompt {longest[1]:,} tokens "
          f"(arm {longest[0][0]}, case {longest[0][1]}); cases excluded from "
          f"EVERY arm for context: {too_long or 'none'}")
    work = [c for c in cases if c["_case"] not in too_long]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(ROOT, "results", f"whowhen_abl_{stamp}"
                       + (f"_dry{a.limit}" if a.limit else ""))
    os.makedirs(out, exist_ok=False)
    date = now_iso()

    results, spent, skipped = {}, 0.0, []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for arm in arms:
            proj = sum(est[(arm, c["_case"])] for c in work) * p_in \
                + len(work) * 2_000 * p_out
            if spent + proj > a.cost_cap:
                skipped.append(f"{arm} (projected ${proj:.3f}, spent "
                               f"${spent:.3f}, cap ${a.cost_cap})")
                print(f"SKIP {arm}: would exceed the cost cap")
                continue
            print(f"running {arm} ({ARM_DESC[arm]}): {len(work)} calls, "
                  f"projected ${proj:.3f}", flush=True)
            recs = list(ex.map(lambda c: call(
                llm, arm, c, *prompts[(arm, c["_case"])],
                est[(arm, c["_case"])]), work))
            for r in recs:
                score(r, by_case[r["case"]])
            spent += sum(r["prompt_tokens"] * p_in + r["completion_tokens"]
                         * p_out for r in recs)
            results[arm] = recs

    all_recs = [r for rs in results.values() for r in rs]
    ptoks = sorted(r["prompt_tokens"] for r in all_recs if r["prompt_tokens"])
    L = [f"WHO&WHEN HAND-CRAFTED -- ABLATIONS  {stamp}   date {date}",
         f"judge: {llm.model} @ {llm.provider}, temperature 0, max_tokens "
         f"{WW_MAX_TOKENS:,} (context {ctx:,}); steps printed and cited in "
         f"every arm",
         "norms: " + ", ".join(f"{v} {locks[v]['sha256'][:12]}"
                               for v in locks),
         f"cases: {len(cases)}" + (f" (dry run, random.Random({DRY_SEED}))"
                                   if a.limit else " (all Hand-Crafted)")
         + f"; excluded from every arm for context: {too_long or 'none'}",
         f"longest prompt: {ptoks[-1] if ptoks else 0:,} tokens actual "
         f"(est {longest[1]:,}); median {ptoks[len(ptoks) // 2] if ptoks else 0:,}",
         f"judge output tokens: mean "
         f"{sum(r['completion_tokens'] for r in all_recs) / max(1, len(all_recs)):.0f}"
         f"  max {max((r['completion_tokens'] for r in all_recs), default=0):,}",
         f"cost (token counts x Cerebras price): ${spent:.4f}  (cap "
         f"${a.cost_cap})" + (f"   SKIPPED: {skipped}" if skipped else ""),
         "headline = all cases incl. 20/22/49 (pre-registered); sensitivity "
         "excludes them", ""]

    def cell(arm, key="ag_all"):
        if arm not in results:
            return "not run"
        m = metrics(results[arm])
        return (f"agent {pct(*m['ag_all'])}; step {pct(*m['st_all'])}; "
                f"coverage {m['cov']:.2f}")
    L += ["2x2 (all cases; abstention and parse failure count as wrong)",
          "                     ground truth: NO                          |"
          "  ground truth: YES",
          f"  norms NO  (forced)  B      {cell('B'):<44}|  ABL-1  "
          f"{cell('ABL-1')}",
          f"  norms YES (open)    ABL-3  {cell('ABL-3'):<44}|  M      "
          f"{cell('M')}",
          "  norms variants (GT yes):  ABL-2 (no O4/O8): "
          f"{cell('ABL-2')}",
          f"                            ABL-4 (O4 process): {cell('ABL-4')}",
          "  Caveat: rows also differ in verdict space and output format.", ""]
    for arm in arms:
        if arm in results:
            L += arm_block(arm, results[arm], by_case) + [""]

    # common set: cases scorable in every arm that ran
    ran = list(results)
    common = set(by_case) - set(too_long)
    for arm in ran:
        common &= {r["case"] for r in results[arm]
                   if r["status"] not in INFRA}
    L.append(f"COMMON SET (scorable in every arm run): {len(common)} cases")
    for arm in ran:
        rs = [r for r in results[arm] if r["case"] in common]
        L.append(f"  {arm:<6} agent {pct(sum(r['agent_correct'] for r in rs), len(rs))}"
                 f"   step {pct(sum(r['step_correct'] for r in rs), len(rs))}")
    L.append("")

    # old (unnumbered pilot) vs new (numbered) for M and B
    if os.path.exists(PILOT_RAW) and not a.limit:
        old = [json.loads(x) for x in open(PILOT_RAW, encoding="utf-8")]
        L.append("OLD (pilot, unnumbered, max_tokens 6000) vs NEW (numbered, "
                 f"max_tokens {WW_MAX_TOKENS:,})")
        for arm, fam in (("M", "method"), ("B", "baseline")):
            if arm not in results:
                continue
            o = [r for r in old if r["method"] == fam]
            for r in o:
                r.setdefault("arm", arm)
            mo, mn = metrics(o), metrics(results[arm])
            L.append(f"  {arm}: coverage {mo['cov']:.2f} -> {mn['cov']:.2f};"
                     f"  agent all {pct(*mo['ag_all'])} -> {pct(*mn['ag_all'])};"
                     f"  step all {pct(*mo['st_all'])} -> {pct(*mn['st_all'])};"
                     f"  parse fail {sum(mo['pf'].values())} -> "
                     f"{sum(mn['pf'].values())};  truncated "
                     f"{mo['infra'].get('truncated', 0)} -> "
                     f"{mn['infra'].get('truncated', 0)}")
        L.append("")
    L.append("CONFOUNDS: ground truth is isolated within a norms row; the "
             "norms effect is confounded\nwith verdict space and output "
             "format. v2/v3 are post-hoc variants frozen after the pilot.")

    text = "\n".join(L)
    print("\n" + text)
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    meta = {"judge_model": llm.model, "judge_provider": llm.provider,
            "judge_max_tokens": WW_MAX_TOKENS, "date": date,
            **{f"norms_{v}_sha256": locks[v]["sha256"] for v in locks}}
    cols = ["arm", "case", "status", "verdict", "agent", "step",
            "label_agent", "label_step", "answered", "agent_correct",
            "step_correct", "rule_violated", "reason", "error",
            "finish_reason", "served_by", "prompt_tokens",
            "completion_tokens", "est_prompt_tokens"]
    with open(os.path.join(out, "rows.csv"), "w", newline="",
              encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols + list(meta),
                           extrasaction="ignore")
        w.writeheader()
        for r in all_recs:
            w.writerow({**r, **meta})
    with open(os.path.join(out, "raw.jsonl"), "w", encoding="utf-8") as f:
        for r in all_recs:
            f.write(json.dumps({**meta, **r}) + "\n")
    print(f"\nwrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
