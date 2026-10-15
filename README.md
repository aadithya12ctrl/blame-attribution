# Fault attribution harness

Five prompt-based text agents on OpenRouter, with contract evaluation and the
four-way verdict classification.

## Setup

```bash
export OPENROUTER_API_KEY=sk-or-...        # never put this in a file
export FA_MODEL=anthropic/claude-haiku-4.5 # or any OpenRouter model id
                                           # (claude-3.5-haiku now 404s)
```

Standard library only — no dependencies.

## Run in this order

```bash
# 0. offline sanity check, no API calls, no key needed
FA_MOCK=1 python3 experiments/exp_cases.py

# 1. projection accuracy. DO THIS FIRST on any new model.
python3 experiments/exp_epsilon.py --n 30

# 2. the seeded case table
python3 experiments/exp_cases.py

# 3. the flinch hypothesis
python3 experiments/exp_flinch.py --k 5 --seeds 4
```

Step 1 first is not a formality. If `eps` is high, the union bound `2nk·eps`
goes vacuous and nothing in steps 2–3 is interpretable. Zero observed errors
is not `eps = 0`: the script reports the rule-of-three bound `3/N` instead,
and at small `N` that bound is itself vacuous.

**A flat activation curve means the flinch test is void, not negative.**
`exp_flinch.py` prints the planner fault rate by `tau` before the `psi`
table. If faults do not rise with `tau`, then `tau*(alpha)` is not estimable,
there is no threshold for any `psi` to anticipate, and "no candidate passes"
says nothing about Hypothesis 10.2. Report it as untestable on that domain.

## Fixed in v2

| | Change | Effect on v1 results |
|---|---|---|
| 1 | Block extraction anchors markers to line starts, tries candidates last-to-first; every `project_*` raises `ProjectionError` instead of returning empty; such runs get `UNATTRIBUTABLE_PROJECTION_FAILURE` and are excluded from fault statistics | v1 turned parse failures into `AGENT_FAULT {planner}` (`"no parseable plan"`). Live, ~12.5% of planner samples failed to parse and 4 of 8 flinch-sweep planner faults co-occurred with parse failure; live scenario A was one of these. Those faults were not agent faults |
| 2 | Parse-failure rate measured for all five agents; bound uses `max(observer value error, worst parse rate)`; rule-of-three when zero | v1 reported `eps = 0.0000` from the observer alone (0/641), the one stage with rigid output. The stage that actually failed was unmeasured, so the reported bound did not cover attribution |
| 3 | Arms labelled at generation; `analyse()` selects by label and asserts disjointness; arm 2 uses its own seed block at `tau = 0.3` | v1 put the shared `tau=0, delta=0` cell (8 rows) in both regressions, double-weighting the endpoint. `psi_hedge` `effect_tau` moved from +0.080 to +0.014 on that alone |
| 4 | Blocked slots scale with `tau` (`round(2·tau·n_jobs)`) and are spread evenly with jitter | v1 fault rate was flat in `tau` (1/8, 0, 0, 1/4, 0, 1/4) and rising in `delta` (3/4 at `delta=3`), so v1's "no candidate passes" was void, not negative. Mock now: 0/16 faults for `tau ≤ 0.6`, 3/16 at 0.8, 9/16 at 0.95, 0/16 at every `delta` |
| 5 | `build_corpus(dead_frac=…)`; `exp_cases.py` prints a corpus-sensitivity section | v1's clean-only corpus made scenario D `REPAIRABLE` by construction. With 75% dead-sensor corpus runs the same run is `CORPUS_BLOCKED`; E is stable |

Side effect of 4: at `tau = 0.3` there are now two blocked slots, so in
scenarios A and C the injected planner shift lands on a blocked slot
(`covers unavailable slot`) instead of producing a separation violation. The
verdicts are unchanged and it is still a direct violation of a stated
guarantee, but the table no longer shows a separation violation specifically.

## Rule: infrastructure failures are never scored as model behaviour

An API error, an HTTP 429, a timeout, or a reply truncated at `max_tokens`
(`finish_reason = "length"`) says nothing about what the model would have
answered. Such a run is **excluded and logged with its reason**. It is never
counted as a fault, a wrong answer, a parse failure (ε), or a background
fault. Where a table has a denominator, the excluded runs are reported next to
it, not inside it.

This project made the same mistake twice before the rule was written down:

1. **Parse failures scored as faults (v1).** A planner reply the parser could
   not read became an empty plan, which the contracts scored as
   `AGENT_FAULT {planner}`. Fixed by `ProjectionError` and
   `UNATTRIBUTABLE_PROJECTION_FAILURE`.
2. **API errors scored as projection failures (screening).** A call rejected
   with HTTP 429 returned empty text, which the screen counted as 65
   "projection failures" and scored the model on. Fixed by counting API
   errors separately and reporting such a model as NOT MEASURED.

Both had the same shape: a missing observation filled with a default, and the
default then evaluated as if the model had produced it. Any new code path that
substitutes a default for missing output must mark it, and every scorer must
check that mark first. Check order: API error → truncation → projection
failure → only then contracts.

## Repository layout

```
.
|-- faultattr/           the harness itself (import package)
|   `-- norms/           frozen Magentic-One norm sets + their hash locks
|-- experiments/         runnable entry points, one per experiment
|-- data/
|   `-- who_and_when/    Who&When subset, downloaded on first use (not in git)
|-- results/             every run's outputs, prereg locks and NOTE_*.md
|-- docs/                the framework write-up
|-- paper/               paper source (bibliography.bib, .tex)
|-- epsilon.json         Phase 1 (v1) live outputs. Kept at root
|-- flinch.csv           because results/README.md and
`-- flinch_analysis.json SESSION_REPORT.md cite them by that path
```

`faultattr/` and `experiments/` must stay directly under the repository root:
each script resolves `ROOT` as its own parent directory and then reaches for
`faultattr/norms`, `data/who_and_when` and `results/` relative to it. Moving
either one, or introducing a `src/` layer, breaks those lookups.

`data/who_and_when/` is **not** in git. The Who&When Hand-Crafted subset
carries no declared licence on HuggingFace, and because the benchmark's agents
browsed live pages its records embed third-party personal data, so this
repository does not redistribute it. `faultattr/whowhen.py` downloads the 58
cases on first use and hash-checks each one, so nothing is lost:

```bash
py -c "import sys; sys.path.insert(0,'.'); from faultattr.whowhen import *; load_hand_crafted(verify_norms('v1'))"
```

`_download.json` is ignored along with the payload, deliberately:
`load_hand_crafted()` skips the download whenever that file is present, so
shipping it without the case files would make a fresh clone fail. The record
it holds — source URL, per-case sha256, and the timestamps that make the
"norms frozen before data downloaded" ordering checkable — is committed
separately as `results/PROVENANCE_who_and_when_download.json`, which no code
path reads.

## Files

| File | What it is |
|---|---|
| `faultattr/domain.py` | Task generation by margin `tau` and difficulty `delta`; the requirement `R`; scalar margin and its linear decomposition |
| `faultattr/agents.py` | The five agents, their prompts, and the fault injectors |
| `faultattr/projection.py` | Text → typed state (raises `ProjectionError` on failure), and the `eps` measurement |
| `faultattr/contracts.py` | `P` and `G` as executable predicates |
| `faultattr/attribute.py` | Fault set `Phi` and the four-way verdict |
| `faultattr/mockagents.py` | Deterministic scripted agents for `FA_MOCK=1` |

## The five seeded scenarios

`exp_cases.py` runs these. Verified in mock mode.

| | Scenario | Expected verdict | What it isolates |
|---|---|---|---|
| A | planner violates separation | `AGENT_FAULT {planner}` | baseline — everything gets this |
| B | observer reports a busy slot free | `AGENT_FAULT {observer}` | LLM judges blame the planner here |
| C | planner + validator + executor all fail | `AGENT_FAULT {3 agents}` | counterfactual methods return nobody |
| D | sensor emits nothing (dead) | `REPAIRABLE [D1]`, 2 repairs | no method can say "no agent" |
| E | sensor reports a busy slot free (lying) | `INEXPRESSIBLE` | nothing observable distinguishes it |

D's verdict depends on the corpus: `REPAIRABLE` against a clean-only corpus,
`CORPUS_BLOCKED` once the corpus contains successful dead-sensor runs.
`exp_cases.py` prints both. Report corpus composition with any D verdict.

D and E are the interesting pair. Both have every contract satisfied and the
system failing. They differ in whether any agent *could* have caught it: in D
the gap is visible as `UNKNOWN`, so a repair exists; in E the false reading is
indistinguishable from a true one, so no expressible repair exists and the
verdict is an instrumentation gap.

## What this does NOT do

**The repair search is a stub.** `_candidate_repairs` checks a hand-written
catalogue of three candidate strengthenings. Enumerating `max_⊑ Rep` properly
is unsolved (gap 1), and the catalogue is enough to separate the verdict
classes on seeded scenarios and nothing more. Do not report it as a repair
algorithm.

**D2 (tolerance stack-up) is not demonstrated.** Both D-type scenarios come out
as D1. A genuine stack-up needs every agent conformant while legitimately
spending margin, and in this domain the planner's guarantee enforces separation
directly, so there is little legitimate slack to spend. Either build a domain
with soft per-agent allowances, or report that D2 is untested.

**Downstream value errors are unmeasured.** Parse failures are measured at
every stage. But a parse that succeeds with the wrong value can only be caught
where ground truth is independent of the agent, and that is the observer
alone. Downstream value error is real and unmeasured.

**Mock mode proves nothing about models.** It exercises the evaluator and the
verdict logic. Every empirical claim must come from real runs.

## Contract authoring, and case E

`contracts.py` has a flag:

```python
ANALYZER_VALIDATES_INPUT = False
```

This decides whether the analyzer is obliged to notice implausible input, or
may assume its input is faithful. Flip it and scenario B's verdict changes from
`{observer}` to `{observer, analyzer}`.

Neither setting is correct. The point is that the choice is written down,
visible, and arguable — instead of being made silently and differently by
whoever is annotating that day.

## Cost

`exp_flinch.py --k 5 --seeds 4` is roughly `6 taus × 4 seeds × 5 samples` plus
`4 deltas × 4 seeds × 5 samples` planner calls, plus five pipeline calls per
configuration. Budget around 700–900 calls. Start with `--k 2 --seeds 2` to
check the plumbing against a real model before committing.
## Licence

The code, documentation and paper source in this repository are MIT licensed
(see `LICENSE`).

That does not extend to the benchmark material. `results/` contains excerpts
of Who&When failure traces (under `audit_histories/`, `label_audit.csv` and
the `abstention_*` sheets) reproduced for audit, and those traces are the work
of Zhang et al. (ICML 2025) and of the sites their agents browsed. The dataset
itself is not redistributed here. Cite the benchmark, not this repository, as
the source of that material.
