# Results — fault-attribution harness

Every experiment run in this project, in order: what was run, on which model,
provider and prompt, the numbers, what they mean, and what remains open.

- For the framework itself, see `../docs/fault-attribution-consolidated-v2.md`.
- For the harness code and how to run it, see `../README.md`.
- The running findings log is `NOTE_prompt_v2_20260922.md`.

**Status:** all experiments below are complete. The hand labels for the
natural condition (§7.3) have **not** been collected, so every claim about
attribution *accuracy* on real agents is still open.

---

## Contents

1. [Headline findings](#1-headline-findings)
2. [Setup and conventions](#2-setup-and-conventions)
3. [Phase 1 — the original harness on Claude Haiku 4.5](#3-phase-1--the-original-harness-v1-on-claude-haiku-45)
4. [Phase 2 — harness fixes and the margin accounting](#4-phase-2--harness-fixes-and-the-margin-accounting)
5. [Phase 3 — the fixed harness on Claude Haiku 4.5](#5-phase-3--the-fixed-harness-on-claude-haiku-45)
6. [Phase 4 — choosing an agent model](#6-phase-4--choosing-an-agent-model)
7. [Phase 5 — LLM-as-judge baseline](#7-phase-5--llm-as-judge-baseline)
7b. [Phase 6 — Who&When Hand-Crafted pilot](#7b-phase-6--whowhen-hand-crafted-pilot)
8. [Rules adopted along the way](#8-rules-adopted-along-the-way)
9. [Open problems](#9-open-problems)
10. [Cost](#10-cost)
11. [File index](#11-file-index)

---

## 1. Headline findings

1. **The seeded case table (A–E) is reproducible.** It came out the same in
   mock, on Claude Haiku 4.5 twice, and on deterministic agents. That includes
   the D/E contrast the framework cares most about: a fixable missing rule
   (D) vs an instrumentation gap no rule can fix (E).

2. **An LLM judge given the norms matches the contract evaluator on clean
   traces.** A judge that sees the agents' written rules *and* may answer
   "no agent" (condition J-P-N) scored 8/8 on B, D and E. By the criterion
   set in advance, **the supported claim is the narrower one**: on these
   cases the evaluator's contribution is formalizing norms that a judge could
   already use. Both ingredients are needed. Without norms or without
   permission to answer "none", the judge fails D and E.

3. **On real-agent traces the judge agrees with the evaluator 25/26 (J-P-N).**
   That agreement survives removing the validator's stated reasons (17/18 →
   18/18), so the judge is not reading the answer off the trace. Agreement is
   not accuracy: the hand labels are still pending.

4. **The disagreements found so far are obligations missing from the
   contract set, not attribution errors.** An orchestrator forwarding
   rejected plans, a validator stating the wrong reason, and no replanning
   after a rejection: none of these is covered by a contract. This is
   *provisional* until the hand labels are in.

5. **Five harness bugs would each have produced false results.**
   Parse failures scored as agent faults; ε measured only where it couldn't
   fail; overlapping regression arms; API errors scored as model behaviour;
   and an orchestrator that forwarded rejected plans. All five are fixed, and
   the rule behind the parse and API fixes is now in the README (§8).

6. **The flinch hypothesis (10.2) was never testable, so it is void, not
   negative.** Faults did not rise with the margin parameter τ on any live
   model. On Haiku, high-τ planner replies were cut off at the token limit
   before a plan appeared, so the activation curve was censored exactly where
   faults would show.

7. **On an external benchmark every norms arm lost to the published
   baseline.** On Who&When's 58 Hand-Crafted cases, All-at-Once scored
   0.439 agent / 0.211 step, against 0.345 / 0.190 for the best of four
   norms arms and 0.224–0.310 for the rest. The answer key had little and
   mixed effect in both rows. Confounded: the norms arms also change verdict
   space and output format.

8. **Written norms concentrate blame on the most CENTRAL agent, not the most
   heavily specified one.** Rule count was manipulated directly (3 each /
   8 Orchestrator / 8 WebSurfer): with only 2 rules the Orchestrator still
   took **77%** of answers, while WebSurfer with 8 took **19%**, its lowest
   share, and that arm had the worst agent accuracy (0.207). The earlier
   "specification density" reading is **refuted**. Rule count instead moves
   coverage: more rules on a peripheral agent produced more **abstention**
   (24 of 58), not more blame.

9. **Non-reasoning instruct models misread the separation rule.** Under the
   original prompt, 32/32 violations by three models were off by exactly one
   slot (gap = 1). A clarified prompt (v2) reduced this, but no candidate
   model reached the 7/8 clean-run bar.

---

## 2. Setup and conventions

**Domain.** N jobs are scheduled on one shared resource over T slots, with
some slots blocked. The requirement R: every job scheduled once, no overlap,
≥ 2 empty slots between consecutive jobs (`SEP_MIN`), no job on an occupied
slot, everything within the horizon.

**Pipeline.** observer → analyzer → planner → validator → executor. Each is an
LLM agent with a written RULES block (its norm) and a contract (P, G) that the
evaluator checks.

**Seeded scenarios.**

| | scenario | how it's seeded | expected verdict |
|---|---|---|---|
| A | direct violation | planner output squeezed below `SEP_MIN` | AGENT_FAULT {planner} |
| B | inherited drift | observer reports a busy slot as free | AGENT_FAULT {observer} |
| C | overdetermination | planner, validator and executor all corrupted | AGENT_FAULT {planner, validator, executor} |
| D | missing obligation | dead sensor: a busy slot emits nothing | REPAIRABLE [D1], 2 repairs |
| E | inexpressible | lying sensor: a busy slot reports free | INEXPRESSIBLE |

**Verdict classes.** `AGENT_FAULT`, `REPAIRABLE_INADEQUACY`, `CORPUS_BLOCKED`,
`INEXPRESSIBLE`, and — added during this work — `UNATTRIBUTABLE_PROJECTION_FAILURE`
for runs whose text could not be parsed.

**Terms used below.**

- **ε (eps)** — projection error rate: how often agent text fails to parse, or
  parses to the wrong state.
- **τ (tau)** — margin parameter: 0 is comfortable, 1 is at the boundary.
- **δ (delta)** — difficulty: more jobs at a fixed margin.
- **Σ_ok (corpus)** — successful, conformant runs, used by repair condition
  (R3).
- **Background fault** — a fault by an agent that was *not* injected.
- **Mock** — deterministic scripted agents, correct by construction. Mock
  results test plumbing only and never measure a model.

**Recording.** Every live result file records model ID, pinned provider,
prompt version, date, and each call's `finish_reason`. Requests pin one
provider with fallback disabled. Temperature is 0.7 for agents and 0 for the
judge.

---

## 3. Phase 1 — the original harness (v1) on Claude Haiku 4.5

Code as delivered, with two forced changes: a missing `faultattr/__init__.py`
was added, and the model became `anthropic/claude-haiku-4.5` because the
README's `claude-3.5-haiku` returns 404. Files: `../epsilon.json`,
`../flinch.csv`, `../flinch_analysis.json`.

### 3.1 Projection accuracy (ε)

| measure | result |
|---|---|
| observer slot value errors | 0 / 641 |
| observer parse failures | 0 / 30 |
| reported union bound | 0.0000 |

The reported bound overstates the result:

- **Zero observed errors is not zero error.** By the rule of three, 0/641
  gives ε ≲ 0.0047, so the bound is 2nkε ≲ 0.047.
- **ε was measured only at the observer**, the one stage with rigidly
  formatted output. The planner stage, where parsing actually failed (§3.4),
  was never measured.

### 3.2 Case table

All five **labels** matched the expected verdicts. Σ_ok was 6/8.

Scenario A was right for the wrong reason. It reported `no parseable plan` /
`unscheduled:J1,J2,J3`, margin −1.000 — a parse failure scored as a fault —
instead of the intended separation violation.

### 3.3 Flinch hypothesis (k = 5, 4 seeds)

No candidate signal passed both clauses:

```
psi_hedge       eff_tau=  0.0142  eff_delta= -0.0441  ratio=3.1037  H1 only
psi_ask         eff_tau=  0.0513  eff_delta=  0.3309  ratio=6.4462  H1 only
psi_len         eff_tau= 76.9042  eff_delta= 90.9485  ratio=1.1826  H1 only
psi_extra       eff_tau= 84.5555  eff_delta= 46.4162  ratio=0.5489  H1 only
psi_disagree    eff_tau= -0.1209  eff_delta= -0.2140  ratio=1.7695  -
psi_parsefail   eff_tau=  0.1342  eff_delta=  0.2162  ratio=1.6103  H1 only
```

Planner faults were flat in τ and rose with δ:

| τ | 0.00 | 0.20 | 0.40 | 0.60 | 0.80 | 0.95 |
|---|---|---|---|---|---|---|
| faults | 1/8 | 0/4 | 0/4 | 1/4 | 0/4 | 1/4 |

| δ | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| faults | 1/8 | 1/4 | 1/4 | **3/4** |

The margin knob did not provoke violations, so τ*(α) can't be estimated and
the test is **void**, not negative.

### 3.4 Defects found in v1

| # | defect | evidence |
|---|---|---|
| 1 | Block markers found by plain substring search: `PLAN` matched "Let me plan:", `END` matched "Ends at slot". The empty result was scored as `AGENT_FAULT`. | 2/10 samples at one config; mean planner parse failure 0.125, with at least one failure in 18/40 configs; 4 of 8 planner faults co-occurred with a parse failure |
| 2 | ε measured only at the observer | the failing stage (planner) was unmeasured |
| 3 | The two flinch arms shared the τ=0/δ=0 cell | 28 + 20 rows with 8 shared; `psi_hedge` effect +0.080 on unshared rows vs +0.0142 reported |
| 4 | τ did not provoke violations | flat in τ, rising in δ (§3.3) |
| 5 | Scenario D's verdict depended on the corpus: it was built from clean runs only, so (R3) never fired | a corpus containing successful dead-sensor runs flips D to CORPUS_BLOCKED |
| 6 | The code has four verdict classes; the framework document states three | `CORPUS_BLOCKED` is extra; `attribute.py` cites "Remark 5.3b, case 4a", which doesn't exist |

---

## 4. Phase 2 — harness fixes and the margin accounting

### 4.1 Fixes (details in `../README.md` → "Fixed in v2")

1. **Projection.**
   - Block markers are anchored to line starts, and candidates are tried
     last-to-first.
   - Every `project_*` function raises `ProjectionError` instead of returning
     an empty result.
   - Such runs are classed `UNATTRIBUTABLE_PROJECTION_FAILURE` and never
     scored.
2. **ε everywhere.** Parse-failure rate is measured for all five agents. The
   rule-of-three bound replaces "ε = 0".
3. **Disjoint arms.** Each flinch row is labelled with its arm, and the script
   asserts the arms don't overlap. Arm 2 uses its own seeds at τ = 0.3.
4. **τ provokes violations.** Blocked slots = round(2·τ·n_jobs), spread
   evenly.

   Mock planner faults by τ (16 seeds each):

   | τ | 0.00 | 0.20 | 0.40 | 0.60 | 0.80 | 0.95 |
   |---|---|---|---|---|---|---|
   | faults | 0/16 | 0/16 | 0/16 | 0/16 | 3/16 | 9/16 |

   Every δ at τ = 0.3 gives 0/16.
5. **Corpus sensitivity shown.** `build_corpus(dead_frac)`, and the case table
   now prints D and E under both corpora. D flips to CORPUS_BLOCKED; E is
   stable.

### 4.2 Depletion identity

`consumed_margin()` is now the single accounting source. `exogenous_depletion()`
is measured directly, and `margin = 1 − Σcons − exo`, so 1 − M = Σcons + exo
holds by construction; a residual assertion checks it. Before this, pure
agent faults showed a spurious exo = 0.4.

Property checks:

- **exo = 0** on all 200 clean runs.
- With dead sensors, exo > 0 in **66/66** runs that cover the dead slot and
  exo = 0 in **84/84** that don't.

### 4.3 The cliff rule and the margin sign convention

Remark 7.3 says crossing a constraint is a rejection, not a proportional
cost. So each violation is charged `1 + magnitude/slack`, which is at least
the whole budget.

Property check over 3,000 mock runs (50 seeds × 5 τ values × 3 sensor modes
× 4 injection sets):

| property | result |
|---|---|
| R fails ⇒ M < 0 | ✅ 0 counterexamples in 2,017 runs |
| R holds ⇒ M ≥ 0 | ❌ **304 counterexamples** in 983 runs (τ=0.3: 1, 0.6: 20, 0.9: 142, 0.95: 141) |

Both causes are in the slack budget, not in the cliff rule:

- **Double counting (218 of 304).** `slack()` already excludes blocked slots,
  but gap charges count them. Charging only free slots removes all 218.
- **The budget depends on placement (86 of 304).** A blocked slot inside a
  mandatory separation gap satisfies separation and costs no capacity. So
  the true slack depends on where jobs are placed. This is Definition 7.4's
  open decomposition problem, showing up concretely.

**Not patched** (by instruction). See §9.

---

## 5. Phase 3 — the fixed harness on Claude Haiku 4.5

Files: `live_20260922-011138/`.

### 5.1 ε (n = 30)

| stage | parse failures |
|---|---|
| all five | 0/30 each |
| observer value errors | 0/677 slots |

The rule-of-three bound (ε ≲ 0.10, so 2·5·0.10 = 1.0) is **vacuous at
N = 30**. Epsilon only samples τ = 0.3, and §5.3 shows planner parse failures
depend strongly on τ.

### 5.2 Case table

Verdicts and margin/cons/exo were **identical to mock** for all five
scenarios. A now shows a real `gap 0 < 2` separation violation, with M < 0.

The one difference was corpus size: Σ_ok 4/8 (mock 8/8). The reasons for
exclusion weren't logged at the time; they are now.

### 5.3 Flinch (k = 5, 4 seeds, disjoint arms)

Activation curve (arm 1):

```
tau=0.00  faults=0/4      tau=0.60  faults=0/4
tau=0.20  faults=0/4      tau=0.80  faults=0/2  (2 unattributable excluded)
tau=0.40  faults=0/4      tau=0.95  faults=0/2  (2 unattributable excluded)
WARNING: zero faults at every tau ... void, not negative.
```

ψ table:

```
psi_hedge       eff_tau=  0.3521  eff_delta=   -0.06  ratio=0.1704  FLINCH
psi_ask         eff_tau=  0.0158  eff_delta=    0.57  ratio=36.1154 H1 only
psi_len         eff_tau= 229.948  eff_delta=  40.665  ratio=0.1768  FLINCH
psi_extra       eff_tau=240.3585  eff_delta=   -23.7  ratio=0.0986  FLINCH
psi_disagree    eff_tau= -0.0031  eff_delta=  0.2062  ratio=65.7619 -
psi_parsefail   eff_tau=  0.4522  eff_delta=   0.105  ratio=0.2322  H1 only
```

- **Planner parse failures: 22/200 sampled calls (11%).** The rate rises with
  τ, reaching 0.35 at τ=0.8 and 0.45 at τ=0.95.
- **The cause is truncation.** Re-running two unattributable configs: **8/8
  failed samples ended with `finish_reason=length` at 900 tokens**, none
  containing a plan. Both successful samples ended with `stop`. The planner
  reasons through placements step by step and runs out of budget.
- **Only 2 planner faults occurred, both in the δ arm.** Faults still track
  difficulty, not margin.
- **The three ψ "passes" are one signal.** Word count, words outside the plan
  block, and hedge words all measure how much the planner writes. The finding
  is that **verbosity rises with tightening margin, with difficulty
  controlled (58 → 304 words)**. It can't count as Hypothesis 10.2 support,
  because the test is void.

---

## 6. Phase 4 — choosing an agent model

The goal was a non-reasoning instruct model that reproduces A–E and rarely
faults on its own. The qualification bar was fixed in advance and never
changed:

- clean corpus (τ = 0.2, 8 seeds) **≥ 7/8** conformant
- A–E match expected verdict *and* fault set
- zero projection failures and zero truncations

Providers were chosen by a pre-stated rule and pinned.

### 6.1 Qwen3-235B-A22B-2507 @ Alibaba, prompt v1 (`qwen_20260922-110335/`)

- **ε:** 0/30 parse failures at every stage and 0/677 slot errors, all 150
  calls served by Alibaba. One validator reply was truncated but still parsed.
- **Case table: A–E do not reproduce.** Σ_ok was **1/8**; A came out as
  {planner, **validator**}; D came out as AGENT_FAULT {validator} with a
  separation failure. B, C and E matched.
- **Gap diagnostic** (3 fresh samples, raw text in `diag_sep_raw.json`):
  - violating gaps: **gap 0 = 3**, gap 1 = 1, compliant = 2 — mostly
    back-to-back packing, i.e. **the rule was ignored, not misread**;
  - the validator accepted 2/3 infeasible plans;
  - when it did reject, it computed gaps exactly as the evaluator does.

### 6.2 Screen, prompt v1 (`screen_20260922-111455/`)

| model @ provider | clean /8 | A–E fails | background faults | violating gaps (0 / 1 / other) | validator accepted infeasible |
|---|---|---|---|---|---|
| deepseek/deepseek-chat @ streamlake | 0/8 | B, D, E | 11/13 | 0 / 11 / 0 | 4/7 |
| deepseek/deepseek-chat-v3.1 @ novita/fp8 | 0/8 | B, D, E | 11/13 | 0 / 13 / 0 | 4/7 |
| google/gemini-2.0-flash-001 | — | — | — | skipped: not listed on OpenRouter | — |
| mistralai/mistral-small-3.2-24b-instruct @ deepinfra/fp8 | 0/8 | B, D, E | 11/13 | 0 / 8 / 0 | 3/4 |

No projection failures or truncations.

**Finding: 32/32 violations were exactly gap = 1**, the next job starting at
`s + d + 1`. This is consistent with an **inclusive-end misreading** of
"leave 2 empty slots between the end of one job and the start of the next".
Validators accepted 11/18 of these plans. Qwen differed (gap 0, rule neglect).
Haiku 4.5 passed under v1 but was removed from the candidate list and not
re-tested.

### 6.3 Prompt v2

Planner and validator got the **same** worked example:

> A job with duration 2 starting at slot 0 occupies slots 0 and 1. The next
> job may start at slot 4 or later, leaving slots 2 and 3 empty. In general,
> a job occupying slots s..s+d-1 means the next job starts no earlier than
> s+d+2.

The validator also got: *"Reject if any next job starts before
previous_start + previous_duration + 2."* v1 is kept byte-identical (verified
against a snapshot), and contracts are unchanged. The version is selected
with `FA_PROMPT_VERSION` and recorded on every result.

### 6.4 Screen, prompt v2 (`screen_v2_20260922-123802/`, `screen_v2_20260922-191453/`)

Same models, same pins.

| model | ver | clean /8 | A–E fails | background faults | violating gaps (0 / 1 / other) | validator accepted infeasible | cost |
|---|---|---|---|---|---|---|---|
| deepseek-chat | v1 | 0/8 | B, D, E | 11/13 | 0 / 11 / 0 | 4/7 | $0.0063 |
| | v2 | 1/8 | **none** | 7/13 | 0 / 3 / 0 | 0/2 | $0.0078 |
| deepseek-chat-v3.1 | v1 | 0/8 | B, D, E | 11/13 | 0 / 13 / 0 | 4/7 | $0.0064 |
| | v2 | 2/8 | B, E | 8/13 | 0 / 9 / 0 | 3/6 | $0.0070 |
| mistral-small-3.2 | v1 | 0/8 | B, D, E | 11/13 | 0 / 8 / 0 | 3/4 | $0.0018 |
| | v2 ‡ | 2/8 | B, D, E | 9/13 | 0 / 3 / 0 | 0/3 | $0.0019 |
| qwen3-235b | v1 | 1/8 | A, D | 9/13 | 3 / 1 / 0 † | 2/3 † | ~$0.007 |
| | v2 | 4/8 | A | 5/13 | 0 / 3 / 0 | 1/2 | $0.0041 |

† From the 3-sample diagnostic. ‡ Re-run on the same DeepInfra pin after
upstream HTTP 429s wiped out its first v2 attempt, which is marked invalid.

- **No model qualifies under v2.**
- v2 cut separation violations and background faults for every model.
- **New dominant failure: availability.** Under v2, 6 of deepseek-chat's 7
  remaining clean-run failures are placements on *unavailable* slots
  (mistral-small: 3 of 5). Spacing and availability aren't satisfied
  together. This is an observation only; no v3 prompt was written.

---

## 7. Phase 5 — LLM-as-judge baseline

**Judge:** `openai/gpt-oss-120b` @ Cerebras (`cerebras/fp16`), temperature 0,
`max_tokens` 6000. The judge sees the **full trace**: every agent's exact
input and raw output, the final requirement violations, and a short statement
of R. Four conditions:

| | forced choice (name one agent) | permissive (any subset incl. none, plus a class) |
|---|---|---|
| **no norms** | J-FC | J-P |
| **norms in prompt** (each agent's RULES block) | J-FC-N | J-P-N |

Permissive classes: `AGENT_FAULT` | `MISSING_RULE` (no agent broke a rule;
the rules can be fixed) | `UNFIXABLE_BY_RULES` (no agent could have had the
needed information).

Truncated or API-errored judge replies are infrastructure. They are excluded
from every rate and never scored as wrong.

### 7.1 Controlled condition (`judge_20260922-193302/`, A re-run in `judge_20260922-194059/`)

Deterministic mock agents (correct by construction) plus the A–E injectors,
so the injection record is exact ground truth. 10 seeds per scenario; 44 runs
kept, 6 excluded because R held. **176 judge calls: 0 truncated, 0 parse
failures, 0 API errors.**

Dry run (2 seeds): 0% parse failures, 0% truncation, mean 409–641 output
tokens (max 1,111).

**Exact match (rate, n):**

| | evaluator | J-FC | J-P | J-FC-N | J-P-N |
|---|---|---|---|---|---|
| A, before fix | 1.00 (10) | 0.00 | 0.30 | 0.60 | 0.80 |
| **A, after fix** | 1.00 (10) | **1.00** | **1.00** | **1.00** | **1.00** |
| B | 1.00 (8) | 1.00 | 1.00 | 1.00 | 1.00 |
| C | 1.00 (10) | 0.00 | 0.10 | 0.00 | 0.50 |
| D | 1.00 (8) | 0.00 | 0.00 | 0.00 | **1.00** |
| E | 1.00 (8) | 0.00 | 0.62 | 0.00 | **1.00** |

**Error patterns.**

- **B:** every condition blamed the observer 8/8. The predicted failure mode
  (blaming the visible symptom) didn't happen: with clean traces, the
  observer's input BUSY → output FREE is plain to see.
- **C:** forced choice can't score, by design. Permissive judges named too few
  agents: mean set size 2.1 (J-P) and 2.5 (J-P-N, exact 5/10), against a
  truth of 3.
- **D vs E (class predicted):**

  | | truth | AGENT_FAULT | MISSING_RULE | UNFIXABLE |
  |---|---|---|---|---|
  | J-P | D | **8** | 0 | 0 |
  | J-P | E | 3 | 2 | 3 |
  | J-P-N | D | 0 | **8** | 0 |
  | J-P-N | E | 0 | 2 | **6** |

- **A before the fix:** J-FC blamed the **executor 10/10** ("ran the plan
  despite the validator rejecting it"). The harness had forwarded every plan
  to the executor labelled `ACCEPTED PLAN:`, including rejected ones. That is
  an **unmodelled orchestrator**: no contract, so contract evaluation can't
  see it. **Fix:** a REJECT now halts the pipeline and the executor is not
  invoked. After the fix, A is 10/10 in every condition. B–E never reach this
  path and weren't re-run. Side effect: A's R violation is now `unscheduled`
  rather than `separation`.

**Findings.**

- **Norms and permission to answer "none" are jointly necessary on D/E.**
  Rate of answering the empty set:

  | | no norms | norms |
  |---|---|---|
  | forced | D 0/8, E 0/8 | D 0/8, E 0/8 |
  | permissive | D 0/8, E 5/8 | **D 8/8, E 8/8** |

  Forced choice can't answer "none", so its zeros are structural. The
  empirical result is that, given permission to answer "none", adding norms
  moves D from 0/8 to 8/8.
- **Caveat 3 triggered.** J-P-N approaches the evaluator on B, D and E, so the
  supported claim is the narrower one (formalizing norms a judge could
  already use). Limits: clean traces, and 8–10 runs per cell.
- **E misses fail R4.** J-P-N's 2 misses on E proposed "check actual
  occupancy", a rule no agent can follow because no agent observes
  occupancy.

### 7.2 Natural condition (`judge_20260922-200108/`)

deepseek-chat @ streamlake, prompt v2, no injection, orchestration fix in
place. 30 runs over τ ∈ {0.2, 0.4}.

| | count |
|---|---|
| excluded, infrastructure (N026: planner truncated) | 1 |
| R held | 3 |
| R held but the evaluator found a contract violation | **0 of 3**. Uninformative at this n. |
| judged (R failed, attributable) | 26 |
| halted by validator REJECT | 18 of 26 |
| R violations that are `unscheduled` | 54 of 67 |

Evaluator fault sets: {planner} 16, {planner, validator} 8, {validator} 2.
104 judge calls, 0 truncated, 0 parse failures.

**Evaluator vs judge agreement** (no ground truth, so this is agreement, not
accuracy):

| | exact set | overlap | class |
|---|---|---|---|
| J-FC | 17/26 (0.65) | 0.96 | n/a |
| J-P | 22/26 (0.85) | 0.96 | 0.96 |
| J-FC-N | 18/26 (0.69) — **at the cap** | 1.00 | n/a |
| J-P-N | **25/26 (0.96)** | 1.00 | 1.00 |

Forced choice names exactly one agent, so its ceiling is the 18 of 26 runs
where the evaluator's set has one agent (0.69).

**Reason-redaction ablation** (`ablation_redaction_20260922-200955/`). No new
agent calls:

- 18 judged runs were rebuilt from stored agent text, each verified
  byte-identical to the stored trace.
- The validator's output was cut to `decision=` only; exactly one line
  (`reasons=…`) was removed.
- 8 runs had no stored text and were skipped: N004, N005, N012, N014, N015,
  N018, N025, N027.

| | exact: unredacted → redacted | overlap | class |
|---|---|---|---|
| J-FC | 0.67 → 0.67 | 1.00 → 1.00 | n/a |
| J-P | 0.89 → 0.89 | 0.94 → 1.00 | 0.94 → 1.00 |
| J-FC-N | 0.67 → 0.67 | 1.00 → 1.00 | n/a |
| J-P-N | 0.94 → **1.00** | 1.00 → 1.00 | 1.00 → 1.00 |

**Agreement doesn't come from reading the validator's reasons.** The judge
works the violation out from the plan, durations and unavailable slots.
Caveat: the unredacted arm is the stored judgments, not a fresh re-judge.

**Observation (provisional, pending hand labels).** The disagreements so far
are obligations missing from the contract set:

| case | the judge's position | missing obligation | stable on re-judge? |
|---|---|---|---|
| A, before the fix | executor at fault | orchestrator must not forward a rejected plan | fixed |
| N001 (J-P-N), N018 (J-P) | validator stated the wrong reason | a validator's reasons must be correct | N001 disappeared with redaction; N018 not re-judged |
| N029 (J-P) | MISSING_RULE: no replanning after a rejection | orchestrator retry/replan | **no**: changed to planner, which may be variability |

Not in that table: **N013** (a set omission that didn't recur when re-judged)
and **N027** (can't be checked, because its agent text wasn't stored; future
runs store every trace).

### 7.3 Hand-label sheet (pending)

`judge_20260922-200108/natural_label_sheet_20260922-200108.csv`:

- 20 runs, drawn with `random.Random(20260922)` from the 29 non-excluded runs.
- Each row has the full trace plus every agent's rules, input and output.
- **Not pre-filled, and no evaluator or judge columns.**
- The first line reads *"Mark broke_rule against the written RULES only.
  Record anything else in other_concern."*

Fill `<agent>_broke_rule` with Y/N for all five agents (plus `other_concern`
if needed), then run:

```
python3 experiments/exp_judge.py --score-labels results/judge_20260922-200108/natural_label_sheet_20260922-200108.csv
```

This scores the evaluator and all four judge conditions against the human
labels. Judges are scored only on the runs they judged, i.e. where R failed.

---

## 7b. Phase 6 — Who&When Hand-Crafted pilot

Full write-up: **`NOTE_whowhen_20260923.md`**. External benchmark, 58
Hand-Crafted cases (Magentic-One traces), same judge as Phase 5.

- **Norms frozen before the data.** `faultattr/norms/magentic_one.md`
  (sha256 `dab067b8…`) was written from Magentic-One's public documentation
  only and hash-locked **before any failure record was downloaded**; the
  runner refuses to proceed if the hash or the ordering fails. Two post-hoc
  variants (v2 without O4/O8, v3 with O4 as a process rule) are verified to
  differ from v1 only by their stated edit.
- **Headline (all 58 cases, agent / step accuracy):** the Who&When
  All-at-Once baseline **0.439 / 0.211** beats every norms arm. Best norms
  arm is ABL-4 (O4 as a process rule) at **0.345 / 0.190**; plain norms
  (M) 0.310 / 0.069; norms without the answer key (ABL-3) 0.246 / 0.123;
  norms minus O4/O8 (ABL-2) 0.224 / 0.086. The answer key has little and
  mixed effect in both rows.
- **Rewriting a rule so its violation is locatable in the trace nearly
  tripled step accuracy** (M 0.069 → ABL-4 0.190). v1's O4 is violated by
  the final answer, which Who&When's history does not record; the process
  rewrite points at a recorded step.
- **Printing step numbers** raised coverage (M 0.61→0.79, B 0.84→1.00) and
  step accuracy (B 0.123→0.211) and cut parse failures from 24 to 2, without
  changing which arm leads.
- **Finding — one agent absorbs the blame, and it is the central one, not
  the most specified one.** The Orchestrator holds 31% of labels but is
  named in 56–83% of answers across every norms arm; no arm without norms
  exceeds 47%. It is not any single rule (deleting O4/O8 left it at 69%) and
  **not rule count** — given only 2 rules it still took 77%, while WebSurfer
  with 8 took 19% (Phase 7). A risk for contract-based attribution
  generally.
- **All six arms complete** (ABL-3 57/58, one API error; the rest 57–58/58).
  Three arms were lost to HTTP 402 in the first run and re-run afterwards
  with identical settings.
- **Abstentions (M 10, ABL-2 22, ABL-3 9, ABL-4 2)** land on failures no written rule
  covers — "did not return anything useful", "the keyword was
  insufficient". Human check outstanding.

## 8. Rules adopted along the way

- **Infrastructure failures are never scored as model behaviour.** API
  errors, 429s, timeouts and truncation (`finish_reason = "length"`) are
  excluded and logged, never counted as faults, wrong answers, parse
  failures or background faults. Two earlier bugs had the same shape, a
  missing observation filled with a default that was then scored: parse
  failures turned into agent faults, and 429s turned into "projection
  failures". Check order: API error → truncation → projection failure →
  contracts.
- **Zero observed errors is never reported as ε = 0.** Report the
  rule-of-three bound.
- **Fixed bars and pre-stated rules.** The qualification bar, the provider
  rule, the model selection order and the ψ candidates were all fixed before
  results and never adjusted after.
- **Mock results are plumbing only.** Mock output directories end in `_MOCK`
  or `_MOCK_plumbing_only`.
- **Never overwrite results.** Every output directory is timestamped and
  created with `exist_ok=False`.

---

## 9. Open problems

| | problem | kind |
|---|---|---|
| 1 | Hand labels, two unfilled sheets: the natural condition's `natural_label_sheet_*.csv` (20 runs) and Who&When's `label_audit.csv` (15 disagreements). The only tests of accuracy against an independent judgement | **next step** |
| 1b | OpenRouter credit is nearly exhausted: $9.36 of $10.00 used, $0.64 left. Any further live run needs a top-up | blocked on credit |
| 1c | Norms concentrate blame on the most central agent (Orchestrator: 31% of labels; 56–83% of answers across seven norms arms vs 42–47% without norms), regardless of rule count — tested in `NOTE_rulecount_20261002.md`. Open: centrality itself is not manipulated, and these norms are recovered prose, not predicates over typed state | framework risk |
| 2 | No non-reasoning model passes the 7/8 clean-run bar. Under v2 the dominant failure is spacing and availability not satisfied together | model / prompt |
| 3 | R holds ⇒ M ≥ 0 fails in 304/983 mock runs: double counting (218, mechanical fix ready) and a placement-dependent budget (86, a design decision) | framework, Definition 7.4 |
| 4 | Flinch void on every live run. On Haiku, strain shows up as truncation at 900 tokens. Needs a larger `max_tokens` and separate handling of truncation | experiment design |
| 5 | Controlled traces are easy by construction; the judge result there is an upper bound | caveat |
| 6 | Natural traces are also easy after the orchestration fix: 18/26 end in a REJECT that points at the failing plan | caveat |
| 7 | Orchestrator obligations (don't forward a rejected plan; retry or replan) are not in the contract set | contract authoring |
| 8 | ε bounds are vacuous at N = 30, and ε depends on τ, so it should be measured across the τ range with N ≳ 150 | method |
| 9 | D2 (tolerance stack-up) not demonstrated; the repair search is a hand-written catalogue | known, per README |
| 10 | The code has four verdict classes vs the document's trichotomy; the "Remark 5.3b" citation dangles | documentation |

---

## 10. Cost

All on one OpenRouter key; total **$10.61** (of $25.00 credited) (the account's own balance shows
$8.47 of $10.00 used, the rest from outside this key — which is why the last
two Who&When arms hit HTTP 402 and were cut short).

| phase | cost |
|---|---|
| Phase 1: v1 live on Haiku (ε, cases, flinch, diagnostics) | $0.77 |
| Phase 3: fixed harness live on Haiku (ε, cases, flinch, truncation check) | ~$1.03 |
| Phase 4: Qwen ε + cases, gap diagnostic, two screens, Mistral re-run | ~$0.07 |
| Phase 5: controlled dry run, full run, and A re-run | ~$0.32 |
| Phase 5: natural condition | $0.10 |
| Phase 5: redaction ablation | ~$0.06 |
| Phase 6: Who&When pilot (dry run + 58 cases, 2 arms) | $0.91 |
| Phase 6: Who&When ablations (dry run + 6 arms, 2 cut short by credit) | $1.69 |
| Phase 6: ABL-2 completion (8 calls) | $0.05 |
| Phase 6: ABL-3 + ABL-4 (116 calls) | $0.80 |
| Phase 7: rule-count experiment, 3 arms (183 calls) | $1.25 |

Per-run cost readings taken right after a run can lag, because the key's
usage total updates late. The phase totals above come from the settled key
balance.

---

## 11. File index

| path | contents |
|---|---|
| `NOTE_prompt_v2_20260922.md` | running findings log (screening, prompt v2, judge) |
| `SESSION_REPORT.md` | report of Phases 1–3 |
| `../epsilon.json`, `../flinch.csv`, `../flinch_analysis.json` | Phase 1 (v1) outputs |
| `live_20260922-011138/` | Phase 3: ε, case table, flinch on Haiku |
| `qwen_20260922-110335/` | Qwen ε, case table, gap diagnostic (`diag_sep_raw.json`) |
| `screen_20260922-111455/` | model screen, prompt v1 (log, summary, raw text) |
| `screen_v2_20260922-123802/` | model screen, prompt v2 (its Mistral row is invalid: 429s) |
| `screen_v2_20260922-191453/` | Mistral v2 re-run, same pin |
| `judge_20260922-193302/` | controlled condition, all scenarios |
| `judge_20260922-194059/` | controlled condition, A after the orchestration fix |
| `judge_20260922-200108/` | natural condition, label sheet, redaction ablation |
| `NOTE_whowhen_20260923.md` | Who&When pilot and ablations, final |
| `whowhen_20260922-215346/` | Who&When pilot: report, rows, raw replies, `label_audit.csv`, `audit_histories/` |
| `whowhen_abl_20260922-224740/` | Who&When ablations: 2×2; ABL-3/ABL-4 unmeasured |
| `whowhen_abl_20260923-070445/` | ABL-2's 8 completing calls, plus the merged 58-case ABL-2 report |
| `whowhen_abl_20260923-182513/` | ABL-3 and ABL-4, all 58 cases each |
| `PREREG_rulecount_20261002.md` (+ `.lock.json`) | pre-registration, hashed before the rule-count norm sets existed |
| `NOTE_rulecount_20261002.md` | rule count vs role centrality: the specification-density refutation |
| `whowhen_abl_20261002-113814/` | N-BAL, N-ORCH, N-WEB, all 58 cases each |
| `../faultattr/norms/` | frozen norms and their hash locks (v1 pre-data; v2, v3 post-hoc) |
| `../data/who_and_when/` | cached Hand-Crafted records with per-file hashes and download time |
| `*_MOCK*/` | plumbing tests only — not results |

Every results directory holds a human-readable report (`*_table_*.txt`,
`*_report_*.txt`, `screen_log.txt`), per-run rows (`*.csv`), and raw model
text (`*_raw_*.jsonl`, `raw_*.jsonl`) with model, provider, prompt version,
date and `finish_reason`.
