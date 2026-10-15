# Magentic-One agent norms (frozen)

> VARIANT v2: identical to v1 (sha256 dab067b8f8d2...) except: rules O4 and O8 removed (ABL-2). Frozen AFTER the pilot, at the user's specification; not derived from reading failure records.

Written ONLY from Magentic-One's public documentation, before any Who&When
failure record was read. Each rule cites its source. A rule marked
"(inferred)" is not stated verbatim; the inference is given. This file is
hashed at freeze time. `experiments/exp_whowhen.py` refuses to run if the
file has changed since then, or if the Who&When data was downloaded before
the freeze.

## Sources (fetched 2026-09-22)

- [P] Fourney et al., "Magentic-One: A Generalist Multi-Agent System for
  Solving Complex Tasks", arXiv:2411.04468v1 (7 Nov 2024),
  https://arxiv.org/html/2411.04468v1 — agent descriptions (sec. 3).
- [D] AutoGen documentation, "Magentic-One",
  https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html
- [OP] Orchestrator prompts, microsoft/autogen `main`,
  python/packages/autogen-agentchat/src/autogen_agentchat/teams/_group_chat/_magentic_one/_prompts.py
- [CP] Coder system message, microsoft/autogen `main`,
  python/packages/autogen-ext/src/autogen_ext/agents/magentic_one/_magentic_one_coder_agent.py
- [WP] WebSurfer description and tool prompt, microsoft/autogen `main`,
  python/packages/autogen-ext/src/autogen_ext/agents/web_surfer/_multimodal_web_surfer.py and _prompts.py
- [FP] FileSurfer description, microsoft/autogen `main`,
  python/packages/autogen-ext/src/autogen_ext/agents/file_surfer/_file_surfer.py

Caveat: [OP], [CP], [WP] and [FP] are the current AutoGen implementation. The
Who&When logs were produced by an earlier Magentic-One release, whose prompts
may differ in wording. [P] is the version-independent specification.

---

## Orchestrator

RULES:
- O1. Before planning, survey the facts: those GIVEN or verified in the
  request, those to LOOK UP (and where), those to DERIVE, and EDUCATED
  GUESSES. [OP facts prompt; P]
- O2. Devise a short step-by-step plan that assigns steps to members of the
  assembled team only, and involves no outside people. [OP plan prompts; P]
- O3. Each turn, assess whether the request is fully satisfied, whether the
  team is in a loop, and whether forward progress is being made. [OP
  progress ledger; P]
- O5. Choose the next speaker from the team, and give that agent an
  instruction or question, phrased directly to it, that includes any specific
  information it needs. [OP progress ledger]
- O6. Treat repeated requests or responses as a loop (including repeated
  actions such as scrolling more than a handful of times). Treat a lack of
  forward progress, such as an inability to read a required file, as a
  stall. [OP progress ledger]
- O7. When stalled, re-plan: identify the root cause of the failure, update
  the fact sheet (adding or updating at least one educated guess), and write
  a new plan that avoids repeating the same mistakes. [OP update prompts; P]

## WebSurfer

RULES:
- W1. Map each request to a single action from its action space: navigation
  (visit a URL, web search, scroll), page actions (click, type), or reading
  actions (summarize, answer questions about the page). [P]
- W2. After acting, report the new state of the web page. [P; D]
- W3. Choose the action by where the needed information is: in the current
  viewport (click, type, hover), elsewhere on the current page (scroll,
  summarize, full-page Q&A), or on another website (a new web search). [WP
  tool prompt]
- W4. When summarizing or answering, base the answer on the content of the
  page. [WP description; P]

## FileSurfer

RULES:
- F1. Operate read-only. Read local files of the requested type, list
  directory contents, and navigate the folder structure. [P; D; FP]
- F2. (inferred) Report what the file or directory contains. Inference: [P]
  describes FileSurfer as "very similar to the WebSurfer", which reports the
  new state after each action (W2).

## Coder

RULES:
- C1. When information must be collected or a task performed with code,
  provide the code in a python or sh code block, and state the script
  type. [CP]
- C2. Provide complete code that runs without modification. Suggest the full
  code, not partial code or code changes. [CP]
- C3. Put only one code block in a response. Use print for output, and do
  not ask the user to copy and paste results. [CP]
- C4. Check the execution result. On an error, fix it and output the full
  code again. If the error can't be fixed, or the task is still unsolved,
  analyze the problem, revisit assumptions, collect more information, and try
  a different approach. [CP]
- C5. If no plan is provided, explain the plan first, and make clear which
  steps use code and which use language skills. [CP]
- C6. When an answer is found, verify it carefully and include verifiable
  evidence where possible. [CP]

## ComputerTerminal

RULES:
- T1. Execute the Coder's programs and shell commands (including installing
  libraries) and return the console output. [P; D]
- T2. (inferred) Report execution results as produced, without altering
  them. Inference: [P] and [D] define the terminal only as the place "where
  the Coder's programs can be executed"; it is not an LLM agent and has no
  other role.
