# Who&When Hand-Crafted pilot — frozen norms and an open verdict space

Final. Dated 2026-09-23. **All six arms are now complete.** The first
ablation run lost three arms to HTTP 402 (the account's credit); ABL-2, ABL-3
and ABL-4 were re-run afterwards with identical settings. Remaining credit:
about $0.64.

Judge for every arm: `openai/gpt-oss-120b` @ Cerebras (`cerebras/fp16`),
temperature 0. Dataset: `Kevin355/Who_and_When`, Hand-Crafted subset, all 58
cases, each file hash-recorded at download.

Outputs: `whowhen_20260922-215346/` (pilot), `whowhen_abl_20260922-224740/`
(first ablation run: M, B, ABL-1 complete), `whowhen_abl_20260923-070445/`
(ABL-2's 8 completing calls), `whowhen_abl_20260923-182513/` (ABL-3, ABL-4).
Cost: pilot $0.91, ablations $1.69, ABL-2 completion $0.05, ABL-3 + ABL-4
$0.80, total **$3.45**.

## Integrity of the norms

| norms | sha256 | content | provenance |
|---|---|---|---|
| **v1** | `dab067b8…0ac9` | O1–O8, W1–W4, F1–F2, C1–C6, T1–T2 | written **before any failure record was downloaded**, from Magentic-One's public documentation only; every rule cites its source |
| v2 | `6164f7ce…41fc` | v1 minus O4 and O8 | **post-hoc**, frozen after the pilot |
| v3 | `62f0eac6…556d` | v1 with O4 rewritten as a process rule | **post-hoc**, frozen after the pilot |

The pilot refuses to run if a norms file no longer matches its lock, or if
the data was downloaded before the v1 freeze. Both variants are verified
programmatically to differ from v1 only by their stated edit plus a header
note; rule IDs are not renumbered. A tampered copy was rejected in testing.

Caveat: these norms are **prose recovered from documentation**, not
predicates over typed state. They are not the contracts of the framework's
formal sections, and nothing here checks them mechanically.

## Dataset notes

- `history` is a list of `{content, role}`; the agent is in `role`. The
  Coder appears as **`Assistant`** (Magentic-One's own name for it), and
  labels mix `WebSurfer` / `Websurfer`. Names are normalized
  case-insensitively with those aliases.
- **Steps are 0-based**, verified: the role at `history[mistake_step]`
  matches the labelled agent in 55/58 cases (1-based gives 12/58).
- **Cases 20, 22 and 49 are internally inconsistent** (the labelled step
  belongs to another agent). Pre-registered: headline numbers include them,
  with a sensitivity figure excluding them.
- Label base rate: WebSurfer 33, **Orchestrator 18 (31%)**, Coder 4,
  FileSurfer 3.

## Method and arms

- **METHOD** (J-P-N style): full history + question + ground-truth answer +
  the frozen norms. JSON out, verdict `RULE_VIOLATION` or
  `UNDERDETERMINED` (no stated rule clearly violated). Never forced.
- **BASELINE**: Who&When All-at-Once, prompt copied verbatim from the
  authors' repository (`Automated_FA/Lib/utils.py`), ground-truth line
  removed, their free-text output format, forced single agent + step.
- Every arm prints steps as `[step N]` and requires a printed step number.

## Headline: the 2×2 (all 58 cases, as pre-registered)

Cells are agent accuracy / step accuracy / coverage, on all scorable cases
(abstention and parse failure count as wrong).

| | no ground truth | with ground truth |
|---|---|---|
| **no norms** (forced, Who&When format) | **B**: 0.439 / 0.211 / 1.00 | **ABL-1**: 0.414 / 0.241 / 1.00 |
| **norms v1** (open verdict, JSON) | **ABL-3**: 0.246 / 0.123 / 0.68 | **M**: 0.310 / 0.069 / 0.79 |

Norms variants, ground truth yes: **ABL-2** (O4/O8 removed) 0.224 / 0.086 /
0.60; **ABL-4** (O4 as a process rule) **0.345 / 0.190 / 0.83**.

Sensitivity excluding cases 20/22/49 (agent): B 0.455, ABL-1 0.418, ABL-3
0.259, M 0.309, ABL-2 0.236, ABL-4 0.364. Same ordering, so the headline does
not rest on those three cases.

Common set (56 cases scorable in all six arms):

| arm | agent | step | coverage |
|---|---|---|---|
| B | **0.429** | 0.214 | 56/56 |
| ABL-1 | 0.411 | **0.250** | 56/56 |
| ABL-4 | 0.357 | 0.196 | 46/56 |
| M | 0.304 | 0.071 | 44/56 |
| ABL-3 | 0.250 | 0.125 | 38/56 |
| ABL-2 | 0.214 | 0.089 | 33/56 |

**No norms arm beats either no-norms arm on agent accuracy.** The best of
them, ABL-4, is the closest (0.357 vs 0.429) and is the only norms arm whose
step accuracy approaches the baselines' (0.196 vs 0.214 / 0.250).

Confounds, stated in advance: ground truth is isolated **within** a norms
row. Across rows the norms also change the verdict space (open vs forced)
and the output format (JSON vs free text), so the norms effect cannot be
separated from those.

## ABL-2 (O4 and O8 removed): complete, 58 of 58 cases

The first run lost 8 calls to HTTP 402. Those 8 cases (46, 48, 49, 52, 53,
54, 55, 58) were completed later in
`whowhen_abl_20260923-070445/` — same judge, provider, temperature,
`max_tokens`, prompt and norms hash (v2 `6164f7ce…`), 0 infrastructure
failures, $0.0498. Merged records and report:
`whowhen_abl_20260923-070445/ABL-2_merged_{raw.json,report.txt}`. The only
difference is wall-clock time, about 8 hours later.

| | agent | step | coverage | abstentions |
|---|---|---|---|---|
| **ABL-2, all 58** | **0.224** | **0.086** | 35/58 = 0.60 | 22 |
| ABL-2, sensitivity excl. 20/22/49 | 0.236 | 0.073 | — | — |
| ABL-2, common 57 | 0.228 | 0.088 | 34/57 | — |
| M, common 57 | 0.298 | 0.070 | 45/57 | — |

One parse failure remains, and it is the structural one: the answer names
the Orchestrator's final answer, one step past the end of the trace.

## ABL-3 (norms v1, no ground truth): 57 of 58 cases

One API error (case 7), excluded as infrastructure. Agent **0.246**, step
**0.123**, coverage 39/57 = 0.68, 9 abstentions, 9 parse failures (7 give no
step at all, 2 name the unrecorded final answer). Dropping the answer key
costs 6 points of agent accuracy against M and lowers coverage, but *raises*
step accuracy (0.123 vs 0.069): without the answer to explain, the judge
points at a step inside the trace more often instead of at the final answer.

## ABL-4 (O4 rewritten as a process rule): 58 of 58 cases, the best norms arm

Agent **0.345**, step **0.190**, coverage 48/58 = 0.83, only **2**
abstentions, 8 parse failures. Against M (same norms otherwise, same ground
truth): agent 0.310 → 0.345, step **0.069 → 0.190**, coverage 0.79 → 0.83,
abstentions 10 → 2.

**Why the step accuracy nearly triples:** v1's O4 ("satisfied only if fully
addressed") is violated by the *final answer*, which the Who&When trace does
not record, so the judge either cites an unrecorded step or gives none. The
process rewrite ("do not declare completion while a sub-goal is unmet or a
step reported failure") points at a step that *is* in the trace. Rewriting a
rule so that its violation is locatable in the recorded history — rather than
in the outcome — is what moved the number.

The cost is concentration: ABL-4 names the Orchestrator in **40 of 48**
answers (83%), the highest of any arm (next section).

## FINDING: the norms concentrate blame on one agent (mechanism superseded — see below)

Share of answers naming the Orchestrator, against a **31% label base rate**:

| arm | norms | ground truth | Orchestrator share of answers |
|---|---|---|---|
| B | none | no | 24/57 = **42%** |
| ABL-1 | none | yes | 27/58 = **47%** |
| ABL-3 | v1 | no | 27/39 = **69%** |
| ABL-2 | v2 (no O4/O8) | yes | 24/35 = **69%** |
| M | v1 | yes | 33/46 = **72%** |
| ABL-4 | v3 (O4 process) | yes | 40/48 = **83%** |

Label base rate: 18/58 = 31%.

Two things follow, now that all six arms exist:

1. **Every arm given the norms concentrates on the Orchestrator (69–83%);
   neither arm without them does (42–47%).** The no-norms arms are themselves
   above the 31% base rate, but the norms roughly double the excess.
2. **It is not about any single rule.** Removing the two rules a failed run
   violates trivially (O4, O8) left the share at 69%, with the judge citing
   O3, O6 and O7 instead. Rewriting O4 as a process rule *raised* it to 83%,
   the highest of any arm.

**Interpretation — SUPERSEDED on 2026-10-02.** This note originally read
the pattern as **specification density**: the Orchestrator holds 8 of the 22
rules, and more rules mean more ways to be found in breach. **Rule count was
never manipulated here, and that mechanism is now refuted.**
`NOTE_rulecount_20261002.md` manipulates it directly (N-BAL 3 rules each,
N-ORCH 8 Orchestrator, N-WEB 8 WebSurfer): with only **2** rules the
Orchestrator still took **77%** of answers in N-WEB, while WebSurfer with
**8** took 19% — its lowest share of any arm — and N-WEB had the *worst*
agent accuracy (0.207). Even with counts equal (N-BAL) blame stays inverted
against the labels: Orchestrator 56% vs a 31% base rate, WebSurfer 34% vs
57%.

**The amended claim:** written norms concentrate blame on the most
**central** agent — the one whose rules are outcome-shaped (is the request
satisfied, re-plan, final answer), which a failed run always arguably
breaches — not on the most heavily specified one. Rule count instead moves
**coverage**: more rules on a peripheral agent produced *more abstention*
(N-WEB 24, coverage 0.53), not more blame. Still a risk for contract-based
attribution generally, but the risk is in which obligations are
outcome-shaped, not in how many there are. These norms remain prose
recovered from documentation rather than predicates over typed state.

## FINDING: the ground-truth answer had little and mixed effect, in both rows

| row | without GT | with GT | agent | step |
|---|---|---|---|---|
| no norms | B | ABL-1 | 0.439 → 0.414 | 0.211 → **0.241** |
| norms v1 | ABL-3 | M | 0.246 → **0.310** | 0.123 → 0.069 |

Adding the answer key moves agent accuracy by about 3 points down without
norms and 6 up with them, and moves step accuracy the opposite way in each
row. Coverage rises with it in the norms row (0.68 → 0.79): knowing the
answer makes the judge readier to name a rule violation. No consistent
benefit, and nothing like the effect the norms themselves have.

## FINDING: printing step numbers raised coverage and step accuracy, and changed no ranking

Both arms, pilot (unnumbered, `max_tokens` 6,000) → final (numbered,
`max_tokens` 32,000):

| arm | coverage | agent (all) | step (all) | parse failures | truncated |
|---|---|---|---|---|---|
| M | 0.61 → **0.79** | 0.304 → 0.310 | 0.036 → 0.069 | **15 → 2** | 2 → 0 |
| B | 0.84 → **1.00** | 0.386 → 0.439 | 0.123 → **0.211** | **9 → 0** | 1 → 1 |

In the pilot, 24 of the two arms' parse failures were step-out-of-range or
missing. Numbering removed nearly all of them, and B's step accuracy
nearly doubled. **B still leads M on both measures**, so the earlier
ranking was not a parsing artifact.

Remaining step failures are structural, not counting errors: they name the
**Orchestrator's final answer, which the Who&When history does not record**
(step `null`, or exactly one past the last printed step).

## Judge context and output budget

- Context 131,072 tokens; `max_tokens` raised from 6,000 to 32,000. Longest
  prompt **67,677** tokens (ABL-4, case 30). **No case excluded for
  context.**
- The endpoint appears to cap output at **8,192 tokens** in practice: B's
  case 20 stopped there with `finish_reason=length`, while every other
  successful reply stayed at or under 3,100. That one case is excluded from
  B, and the common-set table controls for it.
- Infrastructure failures are never scored as model behaviour: 1
  truncation (B, case 20) and 1 API error (ABL-3, case 7) in the final
  results. The first ablation run also lost 117 calls to HTTP 402 (ABL-2 8,
  ABL-3 54, ABL-4 55); all three arms were re-run.

## Abstentions: the outstanding question

Abstentions by arm: **M 10, ABL-2 22, ABL-3 9, ABL-4 2**. The annotated reasons are
dominated by retrieval quality and judgement, not rule breaches:

- "the information obtained … is neither reliable nor satisfies the
  requirements" (case 2)
- "does not click on useful information" (case 8)
- "did not return anything useful" (case 29)
- "the keyword it entered was insufficient" (case 17)
- "the Orchestrator should not replan" (cases 9, 19)

None of W1–W4 or O1–O8 covers "the page you fetched was not useful".
Abstaining is defensible under a "written RULES only" standard, and would
be the framework's `UNDERDETERMINED` verdict. **It has not been checked by
a human.** Full lists with reasons are in each run's `report.txt`.

## Outstanding human work, in working order

Nothing below is filled in, and **none of it may be filled by the model that
produced the verdicts**: the measurement is worth only as much as its
independence from the evaluator and the judge.

### 1. Abstentions — smallest, highest information

The framework's central claim on real data: when no written rule covers the
failure, the honest answer is UNDERDETERMINED. These are all 10 abstentions
of the final M arm (cases 2, 8, 9, 12, 19, 29, 36, 40, 50, 56).

**Stage 1, blind** — `whowhen_abl_20260922-224740/abstention_blind.csv`.
The trace and the RULES only; **no benchmark label, no method answer**. Two
questions per row, kept separate:

| column | question |
|---|---|
| `violated` | Was any written rule clearly violated? Y/N — if Y, `which_agent` and `which_step` (a printed step) |
| `explains` | Does *that* violation account for the wrong final answer? Y / N / unsure |
| `justification` | free text |

**The abstention is unprincipled only when `violated = Y` AND
`explains = Y`.** `violated = Y, explains = N` *supports* the abstention: it
is a rule broken that is not a fault for this failure — the framework's own
error/fault split (§2.1), applied to the audit. Asking only "was a rule
violated" would collapse that distinction, and in a 50-step Magentic-One
trace some agent has almost certainly broken some rule somewhere, so the
loose question would score nearly every abstention wrong and turn the
10-case result into noise.

```
python3 experiments/exp_whowhen.py --score-blind <sheet>
```

reports the four buckets, the principled rate over decided cases, and bounds
if every `unsure` fell each way. It **refuses to print aggregates until every
row is filled** (override: `--allow-partial`). Reading the totals early is
the pressure this sheet exists to measure, so the tool does not offer it
without friction. **Every scoring run is appended to
`results/label_scoring_runs.log` with its timestamp and whether
`--allow-partial` was used**, so a legitimate override is in the record
rather than in memory.

Label all ten in one sitting if you can: spreading them over days lets the
running total leak in through memory of the earlier rows.

**Stage 2, revealed** — `whowhen_abl_20260922-224740/abstention_audit.csv`.
Same 10 cases with the label and the method's answer shown; mark
`human_verdict` as label_right / method_right / both_defensible / neither.
Only after stage 1.

```
python3 experiments/exp_whowhen.py --score-audit <sheet>
```

**Second labeller:** prefer `abstention_blind_labellerB_10rows.csv` (all
10). Kappa on n=5 is close to meaningless — a single flipped case swings it
enormously — so the 10-row version is what makes the `violated` vs
`unprincipled` split reportable rather than suggestive. If B only has
capacity for 5, use `abstention_blind_labellerB_5rows.csv` (cases 2, 9, 19,
36, 50; `random.Random(20260924)`) and **report the kappa as indicative,
with n stated**. Either way, do not reconcile disagreements afterwards: the
disagreement is the data, and the scorer has no merge step. With both
filled:

```
python3 experiments/exp_whowhen.py --score-blind <sheetA>,<sheetB>
```

prints agreement, Cohen's kappa, and every case where the two readers differ
on whether a rule was broken. **Those are case E, measured rather than
argued** — and they measure the bias pressure instead of trusting it.

### 1b. SUPPLEMENTARY: an automated blind reader (NOT the human audit)

Run 2026-10-02 as a proxy while the human sheets are unfilled. Reader:
`qwen/qwen3-235b-a22b-2507` @ Alibaba — a different family from the judge
(`openai/gpt-oss-120b`) — temperature 0, **3 samples per case**, shown
exactly what `abstention_blind.csv` shows a human (task, step-numbered
trace, frozen v1 RULES; no label, no ground truth, no method answer). Cost
$0.13. Output: `abstention_blind_LLM.csv` + `_raw.jsonl`. **The human
sheets were not touched and must not be merged with this.**

**An LLM auditing another LLM's abstention is weaker evidence and partly
circular**: reader and judge share training data, reading habits and
failure modes, and both read the same trace through the same rule set. This
cannot establish that an abstention was principled.

Result, and why it does not settle anything:

| proxy verdict | cases |
|---|---|
| no rule clearly violated (abstention supported) | **1** (case 19) |
| rule violated, does NOT explain the failure | **0** |
| rule violated AND explains the failure (abstention unprincipled) | **9** |

Taken at face value this says 9 of 10 abstentions were misses. Three
observations say otherwise:

1. **It names the Orchestrator in 24 of 27 violation samples and cites O8 —
   "report a final answer based on the information gathered" — at or near
   the last step of the trace** (steps 85, 106, 128 …). That is the
   outcome-shaped-rule artifact identified in `NOTE_rulecount_20261002.md`:
   in a run that ended with a wrong answer, O8 is always arguably breached,
   whatever the proximate cause.
2. **It used `explains = N` zero times out of 27 violations.** The
   error-versus-fault distinction the sheet asks for collapsed entirely,
   which is the confound the two-column design exists to catch. A reader
   applying it would be expected to find some non-causal violations.
3. **It agrees with the benchmark label on the agent in 2 of 10 cases and
   on the step in 0 of 10** (case 36: step 88 vs label 9; case 9: 89 vs
   25). So its "violation that explains the failure" is usually not the
   failure the annotators recorded.

**Reading:** this is weak evidence against the abstentions and strong
evidence of the proxy's own bias toward the terminal Orchestrator rule. It
is reported for completeness, not as a result. Sample agreement was 10/10
unanimous, which at temperature 0 measures **determinism, not confidence**.
The human audit remains the gate.

### 2. Natural label sheet — turns agreement into accuracy

`judge_20260922-200108/natural_label_sheet_20260922-200108.csv`, 20 runs of
the scheduling harness. Mark each agent Y/N against its written rules only;
anything else goes in `other_concern`. This sheet is already blind: it
carries no evaluator or judge column.

```
python3 experiments/exp_judge.py --score-labels <sheet>
```

Until it is filled, "the evaluator and the judge agree on 25/26" supports no
claim that either is correct. Second labeller:
`natural_label_sheet_labellerB_10rows.csv` (N000, N003, N009, N010, N013,
N016, N017, N022, N028, N029; `random.Random(20260923)`); pass both sheets
comma-separated for per-agent agreement, kappa and the disagreement list.

### 3. Answered-wrong audit — context, least urgent

`whowhen_abl_20260922-224740/label_audit.csv`, 15 of the 43 cases where the
final M arm answered and disagreed with the label
(`random.Random(20260922)`), scored with `--score-audit`. The share coming
back **both_defensible or neither** is evidence that the benchmark encodes
one annotation convention rather than a fact the trace fixes — section 2.6
from the other direction. The scorer prints that share.

> The older `whowhen_20260922-215346/label_audit.csv` was built from the
> **pilot** (unnumbered steps, `max_tokens` 6,000), superseded by the final
> run; its M arm had 7 abstentions, not 10. Use the sheets above.

## What is not established

- **All six arms are complete** (ABL-3 57/58, one API error on case 7;
  every other arm 57–58/58). ABL-2, ABL-3 and ABL-4 were run later than M,
  B and ABL-1, with identical judge, provider, settings, prompts and norms
  hashes; only wall-clock time differs.
- **The norms row is confounded** with verdict space and output format.
- **One judge, one temperature, one provider.** No repeats, so run-to-run
  variability is unmeasured.
