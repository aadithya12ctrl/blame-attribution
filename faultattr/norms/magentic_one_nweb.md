# Magentic-One agent norms — N-WEB (websurfer-heavy: 8 WebSurfer rules, 2 each elsewhere)

WebSurfer-heavy set: v1's 4 WebSurfer rules split to 8 along the action space the paper enumerates, every other role merged down to 2 (16 total).

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
- O1. Survey the facts (given or verified, to look up, to derive, educated guesses), devise a short plan that assigns steps to the assembled team only, and each turn name the next speaker with an instruction that includes the information it needs. [OP; P]
- O2. Each turn assess whether the request is fully satisfied, whether the team is looping (including repeated scrolling) and whether progress is being made; treat a lack of progress as a stall and re-plan from its root cause with an updated fact sheet; consider the request satisfied only if SUCCESSFULLY and FULLY addressed; and at the end report a final answer from the transcript, or the best educated guess. [OP; P]

## WebSurfer

RULES:
- W1. Respond to each request with exactly one action; do not combine several. [P]
- W2. Use navigation actions — visiting a URL, performing a web search, or scrolling within a page — when the request calls for them. [P]
- W3. Use page actions — clicking and typing — when the request calls for them. [P]
- W4. Use reading actions — summarizing the page, or answering a question about it — when the request calls for them. [P]
- W5. After acting, report the new state of the web page. [P; D]
- W6. If the needed information is in the current viewport, act there: click, type or hover. [WP tool prompt]
- W7. If it is elsewhere on the current page, scroll, summarize, or answer over the full page; if it is on another website, perform a new web search. [WP tool prompt]
- W8. When summarizing or answering, base the answer on the content of the page. [WP description; P]

## FileSurfer

RULES:
- F1. Operate read-only. Read local files of the requested type, list directory contents, and navigate the folder structure. [P; D; FP]
- F2. Report what the file or directory contains. [inferred in v1 from P's 'very similar to the WebSurfer']

## Coder

RULES:
- C1. When code is needed, provide it in a single python or sh block, state the script type, make it complete and runnable without modification (full code, not partial), use print for output rather than asking for copy-paste, and explain the plan first when none was given. [CP]
- C2. Check the execution result: on an error, fix it and output the full code again; if it cannot be fixed, revisit assumptions and try a different approach. When an answer is found, verify it and include verifiable evidence. [CP]

## ComputerTerminal

RULES:
- T1. Execute the Coder's programs and shell commands (including installing libraries) and return the console output. [P; D]
- T2. Report execution results as produced, without altering them. [inferred in v1]

## Derivation from v1

| rule | from v1 | operation |
|---|---|---|
| Orchestrator O1 | merge of O1+O2+O5 | merge |
| Orchestrator O2 | merge of O3+O4+O6+O7+O8 | merge |
| WebSurfer W1 | split of W1 (a) | split |
| WebSurfer W2 | split of W1 (b), navigation | split |
| WebSurfer W3 | split of W1 (c), page actions | split |
| WebSurfer W4 | split of W1 (d), reading actions | split |
| WebSurfer W5 | W2 | verbatim |
| WebSurfer W6 | split of W3 (a) | split |
| WebSurfer W7 | split of W3 (b) | split |
| WebSurfer W8 | W4 | verbatim |
| FileSurfer F1 | F1 | verbatim |
| FileSurfer F2 | F2 | verbatim |
| Coder C1 | merge of C1+C2+C3+C5 | merge |
| Coder C2 | merge of C4+C6 | merge |
| ComputerTerminal T1 | T1 | verbatim |
| ComputerTerminal T2 | T2 | verbatim |

Rules per agent: {'Orchestrator': 2, 'WebSurfer': 8, 'FileSurfer': 2, 'Coder': 2, 'ComputerTerminal': 2}; total 16.
