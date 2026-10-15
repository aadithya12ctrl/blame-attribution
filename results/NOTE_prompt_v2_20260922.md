# Results note — separation-rule clarification (prompt v2)

Date: 2026-09-22. Agent screening only. The judge experiment was not run.

## Finding (prompt v1)

Under the original prompts (v1), **all 32 separation violations** in the
clean-corpus planner outputs of `deepseek/deepseek-chat`,
`deepseek/deepseek-chat-v3.1` and `mistralai/mistral-small-3.2-24b-instruct`
had **gap = 1** exactly. Here gap = `next_start − (start + duration)`, the
evaluator's definition. The next job starts at `s + d + 1`. This is consistent
with an **inclusive-end misreading** of "leave at least 2 empty slots between
the end of one job and the start of the next": the model computes
`next_start − last_occupied_slot = 2`. The validators, which were given the
same wording, **accepted 11 of 18** plans with a separation violation.

**Qwen differed.** `qwen/qwen3-235b-a22b-2507` violated with **gap 0**: 3 of 4
violations in a 3-sample diagnostic. That is back-to-back packing, i.e.
**rule neglect, not misreading.** Its validator, when it did check, computed
gaps with the evaluator's end-exclusive arithmetic.

**`anthropic/claude-haiku-4.5` passed under v1**: the case table reproduced
A–E exactly in two live runs. It was later removed from the candidate list and
**was not re-tested under v2**.

Sources: `results/screen_20260922-111455/` (v1 screen, raw text),
`results/qwen_20260922-110335/` (Qwen case table and gap diagnostic).

## The change (v2)

- Selected by `FA_PROMPT_VERSION=v2`. v1 is kept byte-identical and verified
  against a pre-change snapshot.
- Planner and validator get the **same** worked example: *"A job with
  duration 2 starting at slot 0 occupies slots 0 and 1. The next job may start
  at slot 4 or later, leaving slots 2 and 3 empty. In general, a job occupying
  slots s..s+d-1 means the next job starts no earlier than s+d+2."*
- The validator also gets: *"Reject if any next job starts before
  previous_start + previous_duration + 2."*
- Contracts are unchanged. Every result records its prompt version.

## Results, model × prompt version

Qualification bar (fixed): clean corpus ≥ 7/8 conformant; A–E match expected
verdict and fault set; 0 projection failures; 0 truncations. Providers are
pinned to the same endpoints in v1 and v2.

`background_fault_rate` is the fraction of the 13 screening runs (8 corpus + 5
scenarios) whose fault set contains an agent that was not injected. Gap
distribution and validator acceptance are computed on the 8 clean-corpus
planner outputs, where "infeasible" means a separation violation (gap < 2).
Blocked-slot collisions are not counted in the acceptance column.

| model | ver | clean /8 | A–E fails | bg fault | viol. gaps (0 / 1 / other) | val. accepted infeasible | proj | trunc | cost |
|---|---|---|---|---|---|---|---|---|---|
| deepseek-chat @ streamlake | v1 | 0/8 | B, D, E | 11/13 | 0 / 11 / 0 | 4/7 | 0 | 0 | $0.0063 |
| | **v2** | **1/8** | **none** | **7/13** | 0 / **3** / 0 | **0/2** | 0 | 0 | $0.0078 |
| deepseek-chat-v3.1 @ novita/fp8 | v1 | 0/8 | B, D, E | 11/13 | 0 / 13 / 0 | 4/7 | 0 | 0 | $0.0064 |
| | **v2** | **2/8** | B, E | **8/13** | 0 / **9** / 0 | 3/6 | 0 | 0 | $0.0070 |
| mistral-small-3.2 @ deepinfra/fp8 | v1 | 0/8 | B, D, E | 11/13 | 0 / 8 / 0 | 3/4 | 0 | 0 | $0.0018 |
| | **v2** ‡ | **2/8** | B, D, E | **9/13** | 0 / **3** / 0 | **0/3** | 0 | 0 | $0.0019 |
| qwen3-235b-a22b-2507 @ alibaba | v1 | 1/8 | A, D | 9/13 | 3 / 1 / 0 † | 2/3 † | 0 | 0 | ~$0.007 |
| | **v2** | **4/8** | **A** | **5/13** | 0 / **3** / 0 | 1/2 | 0 | 0 | $0.0041 |

† The Qwen v1 gap and acceptance figures come from the 3-sample diagnostic
(fresh samples), not from the case-table runs. That run saved no raw text.

‡ Mistral v2 comes from a separate re-run (`results/screen_v2_20260922-191453/`)
on the **same** DeepInfra fp8 pin, after the provider recovered from the
upstream 429s that blocked it in the main v2 screen. No provider change, so no
provider confound. Its first v2 attempt (`screen_v2_20260922-123802`) is not a
measurement: every call failed with HTTP 429.

**Selection (pre-registered order: deepseek-chat, deepseek-chat-v3.1,
mistral-small-3.2, qwen3-235b): no model qualifies under v2.** All four
measured models fail the ≥ 7/8 clean-corpus bar (1/8, 2/8, 2/8, 4/8). The bar
was not changed.

## What v2 changed

- **Separation violations fell for every model.** gap = 1: deepseek-chat
  11→3, v3.1 13→9, mistral-small 8→3. Qwen's gap-0 packing disappeared
  (3→0), leaving 3 gap = 1 violations.
- **Validator acceptance of infeasible plans fell** for deepseek-chat
  (4/7 → 0/2) and mistral-small (3/4 → 0/3).
- **Background faults fell for every model** (deepseek-chat 11→7, v3.1
  11→8, mistral 11→9, qwen 9→5, of 13). Clean corpora rose to 1, 2, 2 and 4
  of 8. None reached the 7/8 bar.
- **deepseek-chat now matches A–E exactly** under v2. It fails only on the
  corpus bar.
- **Qwen's A failure is unchanged:** its validator again accepted the
  injected gap-0 plan.

### Observation: spacing and availability are not satisfied jointly

Under v2, **6 of deepseek-chat's 7 remaining clean-run failures are
placements on unavailable slots** (a job over a slot listed as unavailable).
Only 1 of the 7 is a pure separation violation. Under v1, separation
violations dominated. Read together: the clarification fixed how the models
compute spacing, but the planner still does not satisfy the spacing rule and
the availability rule **jointly**. Once it spaces correctly, a job lands on an
unavailable slot. mistral-small v2 shows the same pattern: 3 of its 5 planner
failures involve a blocked slot. This is recorded as an observation, not a
diagnosis. **No v3 prompt was written or tested.**

## Judge baseline — controlled condition

Judge `openai/gpt-oss-120b` @ Cerebras, temperature 0, `max_tokens` 6000.
Agents: deterministic mock agents (correct by construction) plus the A–E
injectors, so the injection record is exact ground truth. 10 seeds per
scenario; 44 runs kept (6 excluded because R held). 176 judge calls, of which 0
were truncated, 0 failed to parse, and 0 hit API errors. Source:
`results/judge_20260922-193302/`; A post-fix: `results/judge_20260922-194059/`.

### Finding: on D/E, norms and permission to answer "none" are jointly necessary

Rate of answering the empty agent set (the truth on both D and E):

| | no norms | norms in prompt |
|---|---|---|
| **forced choice** | D 0/8, E 0/8 (J-FC) | D 0/8, E 0/8 (J-FC-N) |
| **permissive** | D 0/8, E 5/8 (J-P) | **D 8/8, E 8/8** (J-P-N) |

Only norms + permissive reaches the evaluator. Precision: forced choice cannot
return the empty set, so its 0/8 is structural, not empirical. The empirical
content is the right-hand column of the permissive row: given permission to
say "no agent", adding the norms moves D from 0/8 to 8/8. On class (D vs E),
J-P-N gets D 8/8 MISSING_RULE and E 6/8 UNFIXABLE_BY_RULES. Without norms, J-P
calls every D an AGENT_FAULT and splits E 3/2/3 across the three classes.

### Finding: caveat 3 triggered

On clean traces, **J-P-N approaches the evaluator on B (8/8), D (8/8) and
E (8/8 empty set; 6/8 class).** By the criterion set in advance, the
supported claim is the narrower one: on these cases the contribution is
formalizing norms that a judge could already use, given the norms and allowed
to answer "none". Limits: the controlled traces are easy by construction (the
injected deviation is the only anomaly in each trace), and the cells hold
8–10 runs. The natural condition tests noisy traces.

### Finding: an unmodelled orchestrator is invisible to contract evaluation (A)

Before the fix, J-FC blamed the **executor 10/10** on A ("the executor ran the
plan despite the validator rejecting it"). J-P blamed it 7/10, J-FC-N 4/10,
J-P-N 2/10. Cause: the harness forwarded every plan to the executor under an
`ACCEPTED PLAN:` header, including rejected ones. That forwarding step is an
orchestrator component with no contract. The evaluator excused the executor
(its precondition "plan was accepted" failed) and could not see the
orchestrator at all. The judge was pointing at a real gap the contracts
didn't cover.

**Fix:** a REJECT now halts the pipeline, the executor is not invoked, the
trace says so, and R scores the empty schedule as unscheduled. Contracts are
unchanged. **A post-fix: every judge condition is exact, 10/10**, blaming the
planner. B–E are unaffected, since their validators accept (C's by
injection), so they never reach the halt; they were not re-run.

Side effect: A's R violation is now `unscheduled:J1..J3` instead of
`separation:J2~J3`, because a rejected plan dispatches nothing. A was moved to
τ = 0 to force a separation violation; that reason no longer applies to R's
report, though the planner's guarantee failure is still `gap 0 < 2`.

### Finding: E misses propose an unobservable rule (fails R4)

J-P-N's 2 misses on E classed it MISSING_RULE and proposed a rule such as
"check actual occupancy beyond the reported unavailable slots". No agent
observes physical occupancy; each sees only sensor-derived state, so no agent
can be given that rule. It fails (R4), expressibility over the agent's
observable history. The judge recognised that a rule was missing, but not that
it could not be written for any agent.

## Judge baseline — natural condition

Agents `deepseek/deepseek-chat` @ streamlake, prompt v2, no injection, with the
orchestration fix (a validator REJECT halts the pipeline). 30 runs over τ ∈
{0.2, 0.4}. Judge `openai/gpt-oss-120b` @ Cerebras, temperature 0,
`max_tokens` 6000. Cost $0.103. Source: `results/judge_20260922-200108/`.

| | count |
|---|---|
| runs | 30 |
| excluded, infrastructure (N026: planner truncated at 900 tokens) | 1 |
| R held | 3 |
| **R held but the evaluator found a contract violation** | **0 of 3**. Uninformative at this n. |
| judged (R failed, attributable) | 26 |
| halted by validator REJECT | **18 of 26** |
| R violations that are `unscheduled` | **54 of 67** |

The 104 judge calls had no truncations, parse failures or API errors.
Evaluator fault sets on the 26 judged runs: {planner} 16, {planner,
validator} 8, {validator} 2.

**Evaluator vs judge agreement** (no ground truth; agreement is not accuracy):

| | exact set | overlap | class |
|---|---|---|---|
| J-FC | 17/26 (0.65) | 0.96 | n/a |
| J-P | 22/26 (0.85) | 0.96 | 0.96 |
| J-FC-N | 18/26 (0.69) | 1.00 | n/a |
| J-P-N | **25/26 (0.96)** | 1.00 | 1.00 |

**Forced-choice cap:** a forced-choice answer names one agent, so it can match
only runs where the evaluator names exactly one: **18 of 26 by construction**
(0.69). J-FC-N sits at the cap.

**Why the natural traces are easy:** after the orchestration fix, 18 of 26
judged runs end with the validator rejecting an infeasible plan and the
pipeline halting. R then reports every job unscheduled, which is why
`unscheduled` dominates (54 of 67). In those runs the failing agent is
usually the planner, and the rejection points straight at it.

### Reason-redaction ablation: agreement does not come from reading the validator's reasons

Same judged runs, no new agent calls. Each run was rebuilt from its stored
agent text and verified byte-identical to the stored trace, then the
validator's output was reduced to `decision=` only (exactly one line removed:
`reasons=...`) and re-judged with the same judge, provider and settings. 18 of
26 judged runs had stored agent text; 8 were skipped (N004, N005, N012, N014,
N015, N018, N025, N027). Source: `ablation_redaction_20260922-200955/`.

| | exact: unredacted → redacted | overlap | class |
|---|---|---|---|
| J-FC | 0.67 → 0.67 | 1.00 → 1.00 | n/a |
| J-P | 0.89 → 0.89 | 0.94 → 1.00 | 0.94 → 1.00 |
| J-FC-N | 0.67 → 0.67 | 1.00 → 1.00 | n/a |
| J-P-N | 0.94 → **1.00** | 1.00 → 1.00 | 1.00 → 1.00 |

Removing the reasons did not lower agreement in any condition. The judge
re-derives the violation from the plan, the job durations and the unavailable
list. N001's disagreement (the judge penalising the validator's wrong
*reason*) disappears once there is no reason to judge. The forced-choice
changes (N023, N028) swap between two agents that are both in the
evaluator's set, so they don't change agreement. Caveat: the unredacted arm
is the stored judgments, not a fresh re-judge, so small differences can be
judge noise.

### Observation (provisional, pending hand labels): the disagreements are obligations missing from the contract set

Every substantive judge–evaluator disagreement found so far was an
**obligation absent from the contract set**, not an attribution error:

| case | judge's position | obligation the contracts lack |
|---|---|---|
| A, before the fix | executor at fault for dispatching a rejected plan | an orchestrator must not forward a rejected plan (the orchestrator had no contract) |
| N001 (J-P-N), N018 (J-P) | validator at fault for stating the wrong reason for a correct REJECT | a validator's stated reasons must be correct (the contract checks the decision only) |
| N029 (J-P) | no agent at fault; MISSING_RULE: nothing produces a new plan after a rejection | an orchestrator retry or replan obligation (introduced by the halt) |

**Stability:** of the three natural cases, N001's disagreement disappeared
when its reasons were redacted, as expected, since it was about reasons.
**N029's did not recur either**: in the redacted re-judge, J-P named the
planner, agreeing with the evaluator. So N029 may be judge variability rather
than a stable position. N018 had no stored agent text and was not re-judged.

**Provisional:** this rests on the evaluator's verdicts and the judge's stated
reasons. The hand labels are what test it, and the `other_concern` column
was added to the label sheet to capture exactly this kind of case. Two
disagreements are **not** in the table. **N013** (J-P named only the
validator; the evaluator names planner + validator) is a set omission, not a
missing obligation. It did not recur when re-judged in the redacted arm,
which is consistent with judge noise but doesn't prove it. **N027** (the judge
says the planner broke separation; the evaluator says only the validator
faulted) cannot be checked: its agent text was not stored. Future natural
runs store the full trace for every run.

## Mistral: first v2 attempt was not a measurement

In the main v2 screen, all 65 of mistral's calls failed. DeepInfra returned
HTTP 429 with
`provider_error_code: engine_overloaded`, `limit_source:
upstream_provider_shared_pool`: shared-pool rate limiting on the provider
side. A probe hours later got a normal reply, and mistral was re-screened on
the same pin (row ‡ above). The screen script had
been reporting these as "projection failures" (a call with no reply yields
empty text). That is fixed: API errors are now counted separately, and such a
model is reported as NOT MEASURED instead of being scored.

Also during v2: the StreamLake endpoint for deepseek-chat reported degraded
status −2 at startup. All 65 of its calls were still served by StreamLake.

## Costs

| step | cost |
|---|---|
| Qwen epsilon + case table (v1) | $0.0145 |
| Qwen gap diagnostic | $0.0005 |
| v1 screen, 3 models | $0.0145 |
| v2 screen, 4 models (mistral failed on 429s) | $0.0190 est. (key usage delta $0.0149) |
| v2 mistral re-run, same pin | $0.0019 |

## Files

- `results/screen_v2_20260922-123802/`: v2 screen log, summary, and raw
  planner/validator text per model. Its mistral row is invalid (429s).
- `results/screen_v2_20260922-191453/`: mistral v2 re-run, same pin.
- `results/screen_20260922-111455/`: v1 screen.
- `results/qwen_20260922-110335/`: Qwen v1 epsilon, case table, gap
  diagnostic.
- `*_MOCK_plumbing_only/` directories are mock plumbing checks. They are not
  results.
