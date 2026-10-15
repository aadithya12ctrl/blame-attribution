# Magentic-One agent norms — N-BAL (balanced: 3 rules per agent)

Balanced set: exactly 3 rules for each of the five roles (15 total). Built for the rule-count experiment, to test whether blame follows specification density or role centrality.

Derived from the frozen v1 norms (`faultattr/norms/magentic_one.md`, sha256
dab067b8f8d2…) by changing RULE GRANULARITY ONLY: adjacent v1 rules merged, or a
v1 rule split along an enumeration already present in the cited
documentation. No new obligation is introduced and no rule is worded to
describe a failure mode. Sources are v1's: [P] arXiv:2411.04468v1,
[D] AutoGen Magentic-One docs, [OP] orchestrator prompts, [CP] coder system
message, [WP] web-surfer description and tool prompt, [FP] file-surfer
description. The derivation table at the end gives rule-by-rule provenance.

Frozen after the Who&When pilot, for the rule-count experiment
pre-registered in `results/PREREG_rulecount_20261002.md`.

## Orchestrator

RULES:
- O1. Before planning, survey the facts (given or verified, to look up and where, to derive, educated guesses), then devise a short step-by-step plan assigning steps to members of the assembled team only. [OP; P]
- O2. Each turn, assess whether the request is fully satisfied — only SUCCESSFULLY and FULLY addressed counts — whether the team is in a loop, and whether progress is being made; then name the next speaker with an instruction that includes what it needs. [OP]
- O3. Treat repeated requests or responses as a loop and a lack of progress as a stall; when stalled, re-plan from the root cause with an updated fact sheet; and at the end report a final answer from the full transcript, or the best educated guess. [OP; P]

## WebSurfer

RULES:
- W1. Map each request to a single action from the action space: navigation (visit a URL, web search, scroll), page actions (click, type), or reading (summarize, answer questions). [P]
- W2. Choose the action by where the needed information is: the current viewport (click, type, hover), elsewhere on the current page (scroll, summarize, full-page Q&A), or another website (a new web search). [WP tool prompt]
- W3. After acting, report the new state of the page, and base any summary or answer on the content of the page. [P; D; WP]

## FileSurfer

RULES:
- F1. Operate read-only: never modify a file. [P; D; FP]
- F2. Read local files of the requested type, and list directory contents and navigate the folder structure when asked. [P; D; FP]
- F3. Report what the file or directory contains. [inferred in v1]

## Coder

RULES:
- C1. When code is needed, provide it in a single python or sh block, state the script type, use print for output, and do not ask for results to be copied and pasted. [CP]
- C2. Provide complete code that runs without modification — the full code, not partial code or changes — and when no plan was given, explain the plan first, making clear which steps use code. [CP]
- C3. Check the execution result: fix errors and output the full code again, or revisit assumptions and try a different approach; verify any answer and include verifiable evidence. [CP]

## ComputerTerminal

RULES:
- T1. Execute the Coder's programs. [P; D]
- T2. Run shell commands, including installing libraries. [P; D]
- T3. Return the console output as produced, without altering it. [inferred in v1]

## Derivation from v1

| rule | from v1 | operation |
|---|---|---|
| Orchestrator O1 | merge of O1+O2 | merge |
| Orchestrator O2 | merge of O3+O4+O5 | merge |
| Orchestrator O3 | merge of O6+O7+O8 | merge |
| WebSurfer W1 | W1 | verbatim |
| WebSurfer W2 | W3 | verbatim |
| WebSurfer W3 | merge of W2+W4 | merge |
| FileSurfer F1 | split of F1 (a) | split |
| FileSurfer F2 | split of F1 (b) | split |
| FileSurfer F3 | F2 | verbatim |
| Coder C1 | merge of C1+C3 | merge |
| Coder C2 | merge of C2+C5 | merge |
| Coder C3 | merge of C4+C6 | merge |
| ComputerTerminal T1 | split of T1 (a) | split |
| ComputerTerminal T2 | split of T1 (b) | split |
| ComputerTerminal T3 | T2 | verbatim |

Rules per agent: {'Orchestrator': 3, 'WebSurfer': 3, 'FileSurfer': 3, 'Coder': 3, 'ComputerTerminal': 3}; total 15.
