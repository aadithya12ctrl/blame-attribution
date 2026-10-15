# Does blame follow rule count, or role centrality?

Dated 2026-10-02. Pre-registered in `PREREG_rulecount_20261002.md` (sha256
`39f03847…1364`, hashed before the norm sets were built and before any arm
ran). Results: `whowhen_abl_20261002-113814/`. Cost $1.25 of a $4 cap
(dry run $0.06, three arms $1.19). All 58 cases in every arm, **no
infrastructure failures**.

## Answer: role centrality, not rule count. The earlier interpretation was wrong.

The pre-registered test was whether the Orchestrator's answer share in
N-WEB falls below 60%. **It rose to 77%, with only 2 rules to its name,
while WebSurfer — holding 8 — took 19%.**

| arm | rules O / W | coverage | agent acc | step acc | **Orch share** | **Web share** | abstentions |
|---|---|---|---|---|---|---|---|
| B (no norms) | — | 1.00 | **0.439** | 0.211 | 42% | 35% | 0 |
| ABL-1 (no norms, +GT) | — | 1.00 | 0.414 | **0.241** | 47% | 31% | 0 |
| **N-BAL** | 3 / 3 | 0.71 | 0.293 | 0.121 | **56%** | **34%** | 15 |
| **N-ORCH** | 8 / 2 | 0.76 | 0.345 | 0.103 | **75%** | **20%** | 10 |
| **N-WEB** | 2 / 8 | 0.53 | 0.207 | 0.103 | **77%** | **19%** | 24 |
| M (v1) | 8 / 4 | 0.79 | 0.310 | 0.069 | 72% | 24% | 10 |
| ABL-2 (v2) | 6 / 4 | 0.60 | 0.224 | 0.086 | 69% | 26% | 22 |
| ABL-3 (v1, no GT) | 8 / 4 | 0.68 | 0.246 | 0.123 | 69% | 26% | 9 |
| ABL-4 (v3) | 8 / 4 | 0.83 | 0.345 | **0.190** | 83% | 15% | 2 |

Label base rates on these cases: **WebSurfer 57%**, Orchestrator 31%,
Coder 7%, FileSurfer 5%, ComputerTerminal 0%.

### H1 (rule count drives blame): refuted on both of its predictions

1. **The heavy agent's share was not highest in its own arm.** WebSurfer's
   share is *lowest* in the WebSurfer-heavy arm: 19% in N-WEB against 34% in
   balanced N-BAL. Multiplying its rules by four, and cutting the
   Orchestrator's from 8 to 2, moved blame *away* from WebSurfer.
2. **N-WEB did not raise agent accuracy.** Predicted above M's 0.310;
   observed **0.207**, the lowest of all nine arms. WebSurfer recall fell
   from 7/33 (N-BAL, N-ORCH, M) to **3/33**.

### H2 (role centrality drives blame): supported, with one clause unmet

- Orchestrator share ≥ 60% in N-ORCH (75%) and N-WEB (77%), **independent of
  its rule count**.
- In N-BAL it is **56%**, just under H2's stated 60% threshold, so the "all
  three arms" clause fails as written. But with rule counts *equal*, blame
  is still inverted relative to the labels: the Orchestrator takes 56%
  against a 31% base rate, WebSurfer 34% against 57%. Centrality, not
  parity of specification, decides the direction.
- Agent accuracy is not flat (0.207–0.345), so the third H2 clause is also
  only partly met. The ordering is not explained by rule count either, since
  N-ORCH (0.345) and N-BAL (0.293) straddle M (0.310).

**Verdict: H1 refuted; H2 supported on its primary criterion.** The honest
statement is the negative one — *the Orchestrator's blame share does not
track its rule count* — plus the positive fragment that role position does.

## Correction to the earlier finding

`NOTE_whowhen_20260923.md` reported that norms concentrate blame on the
"most heavily specified agent" and offered specification density as the
mechanism: more rules, more ways to be found in breach. **That mechanism is
now refuted.** Rule count was never manipulated there; this experiment
manipulates it and the effect does not follow. The surviving facts are:

- adding written norms at all roughly doubles the Orchestrator's excess over
  its base rate (42–47% without norms, 56–83% with them);
- *which* agent absorbs the blame is set by role position, not by how many
  rules it has.

The amended claim is **"norms concentrate blame on the most central agent"**,
and specification density should be dropped as the explanation.

## Rule count does do something: it moves coverage, not blame

| arm | WebSurfer rules | abstentions | coverage |
|---|---|---|---|
| N-ORCH | 2 | 10 | 0.76 |
| N-BAL | 3 | 15 | 0.71 |
| N-WEB | 8 | **24** | **0.53** |

Giving the peripheral agent more rules made the judge **abstain more**, not
blame it more. N-WEB has the lowest coverage of any norms arm.

**Provisional mechanism.** The two role's rules differ in kind, not only in
number:

- The Orchestrator's are **outcome-shaped** — assess whether the request is
  satisfied, detect stalls, re-plan, report a final answer. In a run that
  ended with a wrong answer, at least one of these is always arguably
  breached, whatever the proximate cause.
- WebSurfer's are **action-selection** — map the request to one action, pick
  navigation vs clicking vs reading, report the new page state. The actual
  WebSurfer failures in this benchmark are retrieval-*quality* failures
  ("did not return anything useful", "the keyword was insufficient"), which
  no action-selection rule forbids. Splitting them into eight narrower rules
  gave the judge more rules it could not cite, so it abstained.

That is §1.5(b) again, from a new direction: the norm the labels rely on —
*retrieve information that is adequate for the task* — is in nobody's
documentation, so no faithful norm set contains it, however finely sliced.

## A result that cuts against the judge's blame pattern

Precision when an agent is named (correct / times named):

| arm | Orchestrator | WebSurfer |
|---|---|---|
| N-BAL | 9/23 = 0.39 | **7/14 = 0.50** |
| N-ORCH | 12/33 = 0.36 | **7/9 = 0.78** |
| N-WEB | 9/24 = 0.38 | 3/6 = 0.50 |

**The judge's WebSurfer answers are more often right than its Orchestrator
answers, in every arm — it just makes far fewer of them.** In N-ORCH it was
right 7 times out of 9 when it named WebSurfer, and 12 out of 33 when it
named the Orchestrator. The concentration on the Orchestrator is not
explained by the Orchestrator's answers being better.

## Norm sets, and what constrains them

| set | sha256 | rules per agent | total |
|---|---|---|---|
| N-BAL | `7fc4cb8b…c972` | O 3, W 3, F 3, C 3, T 3 | 15 |
| N-ORCH | `56946b65…6349` | O 8, W 2, F 2, C 2, T 2 | 16 |
| N-WEB | `edf82bd4…b101` | O 2, W 8, F 2, C 2, T 2 | 16 |

All three derive from the frozen **v1** norms (`dab067b8…0ac9`, written and
hashed before any failure record was downloaded) by **granularity changes
only**: adjacent rules merged, or a rule split along an enumeration already
in the cited documentation — for N-WEB, the action space the paper lists
(navigation: visit a URL, search, scroll; page actions: click, type;
reading: summarize, answer). No new obligation was introduced. Each file
carries a rule-by-rule derivation table, which the judge never sees
(verified). Counts match the pre-registration exactly.

**Disclosure, carried over from the pre-registration.** The author of these
sets had already read the label distribution and many annotated
`mistake_reason` strings in an earlier session, so "written without having
seen any failure log" does not hold. The granularity-only constraint plus
the derivation tables are the mitigation; an author who never saw the data
is the check that was not available. Note that the contamination would, if
anything, have biased N-WEB *toward* working — and it did not.

## Limits

- One judge, one temperature, one provider, no repeats: run-to-run
  variability unmeasured.
- Coverage differences mean the arms' accuracy figures rest on different
  numbers of answered cases (31–44 of 58). The common set here is all 58,
  since no arm lost a case to infrastructure.
- The norms remain prose recovered from documentation, not predicates over
  typed state.
- Centrality is not manipulated, only rule count. A test of centrality
  itself would need a system where a peripheral agent holds the
  completion-deciding role.
- The abstention mechanism above is an interpretation of the rules' *kind*,
  not a measurement of it.
