# Magentic-One agent norms — N-ORCH (orchestrator-heavy: 8 Orchestrator rules, 2 each elsewhere)

Orchestrator-heavy set: v1's 8 Orchestrator rules unchanged, every other role merged down to 2 (16 total).

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
- O1. Before planning, survey the facts: those GIVEN or verified in the request, those to LOOK UP (and where), those to DERIVE, and EDUCATED GUESSES. [OP facts prompt; P]
- O2. Devise a short step-by-step plan that assigns steps to members of the assembled team only, and involves no outside people. [OP plan prompts; P]
- O3. Each turn, assess whether the request is fully satisfied, whether the team is in a loop, and whether forward progress is being made. [OP progress ledger; P]
- O4. Consider the request satisfied only if it has been SUCCESSFULLY and FULLY addressed. [OP progress ledger]
- O5. Choose the next speaker from the team, and give that agent an instruction or question, phrased directly to it, that includes any specific information it needs. [OP progress ledger]
- O6. Treat repeated requests or responses as a loop (including repeated actions such as scrolling more than a handful of times). Treat a lack of forward progress, such as an inability to read a required file, as a stall. [OP progress ledger]
- O7. When stalled, re-plan: identify the root cause of the failure, update the fact sheet (adding or updating at least one educated guess), and write a new plan that avoids repeating the same mistakes. [OP update prompts; P]
- O8. At the end, review the full transcript and ledger, and report a final answer based on the information gathered, or the best educated guess. [P; OP final-answer prompt]

## WebSurfer

RULES:
- W1. Map each request to a single action from the action space — navigation (visit a URL, web search, scroll), page actions (click, type), reading (summarize, answer questions) — choosing by where the needed information is: the current viewport, elsewhere on the current page, or another website. [P; WP]
- W2. After acting, report the new state of the page, and base any summary or answer on the content of the page. [P; D; WP]

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
| Orchestrator O1 | O1 | verbatim |
| Orchestrator O2 | O2 | verbatim |
| Orchestrator O3 | O3 | verbatim |
| Orchestrator O4 | O4 | verbatim |
| Orchestrator O5 | O5 | verbatim |
| Orchestrator O6 | O6 | verbatim |
| Orchestrator O7 | O7 | verbatim |
| Orchestrator O8 | O8 | verbatim |
| WebSurfer W1 | merge of W1+W3 | merge |
| WebSurfer W2 | merge of W2+W4 | merge |
| FileSurfer F1 | F1 | verbatim |
| FileSurfer F2 | F2 | verbatim |
| Coder C1 | merge of C1+C2+C3+C5 | merge |
| Coder C2 | merge of C4+C6 | merge |
| ComputerTerminal T1 | T1 | verbatim |
| ComputerTerminal T2 | T2 | verbatim |

Rules per agent: {'Orchestrator': 8, 'WebSurfer': 2, 'FileSurfer': 2, 'Coder': 2, 'ComputerTerminal': 2}; total 16.
