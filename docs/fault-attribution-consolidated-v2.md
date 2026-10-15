# Fault and Fault Attribution in Agentic Systems

A consolidated statement of the problem, the definition, and the formal treatment.

**Revision note.** This version repairs ten coherence defects found in the previous draft. The substantive ones: preconditions are now trace predicates (they were typed inconsistently with guarantees); severity is split into violation magnitude and consumed margin (one symbol was doing two incompatible jobs, which made D2 unsatisfiable); and the dichotomy is now a trichotomy (there was no branch for an unrepairable contract set). §12.2 lists all ten.

**Status.** Conceptual and formal work. No implementation, no measurements. Claims marked **[open]** are unproved.

---

# Part 0 — What this addresses

## 0.1 In one paragraph

When a multi-agent LLM system fails, existing methods try to infer from the execution trace which agent was responsible, and reach 14–36% step-level accuracy. This document argues the ceiling is structural rather than a modelling deficiency: correctness is not a property of a trace, so a trace-only method has nothing to check against. It defines fault instead as **violation of a stated obligation**, making attribution a checking problem rather than an inference problem, and yields three things no existing method produces — a set-valued verdict under overdetermination, the verdict *"no agent is at fault; the specification is insufficient"* with the missing obligation as output, and the verdict *"the specification cannot be repaired with the information the system captures."*

## 0.2 The conceptual claim, in one line

> Fault attribution is not an inference problem. It is a derivation from a norm — and where no norm was stated, the question has no answer to infer.

## 0.3 What is claimed

| Claim | Status |
|---|---|
| Trace-only attribution has a structural ceiling | argued §1.5; testable via §2.6 |
| Fault is well-defined as violated obligation | Definition 4.1 |
| Every failure yields a verdict of one of three kinds | **Theorem 5.2** |
| The repair output must be set-valued | **Theorem 6.6** |
| Composition faults split by margin accounting | Definitions 7.7–7.8 |
| Latent violations can be provoked, not just awaited | §9, conditional on **[open]** 10.2 |
| Unstated preconditions are discoverable | §10.5, conditional on **[open]** 10.2 |

## 0.4 Borrowed versus contributed

**Borrowed wholesale — cite, do not claim:**

- Assume-guarantee reasoning; rely-guarantee for concurrency; design by contract
- Fault / error / failure taxonomy (Avižienis et al.)
- Abductive and model-based diagnosis (Reiter; de Kleer & Williams)
- Runtime verification; monitorable temporal logic
- Specification mining; active automata learning
- Tolerance stack-up and error-budget analysis

**Contributed:**

1. **Application** — contract-based attribution for LLM multi-agent systems, where the norms were never written down. The formalism is old; nothing in the attribution literature uses it.
2. **The trichotomy (Theorem 5.2)** — `Φ = ∅` reframed from *absence of verdict* into a positive finding about the specification, with an explicit witness, and separated from the case where no repair exists at all.
3. **Necessity of set-valued output (Theorem 6.6)** — proved from the existential structure of the repair condition, not asserted from general properties of abduction.
4. **D1/D2 by margin accounting** — missing obligation versus tolerance stack-up, distinguished by whether consumed margin explains the failure. They require different repairs and any Boolean treatment conflates them.
5. **Consumed margin as the aggregation quantity (§7.4)** — pushing non-linearity into the geometry of `R` so aggregation stays linear and auditable.
6. **Activation and discovery (§9–10)** — margin ramping to provoke latent violations in order, with a difficulty control that makes the strain signal falsifiable.

The definition of fault is **not** new as mathematics. It is new as an answer to *"what is a fault in an agentic system"* — a question the field has answered only by annotation convention.

---

# Part I — The Problem

## 1.1 Two questions

**Failure attribution** — which agent's action produced the observed failure? A question about causal history.

**Fault attribution** — which agent violated an obligation it was required to meet? A question about conformance to a norm.

These come apart constantly: an agent can cause a failure while meeting every obligation (it was handed bad input), and can violate an obligation without causing any failure (something downstream caught it).

The field's benchmarks sit somewhere between the two. Who&When's *decisive step* annotation is closest to *earliest sufficient cause* — a causal notion with a normative element smuggled in via what annotators judge should have been caught. The point is not that the field is confused about which question it asks, but that the two are evaluated against a single convention that satisfies neither cleanly.

**This document is about fault attribution.**

## 1.2 A third question hidden in both

1. **Where did this come from?** — provenance / lineage
2. **Which change mattered?** — selection / consequence
3. **Was it wrong?** — correctness / fault

Provenance methods answer (1). Anomaly and spectrum methods answer (2). Neither answers (3), and (3) is the question.

## 1.3 Where the field stands

| Result | Agent-level | Step-level |
|---|---|---|
| Who&When original baselines (ICML 2025) | 53.5% | 14.2% |
| Spectrum-based (FAMAS) | 57.6% | 29.4% |
| Causal-inference method | — | up to 36.2% |
| TraceElephant, full observability | 65.9% | 30.3% |

Some published methods perform below random.

## 1.4 The observability result, and its limit

Who&When supplies output-only traces — agent outputs without task instructions, prompts, or contextual messages. Full traces improve step-level attribution by ~76% relative, with a further ~10% from access to the running environment.

Instrumentation beats inference. But it plateaus near 30%.

## 1.5 Why trace-only methods stall

**(a) Correlational, not causal.** Judges blame the loudest symptom. The step that *executes* a harmful action is usually not the step that *decided* on it. *Partially fixable with more context.*

**(b) No norm in the trace.** Correctness is not recoverable from a trace. An output looks acceptable unless you know the threshold it had to satisfy, and that threshold lives in a specification, not a span. Supplying the norm in the prompt is writing a contract — informally, re-derived every run. *Not fixable.*

**(c) The answer format forecloses the correct answer.** Asked "which agent is at fault," a model always names one. When the correct answer concerns the specification rather than any agent, that answer is not in the response space. *Not fixable.*

## 1.6 Central claim

> Existing benchmarks oversample the region where fault attribution is **underdetermined in principle** — no fact about the trace fixes a unique answer, because the standard against which the trace would be judged was never stated.

About **oversampling**, not universality. Many benchmark failures are determinate; those are the easy ones, and progress on the aggregate metric is bounded by the rest.

Testable — §2.6.

---

# Part II — What a Fault Is

## 2.1 Vocabulary

- **Fault** — the underlying defect. Latent. May never activate.
- **Error** — the fault activated; system state is now incorrect.
- **Failure** — the error reached the system boundary; behaviour is observably wrong.

Two consequences the "which agent, which step" framing cannot express: a fault can exist in an agent that never produced a visible error, and an agent can produce an error that never becomes a failure.

## 2.2 Cases any definition must handle

| | Case | Description |
|---|---|---|
| **A** | Direct violation | Assumptions met, output violates a stated constraint. |
| **B** | Inherited drift | Upstream agent emits corrupted state; downstream agent produces the visibly broken artifact. |
| **C** | Overdetermination | Two independently sufficient errors. Repairing either leaves the failure. |
| **D** | All-clear failure | Every agent satisfies its obligations; the system fails anyway. |
| **E** | Contested boundary | Whether an agent was obliged to validate its input is itself undecided. |

B is a large part of the 14% — judges blame the visible artifact. C defeats counterfactual methods, which return *nobody*. D defeats every method that must name an agent. E has no answer until someone states one.

## 2.3 A worked instance

A restaurant order; the customer receives a dish they are allergic to.

| Role | Assumes | Guarantees |
|---|---|---|
| Customer | menu is accurate | states known allergies |
| Waiter | allergies were stated | ticket matches what was said |
| Kitchen | ticket is accurate | dish matches ticket |
| Runner | dish matches ticket | delivers to correct table |

- **B:** the waiter omits the allergy note. The kitchen holds the dangerous dish and cooked it correctly from the ticket it was given. Its assumption failed; **fault: waiter.** Blame the visible artifact and you retrain the kitchen while the front of house stays broken.
- **C:** the waiter omits the note *and* the runner delivers to the wrong table. Neither error is necessary; counterfactual reasoning attributes to nobody. **Fault: {waiter, runner}.**
- **D:** the customer has an unmentioned allergy, the menu did not list the ingredient, and every role performed its stated duty. **Nobody was ever obliged to ask.** Firing the waiter does not prevent recurrence.
- **E:** should the kitchen have queried a table with three allergy-modified dishes and one unmarked? Both policies defensible; no review of the evening settles it.

## 2.4 Candidate definitions

**Deviation from specification** — clean, checkable, no counterfactual. Fails when specifications are prose.

**Counterfactual necessity** — what most methods implicitly assume. Fails on **C**.

**Earliest sufficient cause** — roughly what Who&When encodes. Requires a total order over steps that concurrent agents lack. "Unavoidable" needs a recovery model — unavoidable *given nobody caught it* makes the missing check the fault.

**Cheapest repair** — matches what a debugging engineer wants. Fails as a definition: a property of the repair budget, not the run.

## 2.5 What the fourth reveals

Attribution is not recovery of a fact. It is **selection of a repair target under a cost model**.

| Question actually asked | Definition implied |
|---|---|
| Who violated their contract? | deviation |
| What do I change to ship a fix? | cheapest repair |
| What made this inevitable? | earliest sufficient cause |

The field reports one accuracy number against one annotation convention.

## 2.6 The divergence measurement

§1.6 is checkable. For each benchmark failure, attribute under each definition and record agreement.

**Only three of the four are computable on existing benchmarks.** *Deviation from specification* requires specifications, which benchmark failures do not carry. The comparison is therefore between counterfactual necessity, earliest sufficient cause, and the benchmark's own annotation — with *deviation* available only on instrumented systems of your own.

This is a real limitation of the experiment and must be stated in any writeup. It does not weaken the test: if the three computable definitions already diverge substantially, the underdetermination claim holds a fortiori, since adding a fourth can only add divergence.

- **High divergence** → the benchmark samples underdetermined failures; its metric measures agreement with a convention rather than correctness.
- **Low divergence** → the claim is wrong and the stagnation needs another explanation.

Either outcome is a result. Requires no new machinery.

## 2.7 The definition adopted

> **A fault is a violated obligation.**
>
> An agent is at fault when its assumptions held and its guarantee did not.

## 2.8 Relativity, stated as a feature

Attribution is **relative to the contract set**. Every method is relative to something — an annotator's convention, a judge's learned prior. That dependence is normally hidden. Here it is explicit and arguable.

---

# Part III — Formal Treatment

## 3. System model

### 3.1 States and agents

`Σ` — typed states, each a finite map from typed fields to values.
`A = {a₁, …, aₙ}` — agents, each with input domain `In_a` and output domain `Out_a`, projections of `Σ`. Agents may be stochastic.

### 3.2 Runs and histories

A **run** `ρ` determines, for each invocation, an actual input and output. Write:

```
ins_a(ρ) ∈ In_a*                  a's input history
h_a(ρ)   ∈ (In_a × Out_a)*        a's full invocation history
```

`ins_a(ρ)` is the projection of `h_a(ρ)` onto inputs. No assumption about topology; the definitions never reference execution order across agents.

### 3.3 Requirement

`R ⊆ Runs`. A run **fails** iff `¬R(ρ)`.

### 3.4 Contracts

```
P_a ⊆ In_a*                     precondition — over a's input history
G_a ⊆ (In_a × Out_a)*           guarantee — over a's full history
```

**Both are trace predicates.** The previous draft typed `P_a` over a single input while `G_a` ranged over histories, which left `fault` undefined for agents invoked more than once. Monitorable temporal logic supplies the syntax for both.

Single-invocation contracts are the special case where the predicate constrains only the last element.

**Expressibility.** `G_a` must be a predicate on `(In_a × Out_a)*` only. An agent cannot be obliged over information it never receives. Used in §6.8.

## 4. Fault

### Definition 4.1 (Fault)

```
fault_C(a, ρ)  ⟺  P_a(ins_a(ρ))  ∧  ¬G_a(h_a(ρ))
```

Both arguments are histories. Well-typed for any number of invocations.

### Definition 4.2 (Fault set)

```
Φ_C(ρ)  ≜  { a ∈ A : fault_C(a, ρ) }
```

### Definition 4.3 (Conformance)

```
Conf(C)  ≜  { ρ : Φ_C(ρ) = ∅ }
```

Every agent either had its precondition violated, or met its guarantee.

### Remark 4.4 (Locality, precisely)

`fault_C(a, ρ)` depends only on `⟨h_a(ρ), C(a)⟩`.

Evaluation never reasons **across agents**, requires no counterfactual execution, and needs no total order over concurrent steps. It does require carrying monitor state per agent over time.

This is **local per agent over time**, not local per invocation — the cost of trace predicates.

### Remark 4.5 (What is absent)

No reference to causal history. Faults are evaluated against contracts, not against what happened next.

| Clause | Effect | Case |
|---|---|---|
| `P_a(ins_a)` | bad input ⟹ no fault | **B** |
| `¬G_a(h_a)` | contract violation, not causal contribution | **A** |
| set-valued `Φ` | all violators returned | **C** |
| no counterfactual | no replay, no ordering | **C** |

## 5. The trichotomy

### Definition 5.1 (Adequacy)

`C` is **adequate** for `R` iff `Conf(C) ⊆ R`.

This replaces the informal `⊨ (⋀ᵢ Gᵢ) → R`, which is ill-typed: the `G_a` are predicates over distinct local domains and do not conjoin into a run predicate without the conformance construction.

### Theorem 5.2 (Trichotomy of verdicts)

For every failing run `ρ`, exactly one of the following verdicts holds:

1. **Agent fault.** `Φ_C(ρ) ≠ ∅` — the fault set names the violating agents.
2. **Repairable inadequacy.** `Φ_C(ρ) = ∅` and `Rep(C, ρ, Σ_ok) ≠ ∅` — no agent violated its contract; `C` is inadequate for `R` with `ρ` as witness, and at least one expressible repair exists.
3. **Instrumentation gap.** `Φ_C(ρ) = ∅` and `Rep(C, ρ, Σ_ok) = ∅` — no agent violated its contract, and no strengthening expressible over any agent's observable history excludes `ρ`. The information needed is not captured by the system.

**Proof.** The cases partition on `Φ_C(ρ) = ∅` and, within that, on `Rep = ∅`, so they are exhaustive and mutually exclusive as verdicts for `ρ`.

For 2 and 3: `Φ_C(ρ) = ∅` gives `ρ ∈ Conf(C)` and `¬R(ρ)` gives `ρ ∉ R`, so `Conf(C) ⊄ R` and `C` is inadequate, witnessed by `ρ`. ∎

### Remark 5.3 (Scope of the exclusivity)

The trichotomy classifies the **verdict for `ρ`**, not the global status of `C`. Case 1 does not assert that `C` is adequate — a contract set may have a violator on this run and still be inadequate on others. The previous draft's "exactly one" was ambiguous on this point and, read as a claim about adequacy, false.

### Remark 5.4 (Why this is not vacuous)

`Φ = ∅ ∨ Φ ≠ ∅` is trivial. The content is that `Φ = ∅` is **not an absence of verdict**, and that it further resolves into a repairable case and an unrepairable one — a distinction with direct operational meaning. Case 3 says *change what the system records*, not *change what the agents promise*.

Every failure yields information. No failure is unattributable.

## 6. Repair as abduction

### Definition 6.1 (Contract order)

```
C' ⊑ C   ⟺   ∀a :  P'_a ⊇ P_a   ∧   G'_a ⊆ G_a
```

`C'` is **at least as demanding**: it assumes less and guarantees more.

### Lemma 6.2 (Monotonicity)

`C' ⊑ C ⟹ ∀ρ : Φ_C(ρ) ⊆ Φ_{C'}(ρ)`.

**Proof.** Let `a ∈ Φ_C(ρ)`: `P_a(ins_a)` and `¬G_a(h_a)`. From `P'_a ⊇ P_a`, `P'_a(ins_a)`. From `G'_a ⊆ G_a`, `¬G'_a(h_a)`. ∎

**Corollary.** `Conf(C') ⊆ Conf(C)`.

### Remark 6.3 (The order is two-sided)

| Change | Effect on `Φ` |
|---|---|
| **shrink** `G_a` (guarantee more) | `Φ` **grows** |
| **shrink** `P_a` (assume more) | `Φ` **shrinks** |

Strengthening a *precondition* **excuses** an agent. This is why Definition 6.1 requires `P'_a ⊇ P_a`. Reversing it inverts every result below.

### Definition 6.4 (Repair problem)

Given `C`, witness `ρ*` with `Φ_C(ρ*) = ∅ ∧ ¬R(ρ*)`, and corpus `Σ_ok` of runs satisfying `R` and conformant under `C`, a **repair** is `C'` with:

```
(R1)  C' ⊑ C
(R2)  ρ* ∉ Conf(C')                the witness is now attributed
(R3)  Σ_ok ⊆ Conf(C')              past successes remain conformant
(R4)  every G'_a expressible over (In_a × Out_a)*
```

### Lemma 6.5 (Vacuous repairs excluded)

If `Σ_ok ≠ ∅`, `G'_a = ⊥` is not a repair for any `a` invoked in some `ρ ∈ Σ_ok` under a satisfied precondition.

**Proof.** Such a `ρ` yields `fault_{C'}(a, ρ)`, violating (R3). ∎

The filter is **empirical, not normative** — it imports no cost model, which matters because a cost model would reintroduce the "cheapest repair" definition rejected in §2.4.

**Caveat.** Agents never exercised in `Σ_ok` are unprotected. **Corpus coverage is a precondition of the method and must be reported.**

### Theorem 6.6 (Non-uniqueness)

Minimal (`⊑`-maximal) repairs are in general not unique, and `Rep` is not closed under the least-demanding upper bound of two of its elements.

**Proof sketch.** (R2) unfolds to an **existential over agents**:

```
∃a :  P'_a(ins_a(ρ*))  ∧  ¬G'_a(h_a(ρ*))
```

A repair need only catch `ρ*` at one agent. Construct `C₁` strengthening only `G_a` and `C₂` strengthening only `G_b`, `a ≠ b`, each minimal and satisfying (R1)–(R4). They differ on disjoint components, so neither is `⊑` the other. Their least-demanding common weakening restores both toward the original, satisfying neither disjunct — so `ρ* ∈ Conf(C₁ ⊔ C₂)` and (R2) fails. ∎

### Corollary 6.7

The correct output is `max_⊑ Rep(C, ρ*, Σ_ok)` — the **set** of minimal repairs.

A theorem, not a hedge. Any method returning a single missing obligation is making an unstated choice among incomparable alternatives.

### 6.8 Ownership

Each `C' ∈ max_⊑ Rep` identifies `Own(C') = { a : C'(a) ≠ C(a) }` — candidate owners.

(R4) prunes on **feasibility**: if the distinction needed to catch `ρ*` is not a function of `a`'s observable history, no expressible `G'_a` exists and `a` cannot own the obligation regardless of policy.

When (R4) fails for **every** agent, `Rep = ∅` and Theorem 5.2 case 3 applies.

**Evidence settles feasibility. It does not settle selection among feasible candidates.** **[open]** — no selection rule is claimed.

### 6.9 One underdetermination, two boundaries

- *Where does the `P`/`G` boundary sit between adjacent agents?* — choice of `C` before the run (**case E**)
- *Who owns a new obligation after a composition fault?* — choice within `max_⊑ Rep` after (**§6.8**)

Both are selections of a point in the `⊑` lattice not determined by any run. The framework relocates the choice from an annotator's silent per-run judgment to an explicit artifact decided in advance. **It does not make the choice.**

## 7. Two graded quantities

Definition 4.1 is Boolean. Two distinct real-valued quantities are needed, and conflating them was the previous draft's central defect.

### Definition 7.1 (Violation magnitude)

For `a ∈ Φ_C(ρ)` and a metric `d_a` on histories:

```
sev(a, ρ) ≜ inf { d_a(h_a(ρ), h) : G_a(h) }
```

Distance from the actual history to the nearest conforming one. **Defined only for agents at fault**, and zero exactly when the agent conforms.

Used to grade violations in cases 1 of Theorem 5.2. **Not usable for D2**, since it vanishes identically when `Φ = ∅`.

### Definition 7.2 (Visibility)

Let `h*` attain the infimum. `vis(a, ρ)` is the distance between the downstream input actually produced and the one `h*` would have produced — the size of the **immediate disturbance**.

### Remark 7.3 (Why distance-to-conforming is the wrong aggregation quantity)

System requirements are rarely smooth. A schedule at 119s against a 120s minimum is not 1% worse than conforming — it is rejected. `R` has a **cliff**:

```
sev(a) small  ⇏  consequence small
```

Worse, for D2 the relevant agents are all conforming, so `sev = 0` for every one of them and no aggregate over `sev` can ever be non-zero. Tolerance stack-up is about **permitted** deviations accumulating, which distance-to-conforming cannot see.

### Definition 7.4 (Consumed margin)

Let `R` induce a scalar system margin `M(ρ) ∈ ℝ`, positive when the requirement holds with slack and negative when violated, normalized so that `M = 1` at nominal and `M = 0` at the constraint boundary.

```
cons(a, ρ)  ≜  the portion of margin depletion attributable to a's outputs
```

Defined for **all** agents, conforming or not. The reference point is `R`'s constraint boundary, not any particular output.

**[open] — the decomposition.** Attributing shares of `1 − M(ρ)` across agents requires a domain-specific accounting rule derived from `R`'s structure. For linearly-composing constraints (separation, capacity, cumulative delay) the decomposition is immediate. For others it is not, and no general construction is claimed. This is the main unresolved item in Part III.

### Definition 7.5 (Tolerance budget)

```
Ψ(ρ)  ≜  Σ_a cons(a, ρ)
```

**No weights.** Part V's own test rules out free per-agent coefficients: they are exactly the parameters that cannot be justified against a neighbouring choice. Consumed margin is already denominated in units of the shared budget, so the aggregation is a plain sum against a budget of 1.

**Linear is correct here, not a simplification** — the non-linearity was absorbed into `cons` via `R`'s geometry.

Prior art: error budgets in SRE, timing budgets in real-time systems, tolerance stack-up in mechanical engineering.

### Definition 7.6 (Accounting closure)

A failing conformant run is **accounted** iff `Ψ(ρ) ≥ 1` — the observed margin depletion is fully explained by the agents' own consumption.

### Definition 7.7 (D2 — tolerance stack-up)

```
Φ_C(ρ) = ∅  ∧  ¬R(ρ)  ∧  Ψ(ρ) ≥ 1
```

Every agent conformant; each legitimately spent margin within its guarantee; the sum exhausted the budget.

**Repair: tighten existing guarantees** so their permitted deviations cannot jointly exceed the budget.

### Definition 7.8 (D1 — missing obligation)

```
Φ_C(ρ) = ∅  ∧  ¬R(ρ)  ∧  Ψ(ρ) < 1
```

The failure is **not** explained by agent margin consumption. Something outside the accounted margin caused it — in the dead-sensor case, the state ceased to correspond to reality, which consumes no scheduling margin at all.

**Repair: a new obligation** covering the unaccounted cause.

### Remark 7.9

The distinction is now derived rather than stipulated: **D1 and D2 are separated by whether the margin accounting closes.** This also makes them decidable given `cons`, which the previous draft's formulation did not.

### Conjecture 7.10 **[open]**

`cons` and `vis` are weakly correlated at best, and the most damaging failures concentrate in the **high-consumption, low-visibility** region: agents that quietly spend large shares of the budget without producing local disturbance.

Predicts a specific competitor failure — methods keying on trace anomaly detect `vis`, not `cons`.

### Remark 7.11 (Interaction terms)

If real cases are found where a plain sum misattributes, add **specific** pairwise terms with numbers someone can defend. A dense interaction matrix nobody can justify is worse than none. **[open]** — no interaction structure is claimed.

## 8. Projection

### Definition 8.1

Contracts are defined over `Σ` but evaluated over a reconstruction `π : Traces → Σ̂`. Write `Φ̂` for the fault set so computed.

### Definition 8.2 (Per-evaluation error)

`ε` — the maximum probability that a projected predicate evaluation at one invocation differs from the true one.

### Proposition 8.3 (Union bound)

Let `k` bound the number of invocations per agent in `ρ`. Trace predicates are evaluated over histories of length up to `k`, so `Φ` depends on at most `2nk` field-level projections.

```
Pr[ Φ̂(ρ) ≠ Φ(ρ) ]  ≤  1 − (1 − ε)^{2nk}  ≤  2nk·ε
```

**Proof.** If all projections are correct, `Φ̂ = Φ`. ∎

### Remark 8.4

The previous draft stated `2nε`, which was correct only for single-invocation contracts and understated the bound once guarantees became trace predicates.

The bound is loose in two directions: it assumes independent projection errors (likely false — one misprojected field can flip several predicates), and it counts every projection as load-bearing when most predicates depend on few fields. **For long runs it may be vacuous.** **[open]** — a correlated, predicate-sensitive version is not derived.

The practical consequence stands: **`ε` must be measured and reported.** Attribution accuracy is upper-bounded by projection accuracy. A method evaluated without reporting `ε` is not interpretable.

---

# Part IV — Activation and Discovery

Parts II–III are post-hoc. This part makes latent violations **provokable** and unstated preconditions **discoverable**.

## 9. Margin and activation

Two design principles, recorded without the framings that produced them.

**On unstated preconditions.** After a failure, people state what they were relying on — *"I was relying on you to mention allergies."* That is a precondition articulated for the first time, retroactively, because it was never written. Resolution typically involves someone accepting an obligation nobody had assigned — *"I should have asked"* — a candidate strengthening with a volunteered owner. **Agents cannot volunteer.** This is why D1 requires abduction: the missing obligation must be derived, since no agent will offer to take it.

**On ramp rate.** Whether a signal is *resolvable* depends on the rate at which conditions change, not only their magnitude. Ramp too fast and multiple violations activate simultaneously, interact, and none is cleanly attributable. Ramp slowly and violations precipitate one at a time. **The control parameter has an optimum, not a maximum** — this is the opposite of standard stress testing, which maximizes load.

### Definition 9.1 (Margin parameter)

Task instances indexed by `τ ∈ [0,1]` with system margin decreasing in `τ`; `τ = 0` comfortable, `τ = 1` at the boundary.

### Definition 9.2 (Difficulty)

`δ` indexes instance complexity **at fixed margin**. `τ` and `δ` vary independently. This separation is the control for the difficulty confound.

### Definition 9.3 (Activation threshold)

For a stated exceedance level `α ∈ (0,1)`:

```
τ*_a(α)  ≜  inf { τ : Pr[ fault_C(a, ρ_τ) ] ≥ α }
```

The `α` is required: `Pr > 0` is not estimable from finite samples, and the previous draft's threshold was undefined in practice. Report `α` and the sample size.

The **fault ordering** is agents ordered by `τ*_a(α)` — which obligations sit closest to their margin. No existing method produces this, since all require a failure to have already occurred.

### Definition 9.4 (Inadequacy threshold)

```
τ*_∅(α)  ≜  inf { τ : Pr[ Φ_C(ρ_τ) = ∅ ∧ ¬R(ρ_τ) ] ≥ α }
```

Yields **Theorem 5.2 cases 2–3 on demand**, converting the central claim from an anecdote into a measurement. Definitions 7.7–7.8 then sort the instances into D1 and D2.

## 10. The flinch hypothesis

### Definition 10.1 (Strain signal)

`ψ_a(ρ) ∈ ℝ` — an observable computed from `a`'s behaviour: output entropy, disagreement across samples, hedge-marker rate, clarification requests, retries. Computed **without reference to `C`**.

### Hypothesis 10.2 (Flinch) **[open — this is the experiment]**

There exists `ψ` and a neighbourhood below `τ*_a(α)` on which:

```
(H1)   s_τ ≜ ∂ E[ψ_a(ρ_τ)] / ∂τ   >  0
(H2)   | s_δ / s_τ |  ≤  γ,        where s_δ ≜ ∂ E[ψ_a(ρ_{τ,δ})] / ∂δ
```

for a stated `γ` (e.g. `γ = 0.2`), with both slopes estimated over comparable ranges of `τ` and `δ`.

The previous draft wrote (H2) as `≈ 0`, which is not falsifiable. Stating it as a bounded **ratio of effect sizes** makes it testable and scale-free.

### Remark 10.3 (Both clauses are required)

(H1) alone is uninformative — any signal correlating with task hardness satisfies it, and reducing margin makes tasks harder as a side effect.

(H2) is discriminating. A `ψ` satisfying (H1) but not (H2) is a **difficulty detector**, and reporting it as a flinch signal would repeat exactly the error this framework accuses LLM judges of.

### Remark 10.4 (Direction of the signal)

`ψ_a` reveals **`a`'s own** strained assumption — the agent being let down, not the one that erred. Wrong direction for attribution; right direction for **discovery**, since it points at the agent whose contract needs writing.

It also inherits a known failure mode: proximity, not causation. The same bias that makes LLM judges fail.

### Corollary 10.5 (Active specification mining) — conditional on 10.2

For `τ < τ*_a(α)`, `ψ_a` is elevated while no violation has occurred. The strained assumption is by construction **not in `C`** — otherwise it would be a checked `P_a`.

Elevated `ψ` therefore identifies **unstated preconditions**, ordered by proximity to violation.

**Procedure:** ramp `τ` slowly → observe first elevation of `ψ_a` → interrogate that boundary → write `P_a` down → continue.

Prior art: specification mining, Daikon-style invariant detection (passive), active automata learning (query-based). This is the **active** variant.

### Remark 10.6 (Partial resolution of ownership)

Flinch data narrows §6.8 candidates on **feasibility**: an agent that flinched has the relevant signal in hand and *can* hold the obligation; one with no access to that state cannot — and if no agent has it, that is Theorem 5.2 case 3.

**Evidence prunes the infeasible. It does not select among the feasible.**

### 10.7 Threats

- **The signal may not exist.** Unmeasured. Test first, cheaply.
- **The difficulty confound.** Addressed by (H2), but needs a real control. This confound has surfaced from three independent directions, which suggests it is central.
- **Ramping perturbs the system under measurement.**

---

# Part V — Policy on Non-Linearity

The framework distinguishes **stated** components (which adjudicate) from **fitted** ones (which detect).

| Location | Non-linearity | Rationale |
|---|---|---|
| Inside `G_a` (window aggregates over history) | **yes** — unavoidable | comes free with trace predicates |
| `cons` — consumed margin | **yes** — the substantive one | derived from `R`'s geometry |
| `Ψ` — tolerance budget | **no** — plain sum, no weights | non-linearity already in `cons`; keeps aggregation auditable |
| `ψ` — strain signal | **yes** — unconstrained | detects, never adjudicates |

### The test for any proposed function

> Can you state, without reference to fit quality, why *this* function and not a neighbouring one?

- Circular distance on circular state — **yes**, from the topology
- Hard clip at a constraint boundary — **yes**, from `R`
- `tanh` over aggregated severity — **no**
- Free per-agent weights in `Ψ` — **no** (this is why Definition 7.5 has none)

Squashing functions exist to keep stacked linear layers non-degenerate and gradients well-behaved. Both concern *training*. `Ψ` is not learned, so neither applies. **A parameter with no principled setting is a parameter that cannot be defended.**

### The line on learned components

| Role | Learned |
|---|---|
| deciding whether `G_a` was violated | **no** — must be explicit and arguable |
| computing `ψ_a` | **yes** — a detector |
| proposing candidate `P`/`G` from flinch data | **yes** — a human ratifies |
| the margin decomposition in `cons` (§7.4) | **boundary case** — if fitted rather than derived, the resulting rule must be *stated*, like the contracts |

A learned adjudicator is an implicit norm — a model of what runs usually look like. That is LLM-as-judge with a different architecture, reintroducing exactly what §1.5(b) identifies as the problem.

**Fitted proposes. Stated adjudicates.**

---

# Part VI — Status

## 11. Proof status

| Result | Status |
|---|---|
| 4.1–4.3 fault, `Φ`, conformance | definition |
| 4.4 locality (per agent over time) | true by construction |
| 5.2 trichotomy | **proved** |
| 5.3 scope of exclusivity | **proved** |
| 6.2 monotonicity | **proved** |
| 6.3 two-sidedness of the order | **proved** |
| 6.5 vacuous repairs excluded | **proved**, corpus-coverage caveat |
| 6.6 non-uniqueness | **proved** (sketch — construction should be written out) |
| 6.7 set-valued output | corollary of 6.6 |
| 6.8 selection among feasible owners | **[open]** — none claimed |
| 7.1–7.2 violation magnitude, visibility | definition |
| 7.4 consumed margin | definition; **decomposition [open]** |
| 7.7–7.8 D1/D2 by accounting closure | definition; decidable given `cons` |
| 7.10 consumption/visibility decorrelation | **[open]** — conjecture, testable |
| 8.3 projection bound | **proved**, loose; correlated version **[open]** |
| 9.3–9.4 thresholds with stated `α` | definition |
| 10.2 flinch, with effect-size ratio | **[open]** — the experiment |

## 12. Gaps

### 12.1 Largest open problems

1. **No algorithm for `max_⊑ Rep`.** Theorem 6.6 characterizes the answer; nothing computes it. The novel mechanism lives here.
2. **The margin decomposition in Definition 7.4.** Without it, `Ψ` is not computable and D1/D2 cannot be separated. Immediate for linearly-composing constraints; open in general.
3. **No predicate language.** `P_a`, `G_a` are abstract subsets. A concrete syntax with decidable satisfaction is required before implementation; monitorable LTL fragments are the obvious candidate.
4. **No complexity analysis** of the repair search.
5. **Nothing empirical.**

### 12.2 Defects repaired in this revision

| | Defect | Fix |
|---|---|---|
| 1 | D2 unsatisfiable — `sev` vanishes when `Φ = ∅` | split into `sev` (7.1) and `cons` (7.4); D1/D2 by accounting closure |
| 2 | `P` typed over single input, `G` over histories | both trace predicates (§3.4) |
| 3 | No branch for `Rep = ∅` | trichotomy, case 3 (5.2) |
| 4 | "Exactly one" ambiguous about adequacy of `C` | scoped to the verdict for `ρ` (5.3) |
| 5 | §2.6 promised four definitions, three computable | stated, with the a fortiori argument |
| 6 | Projection bound `2nε` ignored trace length | `2nkε` (8.3), with vacuity warning |
| 7 | Free weights `w_a` violated Part V's own test | removed; plain sum (7.5) |
| 8 | `τ* = inf{τ : Pr > 0}` not estimable | stated exceedance level `α` (9.3) |
| 9 | `(H2) ≈ 0` not falsifiable | bounded effect-size ratio `γ` (10.2) |
| 10 | §1.1 overstated the field's confusion | softened; Who&When placed near earliest-sufficient-cause |

## 13. Runnable now

| Experiment | Needs | Blocked on |
|---|---|---|
| Divergence between definitions (§2.6) | annotated failures | nothing |
| Flinch (H1) and control (H2) | one agent, margin knob, `ψ` | nothing |
| Contract evaluation on hand-built B and D cases | hand-coded `P`, `G` for 2–3 agents | nothing |
| Judge baseline comparison | full contract set, projection layer | the above |
| D1/D2 separation | `cons` decomposition | gap 2 |
| Repair enumeration | repair algorithm | gap 1 |

The first two require no formalization beyond what is here, and §2.6 tests the central claim directly.

## 14. Applicability

Requires: typed state (or a projection with measured `ε`), some externally specified correctness conditions, stable agent roles, a stated `R`, and — for D1/D2 separation — a margin decomposition.

**Best fit:** pipelines over structured state with external specifications — scheduling, resource allocation, transaction and workflow systems, control loops, compliance checking, data pipelines with schema and integrity constraints.

**Worst fit:** open-ended generative systems with prose interfaces and no external correctness standard.

The worst fit describes most current attribution benchmarks. Per §1.6 this is a claim about the benchmarks rather than a limitation of the method — but §2.6 is what makes it testable rather than convenient, and should be run before the claim appears in print.

---

# Anchors

- Avižienis et al. — fault / error / failure taxonomy
- Halpern & Pearl — structural account of actual causation
- Rely-guarantee reasoning; Meyer, design by contract
- Reiter; de Kleer & Williams — model-based diagnosis
- Runtime verification; monitorable LTL fragments
- Daikon — dynamic invariant detection; Angluin — active automata learning
- Zhang et al., ICML 2025 — Who&When, original baselines
- TraceElephant — observability ablation
- FAMAS — spectrum-based attribution
