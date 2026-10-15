# Pre-registration — does blame follow rule count, or role centrality?

Written and hashed **before the three norm sets were built and before any
arm was run**. Dated 2026-10-02.

## Question

Earlier result (NOTE_whowhen_20260923.md): every arm given written norms
named the Orchestrator in 69–83% of answers, against a 31% label base rate,
while neither arm without norms exceeded 47%. The interpretation offered was
**specification density** — the Orchestrator holds 8 of v1's 22 rules, and
more rules mean more ways to be found in breach. **Rule count was never
manipulated**, so that interpretation is untested: the Orchestrator is also
the most *central* role (it plans, delegates, decides completion), and
centrality alone could explain the same pattern.

This experiment manipulates rule count per agent, holding roles, cases,
judge, temperature and prompt format fixed.

## Arms

Three new norm sets, same five Magentic-One roles, same 58 Hand-Crafted
cases, same judge (`openai/gpt-oss-120b` @ Cerebras, temperature 0), same
prompt as arm M (norms + ground truth, open verdict, JSON, printed steps):

| arm | norms | rules per agent | total |
|---|---|---|---|
| N-BAL | balanced | O 3, W 3, F 3, C 3, T 3 | 15 |
| N-ORCH | orchestrator-heavy | **O 8**, W 2, F 2, C 2, T 2 | 16 |
| N-WEB | websurfer-heavy | O 2, **W 8**, F 2, C 2, T 2 | 16 |

Label base rates on these 58 cases: **WebSurfer 33/58 = 57%**, Orchestrator
18/58 = 31%, Coder 4/58 = 7%, FileSurfer 3/58 = 5%, ComputerTerminal 0.

## Predictions, stated before results

**H1 — rule count drives blame.** Then:
- the heavy agent's answer share is **highest in its own arm**: Orchestrator
  share greatest in N-ORCH, WebSurfer share greatest in N-WEB;
- shares move monotonically with rule count across the three arms;
- **N-WEB raises agent accuracy above M (0.310)**, because WebSurfer is the
  true label in 33/58 cases, so pushing blame toward WebSurfer pushes it
  toward the labels;
- N-ORCH accuracy is at or below M.

**H2 — role centrality drives blame.** Then:
- the **Orchestrator share stays high in all three arms** (taken here as
  ≥ 60% of answers) regardless of rule count, including in N-WEB where it
  has only 2 rules;
- WebSurfer's share stays well below its 57% label base rate even in N-WEB;
- agent accuracy is roughly flat across the three arms.

**Mixed outcome.** Shares move in H1's direction but the Orchestrator
remains the modal answer in N-WEB: both factors operate, and the earlier
"specification density" claim must be stated as partial.

**Decision rule.** Primary comparison: WebSurfer and Orchestrator answer
shares across N-BAL, N-ORCH, N-WEB. Secondary: agent accuracy of N-WEB
versus M. H1 and H2 are distinguished by whether the Orchestrator share in
N-WEB falls below 60%.

## Fixed before results

- Headline numbers include cases 20, 22 and 49 (label step belongs to
  another agent); a sensitivity figure excludes them.
- Infrastructure failures — API errors, truncation, context overflow — are
  excluded and reported, never scored as model behaviour.
- A case that cannot fit the judge's context in any arm is excluded from
  every arm and listed.
- Coverage, agent accuracy and step accuracy are reported on all scorable
  cases (abstention and parse failure count as wrong) and on answered cases.
- Existing arms (M, B, ABL-1..4) are reported alongside for context, not
  re-run.

## Norm-set construction, and a disclosure

**Disclosure.** The model writing these norm sets has already read, in this
session, the Who&When label distribution and many annotated
`mistake_reason` strings. It therefore cannot satisfy "write the norms
without having read any failure log". Writing eight fresh WebSurfer rules
from scratch would risk encoding the failure modes already seen, which is
precisely the bias H1 predicts a WebSurfer-heavy set would create.

**Mitigation, binding on construction.** All three sets are derived from the
frozen **v1** norms (`faultattr/norms/magentic_one.md`, sha256
`dab067b8…0ac9`, written and hashed before any record was downloaded) by
**changing granularity only**:

- to *reduce* an agent's count, adjacent v1 rules are **merged**, keeping
  their obligations and their source citations;
- to *increase* an agent's count, a v1 rule is **split along an enumeration
  that already appears in the cited documentation** (for example the
  WebSurfer action space the paper lists: navigation — visit a URL, web
  search, scroll; page actions — click, type; reading — summarize, answer
  questions);
- no new obligation is introduced, and no rule is reworded to describe a
  failure mode;
- every rule in every set records which v1 rule(s) it came from and by
  which operation (split or merge).

The derivation table is part of each norms file, so faithfulness can be
checked against v1 and against the documentation without trusting the
author.

**Residual risk, stated rather than solved.** Granularity allocation is
still a post-data choice made by a contaminated author. The check available
is the audit trail above; the check not available is an author who never saw
the data.
