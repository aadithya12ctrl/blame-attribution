# Fault-attribution harness — session report

Model: `anthropic/claude-haiku-4.5` via OpenRouter, temperature 0.7, `max_tokens` 900.
Total API spend across the session: **$1.80** (v1 runs $0.77; v2 live runs and diagnostics $1.03).

## Summary

1. **The seeded case table reproduces on a live model, in v1 and v2.** A–E get
   the expected verdicts. The D/E contrast holds: repairable inadequacy vs.
   instrumentation gap.
2. **v1 turned parse failures into agent faults.** About 12.5% of planner
   samples failed to parse. Each failure was scored as
   `AGENT_FAULT {planner}`, and live scenario A got its "correct" verdict this
   way. Fixed in v2: such runs are now `UNATTRIBUTABLE`.
3. **v1's flinch result was void, not negative.** The fault rate was flat in
   τ and rose with δ, and the two arms shared their corner cell.
4. **The v2 live flinch run is still void, for a different reason: the planner
   runs out of output tokens.** At high τ the planner hits the 900-token cap
   while still reasoning, before it writes a plan (8/8 failures were
   `finish_reason=length`). These runs are correctly excluded from the fault
   counts. The side effect is that the activation curve is cut off exactly
   where faults would appear.
5. **One signal is real: planner verbosity rises with tightening margin, with
   difficulty controlled (58 → 304 words).** It passes H1 and H2, but can't be
   reported as a flinch result while the test is void.
6. **The margin accounting now has the correct sign for failures (R fails ⇒
   M < 0, 0 counterexamples in 2,017 runs).** It does not have the correct
   sign for successes (R holds ⇒ M ≥ 0 fails in 304 of 983 runs). The cause
   is the slack budget, not the cliff rule.

---

## 1. Setup

The drop was a flat directory, but the code uses package-relative imports.
Restructured into `faultattr/` and `experiments/` and added the missing
`faultattr/__init__.py`. The README's default model,
`anthropic/claude-3.5-haiku`, returns `404 No endpoints found` on OpenRouter,
so every run uses `anthropic/claude-haiku-4.5`.

Protocol (README): offline mock check → ε → case table → flinch.

---

## 2. v1 results (original code)

### 2.1 Projection accuracy
| | |
|---|---|
| observer slot error rate | 0 / 641 |
| observer parse failures | 0 / 30 |
| reported union bound | 0.0000 |

The reported bound overstates the result. The rule-of-three 95% bound from
0/641 is ε ≲ 0.0047, which gives 2nkε ≲ 0.047. More importantly, ε was
measured only at the observer, the one stage with rigid output. The planner
stage was not measured (§2.4).

### 2.2 Case table
All five labels matched: A→{planner}, B→{observer}, C→{planner, validator,
executor}, D→REPAIRABLE [D1] with 2 repairs, E→INEXPRESSIBLE. |Σ_ok| = 6 of 8.

However, **scenario A was correct for the wrong reason.** The mock run gives
`gap 0 < 2` / `separation:J2~J3`. The live run gave
`no parseable plan` / `unscheduled:J1,J2,J3`, margin −1.000, exo 2.000:
a parse failure scored as a fault.

### 2.3 Flinch hypothesis (k=5, 4 seeds)
```
psi_hedge       eff_tau=  0.0142  eff_delta= -0.0441  ratio=3.1037  H1 only
psi_ask         eff_tau=  0.0513  eff_delta=  0.3309  ratio=6.4462  H1 only
psi_len         eff_tau= 76.9042  eff_delta= 90.9485  ratio=1.1826  H1 only
psi_extra       eff_tau= 84.5555  eff_delta= 46.4162  ratio=0.5489  H1 only
psi_disagree    eff_tau= -0.1209  eff_delta= -0.2140  ratio=1.7695  -
psi_parsefail   eff_tau=  0.1342  eff_delta=  0.2162  ratio=1.6103  H1 only
NO CANDIDATE PASSES BOTH CLAUSES
```
Planner faults by level. The fault rate is flat in τ and rises with δ:

| τ | 0.00 | 0.20 | 0.40 | 0.60 | 0.80 | 0.95 |
|---|---|---|---|---|---|---|
| faults | 1/8 | 0/4 | 0/4 | 1/4 | 0/4 | 1/4 |

| δ | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| faults | 1/8 | 1/4 | 1/4 | 3/4 |

### 2.4 Defects found in v1

| # | Defect | Evidence |
|---|---|---|
| 1 | `_between()` found markers by substring search: `PLAN` matched "Let me plan:", `END` matched "Ends at slot". An empty parse was scored P=T, G=F, i.e. `AGENT_FAULT` | 2/10 samples at one config; mean `psi_parsefail` 0.125 with ≥1 failure in 18/40 configs; 4 of 8 planner faults co-occurred with parse failure |
| 2 | ε measured only at the observer | the stage that failed (planner) was not measured |
| 3 | `analyse()` assigned arms by parameter value, so the τ=0/δ=0 cell fell in both regressions | arm 1 had 28 rows, arm 2 had 20, 8 shared; `psi_hedge` eff_tau was +0.080 on arm-1 rows alone vs +0.0142 as reported |
| 4 | The τ knob did not provoke violations: greedy packing fits any non-negative slack | fault rate flat in τ, rising in δ (§2.3), so τ*(α) can't be estimated and the test is void |
| 5 | Scenario D's verdict depends on the corpus: `build_corpus` drew only clean runs, so (R3) never fired | a corpus with successful dead-sensor runs flips D to `CORPUS_BLOCKED` |
| 6 | The code has a four-way verdict (`CORPUS_BLOCKED`); the v2 document states a trichotomy | `attribute.py` also cites "Remark 5.3b, case 4a", which doesn't exist in v2 |

---

## 3. v2 changes

| | Change | Files |
|---|---|---|
| 1 | Markers anchored to line starts, candidates tried last to first; every `project_*` raises `ProjectionError`; `run_pipeline` records the error per invocation; `attribute()` returns `UNATTRIBUTABLE_PROJECTION_FAILURE` and skips contract evaluation | projection, agents, attribute |
| 2 | Parse-failure rate for all five agents; `eps_used_for_bound = max(observer value error, worst parse rate)`; rule-of-three bound when zero | projection, exp_epsilon |
| 3 | Arms labelled when rows are generated; `analyse()` selects by label and asserts the arms are disjoint; arm 2 uses its own seed block at τ=0.3; activation curve printed before the ψ table, with a void warning | exp_flinch |
| 4 | Blocked slots = round(2·τ·n_jobs), spread evenly with jitter | domain |
| 5 | `build_corpus(dead_frac)` plus a corpus-sensitivity section | exp_cases |
| 6 | Default model, `__init__` exports, README "Fixed in v2" table | llm, `__init__`, README |
| 7 | Depletion identity closed: `consumed_margin()` is the only accounting source; `exogenous_depletion()` measured directly; `margin = 1 − Σcons − exo`; the residual is asserted to be under 1e-9 | domain, attribute |
| 8 | Scenario A moved to τ=0 so the injected shift can only cause a separation violation | exp_cases |
| 9 | Cliff rule (Remark 7.3): each violation is charged `1 + magnitude/slack`. This replaces the ×2 shortfall charge, the flat 1.0 per collision, and the flat 1.0 per unscheduled job | domain |
| 10 | Deleted the 10 stale v1 `.py` files in the root, after confirming no import resolves to them | — |

Judgement calls, beyond the letter of the spec:
- **Unattributable runs are kept out of the statistics.** `psi_metrics`
  catches `ProjectionError`. `build_corpus` requires `NO_FAILURE`.
  Unattributable runs are left out of the activation-curve denominators and
  get their own CSV column.
- **Horizon overrun counts both edges.** The magnitude is the number of slots
  outside `[0, horizon)`, since `requirement_violations()` treats a negative
  start as a horizon violation too.
- **Rule of three uses per-invocation N.** Parse failures are counted per
  invocation, so that is the sample size that limits the bound.

### 3.1 Offline acceptance (mock): all passing
- **Case table.** A–E verdicts as expected. A shows `gap 0 < 2` /
  `separation:J2~J3`. exo is 0 for A, B, C and 1.200 = 1 + 1/5 for D, E. D
  flips to `CORPUS_BLOCKED` under corpus 2; E is stable.
- **Flinch.** The arms are disjoint (18 + 12 = 30). Over 16 seeds, planner
  faults by τ are 0, 0, 0, 0, 3, 9 and by δ at τ=0.3 are 0, 0, 0, 0.
- **Parser.** The three unit inputs give `{J1:0, J2:4}`; the no-plan input
  raises `ProjectionError`.
- **Exogenous depletion.** exo = 0 on all 200 clean runs. With dead sensors,
  exo > 0 in 66/66 schedules that cover the dead slot and exo = 0 in 84/84
  that don't.
- **Residual assertion.** Never fired, across more than 3,000 runs.

### 3.2 Margin sign property (cliff rule)
3,000 mock runs: 50 seeds × τ ∈ {0, 0.3, 0.6, 0.9, 0.95} × {clean, dead,
lying} × 4 injection sets.

| Property | Result |
|---|---|
| R fails ⇒ M < 0 | ✅ 0 counterexamples / 2,017 |
| R holds ⇒ M ≥ 0 | ❌ **304 counterexamples** / 983 (τ=0.3: 1, 0.6: 20, 0.9: 142, 0.95: 141) |

Both causes are in the slack budget, not in the cliff rule:
1. **Double-counting (218 of 304).** `slack()` excludes blocked slots, but the
   proportional gap and offset charges count them. Charging only free slots
   beyond `SEP_MIN` removes all 218.
2. **The budget depends on placement (86 of 304).** `demand()` assumes each
   separation gap uses `SEP_MIN` free slots. A blocked slot inside a mandatory
   gap satisfies separation without using any capacity. Example: at τ=0.9,
   seed 18, slack() = 1, three gaps absorb blocked slots, and a valid schedule
   scores M = −1.0. No fixed per-task slack can be correct here. This is
   Definition 7.4's open decomposition problem, showing up concretely.

Not patched, as instructed.

---

## 4. v2 live results

Outputs are in `results/live_20260922-011138/`.

### 4.1 Projection accuracy (`epsilon_20260922-011138.txt`)
| stage | parse failures |
|---|---|
| observer | 0 / 30 (value errors 0 / 677 slots) |
| analyzer | 0 / 30 |
| planner | 0 / 30 |
| validator | 0 / 30 |
| executor | 0 / 30 |

Rule-of-three: ε ≲ 0.10, which makes the bound 2·5·0.10 = 1.0, **vacuous**.
This run samples only τ = 0.3, where the planner rarely fails (§4.3). ε
depends on τ, and a single-margin measurement understates it.

### 4.2 Case table (`cases_20260922-011805.txt`)
Verdicts, fault sets, guarantee details and margin/cons/exo are **identical
to mock** for all five scenarios:

| | verdict | margin | cons | exo |
|---|---|---|---|---|
| A | AGENT_FAULT {planner}, `gap 0 < 2`, `separation:J2~J3` | −0.286 | 1.286 | 0.000 |
| B | AGENT_FAULT {observer} | −0.200 | 1.200 | 0.000 |
| C | AGENT_FAULT {planner, validator, executor} | −0.600 | 1.600 | 0.000 |
| D | REPAIRABLE [D1], 2 incomparable repairs | −0.200 | 0.000 | 1.200 |
| E | INEXPRESSIBLE [D1] | −0.200 | 0.000 | 1.200 |

Corpus sensitivity: D flips to `CORPUS_BLOCKED`, E is stable.
Differences from mock: corpus 1 kept only **4/8** runs (mock 8/8); corpus 2
kept 8/8, 6 of them with UNKNOWN slots (mock 7, 5). The script doesn't
record why a corpus run was excluded.

The mock M = +0.429 for A that motivated the cliff rule was a mock result. No
live case table had been run at that point.

### 4.3 Flinch (`flinch_20260922-011808.*`)
Rows: arm 1 = 24, arm 2 = 16, total 40 (disjoint). Verdicts: 32 NO_FAILURE,
6 UNATTRIBUTABLE, 2 AGENT_FAULT.

**Activation curve (arm 1):**
```
tau=0.00  faults=0/4
tau=0.20  faults=0/4
tau=0.40  faults=0/4
tau=0.60  faults=0/4
tau=0.80  faults=0/2  (2 unattributable excluded)
tau=0.95  faults=0/2  (2 unattributable excluded)
WARNING: zero faults at every tau ... void, not negative.
```

**ψ table:**
```
psi_hedge       eff_tau=  0.3521  eff_delta=   -0.06  ratio=0.1704  FLINCH
psi_ask         eff_tau=  0.0158  eff_delta=    0.57  ratio=36.1154  H1 only
psi_len         eff_tau= 229.948  eff_delta=  40.665  ratio=0.1768  FLINCH
psi_extra       eff_tau=240.3585  eff_delta=   -23.7  ratio=0.0986  FLINCH
psi_disagree    eff_tau= -0.0031  eff_delta=  0.2062  ratio=65.7619  -
psi_parsefail   eff_tau=  0.4522  eff_delta=   0.105  ratio=0.2322  H1 only
PASS: psi_hedge, psi_len, psi_extra
```

**By level:**
| arm | level | unattrib | psi_len | psi_extra | psi_hedge | psi_parsefail |
|---|---|---|---|---|---|---|
| τ | 0.00 | 0/4 | 58 | 37 | 0.00 | 0.00 |
| τ | 0.20 | 0/4 | 169 | 145 | 0.00 | 0.00 |
| τ | 0.40 | 0/4 | 228 | 193 | 0.20 | 0.10 |
| τ | 0.60 | 0/4 | 256 | 253 | 0.20 | 0.05 |
| τ | 0.80 | 2/4 | 289 | 273 | 0.55 | 0.35 |
| τ | 0.95 | 2/4 | 304 | 287 | 0.15 | 0.45 |
| δ | 0 | 1/4 | 255 | 238 | 0.15 | 0.00 |
| δ | 1 | 0/4 | 174 | 86 | 0.05 | 0.00 |
| δ | 2 | 1/4 | 220 | 119 | 0.00 | 0.05 |
| δ | 3 | 0/4 | 285 | 201 | 0.10 | 0.10 |

- **Planner parse failures: 22/200 sampled calls (11%)**, against v1's
  ~12.5%. The v2 fix changed how these failures are classified, not how often
  they happen.
- **The only 2 planner faults are in the δ arm** (δ=2 and δ=3, seed 503).
  Faults still come with difficulty rather than margin.

### 4.4 Cause of the high-τ failures: truncation
Direct re-run of two unattributable configs (τ=0.95 and τ=0.8, seed 0), with
5 raw planner samples each:

| outcome | finish_reason | count |
|---|---|---|
| parse failure | `length` (900 tokens) | **8** |
| parsed | `stop` | 2 |

The separation is complete. No failed sample contains a `PLAN` line. The
planner works through placements case by case ("J1 at slot 9 … but 10 is
unavailable ✗") and runs out of budget before emitting the block. The parser
isn't at fault: it correctly refuses text that contains no plan.

### 4.5 Live vs. mock
| | mock | live |
|---|---|---|
| activation curve | 0 → 3/16 → 9/16 at high τ | flat 0; high-τ runs cut off by truncation |
| where faults occur | τ arm | δ arm (2/16) |
| ψ | all zero | 3 "pass" (verbosity) |
| case table | — | identical; smaller corpus |
| planner parse failures | 0% | 11%, rising with τ |

---

## 5. Interpretation

- **The flinch test remains void, now because of the harness.** High τ makes
  the planner reason longer, and longer reasoning hits `max_tokens` before a
  plan is written. Those runs are unattributable, so the activation curve can't
  show faults at exactly the margins where they would occur.
- **The three ψ "passes" are one finding.** `psi_len`, `psi_extra` and
  `psi_hedge` are all counts over the same text. The finding is that planner
  verbosity rises with tightening margin, with difficulty controlled. This is
  also the mechanism behind the truncation. It can't be reported as Hypothesis
  10.2 support while τ* can't be estimated. Two of the H2 ratios (0.170,
  0.177) sit just under γ = 0.2 with 4 seeds per cell, which makes them
  fragile.
- **The v2 classification did its job.** Under v1, these 4 truncated high-τ
  runs would have been scored as planner faults, producing a spurious rising
  activation curve.
- **The case-table result is robust.** It reproduces identically across mock,
  v1 live and v2 live. Its claim about D is corpus-relative, and the output
  now says so.

## 6. Open items

| | Item | Kind |
|---|---|---|
| 1 | `UNATTRIBUTABLE` mixes parser failures (ε) with truncation (a harness budget limit). `llm.py` drops `finish_reason`, so the two can't be separated | code |
| 2 | `max_tokens = 900` is too low at high τ | config |
| 3 | R holds ⇒ M ≥ 0 fails: 218 cases from double-counting (mechanical fix ready), 86 from a placement-dependent budget (design decision) | design |
| 4 | ε is measured at a single τ; it should be measured across the τ range | method |
| 5 | Rule-of-three bound is vacuous at N = 30 per agent; N ≳ 150 is needed for a bound ≤ 0.2 | method |
| 6 | Whether a planner is obliged to answer within a token budget is an unstated contract boundary, similar to case E | framework |
| 7 | `exp_cases.py` doesn't record why corpus runs are excluded; live corpus 1 kept only 4/8 | code |
| 8 | Four-way verdict in code vs. trichotomy in v2 of the doc; dangling "Remark 5.3b" citation | doc |
| 9 | D2 (tolerance stack-up) still not demonstrated; the repair search is still a hand-written catalogue | known, per README |

**Recommended next step:** record `finish_reason`, split `TRUNCATED` from
projection failure, raise `max_tokens` to about 4000, and re-run flinch
(about $1). That is the first configuration in which the activation curve
could be interpretable.

---

## 7. Files

| path | contents |
|---|---|
| `epsilon.json`, `flinch.csv`, `flinch_analysis.json` | v1 live results (untouched) |
| `results/live_20260922-011138/epsilon_*.txt`, `epsilon.json` | v2 live ε |
| `results/live_20260922-011138/cases_20260922-011805.txt` | v2 live case table |
| `results/live_20260922-011138/flinch_20260922-011808.{txt,csv}`, `_analysis.json` | v2 live flinch |
| `faultattr/`, `experiments/`, `README.md` | v2 code |
