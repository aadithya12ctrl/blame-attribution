"""
Build the three rule-count norm sets (N-BAL, N-ORCH, N-WEB) from the frozen
v1 norms by changing GRANULARITY ONLY, and freeze each with a hash lock.

Every rule carries the v1 rule(s) it came from and the operation (split or
merge). No new obligation is introduced; splits follow enumerations that
already appear in the cited documentation (see each file's derivation
table). Run once: the locks are written with exclusive-create.

  python3 experiments/build_rulecount_norms.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from faultattr.whowhen import verify_norms, norms_path, lock_path  # noqa: E402

HEAD = """# Magentic-One agent norms — {name}

{summary}

Derived from the frozen v1 norms (`faultattr/norms/magentic_one.md`, sha256
{v1sha}) by changing RULE GRANULARITY ONLY: adjacent v1 rules merged, or a
v1 rule split along an enumeration already present in the cited
documentation. No new obligation is introduced and no rule is worded to
describe a failure mode. Sources are v1's: [P] arXiv:2411.04468v1,
[D] AutoGen Magentic-One docs, [OP] orchestrator prompts, [CP] coder system
message, [WP] web-surfer description and tool prompt, [FP] file-surfer
description. The derivation table at the end gives rule-by-rule provenance.

Frozen after the Who&When pilot, for the rule-count experiment
pre-registered in `results/PREREG_rulecount_20261002.md`.
"""

# --- shared blocks, all merges/splits of v1 text -------------------------
F_2 = [("F1", "F1", "Operate read-only. Read local files of the requested "
        "type, list directory contents, and navigate the folder structure. "
        "[P; D; FP]"),
       ("F2", "F2", "Report what the file or directory contains. [inferred "
        "in v1 from P's 'very similar to the WebSurfer']")]
T_2 = [("T1", "T1", "Execute the Coder's programs and shell commands "
        "(including installing libraries) and return the console output. "
        "[P; D]"),
       ("T2", "T2", "Report execution results as produced, without altering "
        "them. [inferred in v1]")]
C_2 = [("C1", "merge of C1+C2+C3+C5", "When code is needed, provide it in a "
        "single python or sh block, state the script type, make it complete "
        "and runnable without modification (full code, not partial), use "
        "print for output rather than asking for copy-paste, and explain "
        "the plan first when none was given. [CP]"),
       ("C2", "merge of C4+C6", "Check the execution result: on an error, "
        "fix it and output the full code again; if it cannot be fixed, "
        "revisit assumptions and try a different approach. When an answer "
        "is found, verify it and include verifiable evidence. [CP]")]
W_2 = [("W1", "merge of W1+W3", "Map each request to a single action from "
        "the action space — navigation (visit a URL, web search, scroll), "
        "page actions (click, type), reading (summarize, answer questions) — "
        "choosing by where the needed information is: the current viewport, "
        "elsewhere on the current page, or another website. [P; WP]"),
       ("W2", "merge of W2+W4", "After acting, report the new state of the "
        "page, and base any summary or answer on the content of the page. "
        "[P; D; WP]")]
O_8 = [("O1", "O1", "Before planning, survey the facts: those GIVEN or "
        "verified in the request, those to LOOK UP (and where), those to "
        "DERIVE, and EDUCATED GUESSES. [OP facts prompt; P]"),
       ("O2", "O2", "Devise a short step-by-step plan that assigns steps to "
        "members of the assembled team only, and involves no outside "
        "people. [OP plan prompts; P]"),
       ("O3", "O3", "Each turn, assess whether the request is fully "
        "satisfied, whether the team is in a loop, and whether forward "
        "progress is being made. [OP progress ledger; P]"),
       ("O4", "O4", "Consider the request satisfied only if it has been "
        "SUCCESSFULLY and FULLY addressed. [OP progress ledger]"),
       ("O5", "O5", "Choose the next speaker from the team, and give that "
        "agent an instruction or question, phrased directly to it, that "
        "includes any specific information it needs. [OP progress ledger]"),
       ("O6", "O6", "Treat repeated requests or responses as a loop "
        "(including repeated actions such as scrolling more than a handful "
        "of times). Treat a lack of forward progress, such as an inability "
        "to read a required file, as a stall. [OP progress ledger]"),
       ("O7", "O7", "When stalled, re-plan: identify the root cause of the "
        "failure, update the fact sheet (adding or updating at least one "
        "educated guess), and write a new plan that avoids repeating the "
        "same mistakes. [OP update prompts; P]"),
       ("O8", "O8", "At the end, review the full transcript and ledger, and "
        "report a final answer based on the information gathered, or the "
        "best educated guess. [P; OP final-answer prompt]")]
O_2 = [("O1", "merge of O1+O2+O5", "Survey the facts (given or verified, to "
        "look up, to derive, educated guesses), devise a short plan that "
        "assigns steps to the assembled team only, and each turn name the "
        "next speaker with an instruction that includes the information it "
        "needs. [OP; P]"),
       ("O2", "merge of O3+O4+O6+O7+O8", "Each turn assess whether the "
        "request is fully satisfied, whether the team is looping (including "
        "repeated scrolling) and whether progress is being made; treat a "
        "lack of progress as a stall and re-plan from its root cause with an "
        "updated fact sheet; consider the request satisfied only if "
        "SUCCESSFULLY and FULLY addressed; and at the end report a final "
        "answer from the transcript, or the best educated guess. [OP; P]")]

SETS = {
    "nbal": dict(
        name="N-BAL (balanced: 3 rules per agent)",
        summary="Balanced set: exactly 3 rules for each of the five roles "
                "(15 total). Built for the rule-count experiment, to test "
                "whether blame follows specification density or role "
                "centrality.",
        agents={
            "Orchestrator": [
                ("O1", "merge of O1+O2", "Before planning, survey the facts "
                 "(given or verified, to look up and where, to derive, "
                 "educated guesses), then devise a short step-by-step plan "
                 "assigning steps to members of the assembled team only. "
                 "[OP; P]"),
                ("O2", "merge of O3+O4+O5", "Each turn, assess whether the "
                 "request is fully satisfied — only SUCCESSFULLY and FULLY "
                 "addressed counts — whether the team is in a loop, and "
                 "whether progress is being made; then name the next speaker "
                 "with an instruction that includes what it needs. [OP]"),
                ("O3", "merge of O6+O7+O8", "Treat repeated requests or "
                 "responses as a loop and a lack of progress as a stall; "
                 "when stalled, re-plan from the root cause with an updated "
                 "fact sheet; and at the end report a final answer from the "
                 "full transcript, or the best educated guess. [OP; P]")],
            "WebSurfer": [
                ("W1", "W1", "Map each request to a single action from the "
                 "action space: navigation (visit a URL, web search, "
                 "scroll), page actions (click, type), or reading "
                 "(summarize, answer questions). [P]"),
                ("W2", "W3", "Choose the action by where the needed "
                 "information is: the current viewport (click, type, hover), "
                 "elsewhere on the current page (scroll, summarize, "
                 "full-page Q&A), or another website (a new web search). "
                 "[WP tool prompt]"),
                ("W3", "merge of W2+W4", "After acting, report the new state "
                 "of the page, and base any summary or answer on the content "
                 "of the page. [P; D; WP]")],
            "FileSurfer": [
                ("F1", "split of F1 (a)", "Operate read-only: never modify a "
                 "file. [P; D; FP]"),
                ("F2", "split of F1 (b)", "Read local files of the requested "
                 "type, and list directory contents and navigate the folder "
                 "structure when asked. [P; D; FP]"),
                ("F3", "F2", "Report what the file or directory contains. "
                 "[inferred in v1]")],
            "Coder": [
                ("C1", "merge of C1+C3", "When code is needed, provide it in "
                 "a single python or sh block, state the script type, use "
                 "print for output, and do not ask for results to be copied "
                 "and pasted. [CP]"),
                ("C2", "merge of C2+C5", "Provide complete code that runs "
                 "without modification — the full code, not partial code or "
                 "changes — and when no plan was given, explain the plan "
                 "first, making clear which steps use code. [CP]"),
                ("C3", "merge of C4+C6", "Check the execution result: fix "
                 "errors and output the full code again, or revisit "
                 "assumptions and try a different approach; verify any "
                 "answer and include verifiable evidence. [CP]")],
            "ComputerTerminal": [
                ("T1", "split of T1 (a)", "Execute the Coder's programs. "
                 "[P; D]"),
                ("T2", "split of T1 (b)", "Run shell commands, including "
                 "installing libraries. [P; D]"),
                ("T3", "T2", "Return the console output as produced, without "
                 "altering it. [inferred in v1]")]}),
    "norch": dict(
        name="N-ORCH (orchestrator-heavy: 8 Orchestrator rules, 2 each "
             "elsewhere)",
        summary="Orchestrator-heavy set: v1's 8 Orchestrator rules "
                "unchanged, every other role merged down to 2 (16 total).",
        agents={"Orchestrator": O_8, "WebSurfer": W_2, "FileSurfer": F_2,
                "Coder": C_2, "ComputerTerminal": T_2}),
    "nweb": dict(
        name="N-WEB (websurfer-heavy: 8 WebSurfer rules, 2 each elsewhere)",
        summary="WebSurfer-heavy set: v1's 4 WebSurfer rules split to 8 "
                "along the action space the paper enumerates, every other "
                "role merged down to 2 (16 total).",
        agents={
            "Orchestrator": O_2,
            "WebSurfer": [
                ("W1", "split of W1 (a)", "Respond to each request with "
                 "exactly one action; do not combine several. [P]"),
                ("W2", "split of W1 (b), navigation", "Use navigation "
                 "actions — visiting a URL, performing a web search, or "
                 "scrolling within a page — when the request calls for "
                 "them. [P]"),
                ("W3", "split of W1 (c), page actions", "Use page actions — "
                 "clicking and typing — when the request calls for them. "
                 "[P]"),
                ("W4", "split of W1 (d), reading actions", "Use reading "
                 "actions — summarizing the page, or answering a question "
                 "about it — when the request calls for them. [P]"),
                ("W5", "W2", "After acting, report the new state of the web "
                 "page. [P; D]"),
                ("W6", "split of W3 (a)", "If the needed information is in "
                 "the current viewport, act there: click, type or hover. "
                 "[WP tool prompt]"),
                ("W7", "split of W3 (b)", "If it is elsewhere on the current "
                 "page, scroll, summarize, or answer over the full page; if "
                 "it is on another website, perform a new web search. "
                 "[WP tool prompt]"),
                ("W8", "W4", "When summarizing or answering, base the answer "
                 "on the content of the page. [WP description; P]")],
            "FileSurfer": F_2, "Coder": C_2, "ComputerTerminal": T_2}),
}
ORDER = ["Orchestrator", "WebSurfer", "FileSurfer", "Coder",
         "ComputerTerminal"]


def render(spec, v1sha):
    out = [HEAD.format(name=spec["name"], summary=spec["summary"],
                       v1sha=v1sha[:12] + "…")]
    for ag in ORDER:
        rules = spec["agents"][ag]
        out.append(f"## {ag}\n\nRULES:")
        for rid, _src, text in rules:
            body = text
            out.append(f"- {rid}. {body}")
        out.append("")
    out.append("## Derivation from v1\n")
    out.append("| rule | from v1 | operation |")
    out.append("|---|---|---|")
    for ag in ORDER:
        for rid, src, _ in spec["agents"][ag]:
            op = ("verbatim" if src == rid and "of" not in src else
                  "merge" if src.startswith("merge") else
                  "split" if src.startswith("split") else "verbatim")
            out.append(f"| {ag} {rid} | {src} | {op} |")
    counts = {ag: len(spec["agents"][ag]) for ag in ORDER}
    out.append("")
    out.append(f"Rules per agent: {counts}; total {sum(counts.values())}.")
    return "\n".join(out) + "\n"


def main():
    v1 = verify_norms("v1")
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for ver, spec in SETS.items():
        text = render(spec, v1["sha256"])
        b = text.encode("utf-8")
        with open(norms_path(ver), "xb") as f:      # binary: no CRLF rewrite
            f.write(b)
        lock = {"file": f"faultattr/norms/{os.path.basename(norms_path(ver))}",
                "sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b),
                "frozen_at": stamp,
                "derived_from_sha256": v1["sha256"],
                "edit": spec["name"],
                "post_hoc": True,
                "prereg": "results/PREREG_rulecount_20261002.md",
                "note": "Granularity-only derivation from v1 (merge/split); "
                        "no new obligations. See the file's derivation "
                        "table."}
        with open(lock_path(ver), "x", encoding="utf-8") as f:
            json.dump(lock, f, indent=2)
        n = len(re.findall(r"^- \w\d\.", text, re.M))
        print(f"{ver}: {n} rules, sha256 {lock['sha256'][:12]}")
        verify_norms(ver)


if __name__ == "__main__":
    main()
