# Demo walkthrough — data, queries, results, interpretation

> **🇰🇷 한국어:** [walkthrough.ko.md](./walkthrough.ko.md)
> **Parent README:** [README.md](../README.md)

This document goes one step deeper than the README's "what comes out"
view, into **how each question's answer is actually derived** — what
the data is, which inference layer answers each, and why other layers
*can't*.

Every one of the 14 questions follows the same four-block structure:

| Block | What it covers |
|---|---|
| **Question (natural language)** | What an ops team would actually ask |
| **Layer used** | L0 (store) / L1 (SPARQL) / L2 (posterior) / L3 (do · counterfactual) / Flow |
| **Derivation** | How the data is walked, where the reasoning happens |
| **Query / call** | Real SPARQL / Python — not pseudocode |
| **Result** | Actual script output (reproducible, seed-pinned) |
| **Interpretation** | Why the answer matters and why no other layer could produce it |

---

## 0. Data overview — "what lives in this demo's universe"

### Entity counts (after one `01_generate_data.py` run)

| Class | Instances | Notes |
|---|---:|---|
| `mfg:Supplier` | 5 | SUP-A through SUP-E |
| `mfg:Lot` | 50 | LOT-0001 through LOT-0050 |
| `mfg:Component` | 600 | one per product (1:1) |
| `mfg:ProcessRun` | 1,800 | three runs per component (machining/assembly/inspection) |
| `mfg:Product` | 600 | |
| `mfg:QCResult` | 600 | pass 449 / fail 151 (25.2%) |
| **Total RDF triples** | **14,010** | after Turtle serialisation |

### Relation graph (schema = the only navigation path)

```
Supplier ─supplies→ Lot ─hasComponent→ Component ─processedBy→ ProcessRun ─produces→ Product ─hasQC→ QCResult
                                                                     │
                                                                 atStep ↓
                                                                 ProcessStep
```

`mfg:condition` (`"normal"` / `"low"` / `"high"`) is attached to each
ProcessRun and preserves the process state as a discrete value. That's
what the Stage-4 causal layer consumes.

### Ground truth (`ground_truth.json` — verification-only)

The generator separately retains the "hidden truths" that a real factory
would not have:

```json
{
  "suspect_supplier_id": "SUP-B",          // P(bad lot) = 0.55 — ~4× the average ~0.14
  "contaminated_lot_id": "LOT-0047",       // P(bad lot) hard-forced to 1.0
  "causal_process_step_uri": ".../StepAssembly",  // the true causal process
  "total_products": 600,
  "total_failures": 151,
  "failures_by_supplier": {"SUP-B": 46, "SUP-D": 32, ...},
  "failures_by_lot": {"LOT-0047": 10, "LOT-0027": 9, ...}
}
```

**Why synthetic** — real factory part→lot→supplier→product relational
data is proprietary; public exemplars are essentially nonexistent.
Synthetic data lets us *control* the causal/relational structure and,
crucially, *know the answers up front* so ontorag's responses can be
verified byte-for-byte (questions 1–4 prove this).

### Causal model (generator and inference engine, identical)

```
SupplierQuality ─→ LotQuality ─→ ComponentQuality ─┐
                                                   ├─→ ProductDefect
                  AssemblyPressure ────────────────┘
MachiningTemperature   (noise — independent of ProductDefect)
InspectionMoisture     (noise — independent of ProductDefect)
```

Part of the ProductDefect CPT:

| Condition | P(Defect=fail) |
|---|---:|
| Component=good, Pressure=normal | 0.02 |
| Component=good, Pressure=low    | 0.35 |
| Component=bad,  Pressure=normal | 0.50 |
| Component=bad,  Pressure=low    | 0.85 |

This single table is the source of every causal claim in the demo.

---

## L1 — questions answerable by graph traversal

### Q1: "Which lot produced the most failing units?"

**Layer:** L1 (multi-hop SPARQL)

**Derivation:**

1. Filter QCResult to `verdict="fail"`.
2. QCResult → Product (inverse of `mfg:hasQC`).
3. Product → ProcessRun (inverse of `mfg:produces`).
4. ProcessRun → Component (inverse of `mfg:processedBy`).
5. Component → Lot (inverse of `mfg:hasComponent`).
6. GROUP BY lotId, COUNT DISTINCT product.
7. ORDER BY DESC + LIMIT.

**Query** (`src/ontorag_demo/verify/trace.py::failures_per_lot`):

```sparql
PREFIX mfg:  <https://ontorag-demo.dev/manufacturing#>
SELECT ?lotId (COUNT(DISTINCT ?product) AS ?failures) WHERE {
    ?product mfg:hasQC ?qc .
    ?qc      mfg:verdict "fail" .
    ?run     mfg:produces ?product .
    ?component mfg:processedBy ?run .
    ?lot     mfg:hasComponent ?component .
    ?lot     mfg:lotId ?lotId .
}
GROUP BY ?lotId
ORDER BY DESC(?failures)
LIMIT 5
```

**Result:**

```text
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Rank ┃ Lot                     ┃ SPARQL count ┃ Ground truth ┃ Match ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━┩
│    1 │ LOT-0047 (contaminated) │           10 │           10 │ ✓     │
│    2 │ LOT-0027                │            9 │            9 │ ✓     │
│    3 │ LOT-0005                │            8 │            8 │ ✓     │
│    4 │ LOT-0014                │            8 │            8 │ ✓     │
│    5 │ LOT-0017                │            8 │            8 │ ✓     │
└──────┴─────────────────────────┴──────────────┴──────────────┴───────┘
```

**Interpretation:**

- Every count matches ground truth — proof the 5-hop SPARQL JOIN walks
  the schema's inverse relations correctly. The *data itself* is not lying.
- **The contaminated LOT-0047 surfaces at rank #1.** If the ops team
  decides off this table alone, "quarantine LOT-0047" is a natural and
  *correct* first move.
- But ranks 2–5 cluster at 8–9 failures each — quarantining a single
  lot won't catch the rest of the risk → motivates questions 3 and 5–9.

---

### Q2: "Which supplier is most associated with failures?"

**Layer:** L1 (Q1 plus one more hop)

**Derivation:**
Same 5 hops as Q1 down to Lot, then one more inverse hop to Supplier
(`mfg:supplies` inverse), then GROUP BY supplierId.

**Query** (`failures_per_supplier`):

```sparql
SELECT ?supplierId (COUNT(DISTINCT ?product) AS ?failures) WHERE {
    ?product mfg:hasQC ?qc .
    ?qc      mfg:verdict "fail" .
    ?run     mfg:produces ?product .
    ?component mfg:processedBy ?run .
    ?lot     mfg:hasComponent ?component .
    ?supplier mfg:supplies ?lot .
    ?supplier mfg:supplierId ?supplierId .
}
GROUP BY ?supplierId
ORDER BY DESC(?failures)
```

**Result:**

```text
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Supplier        ┃ SPARQL count ┃ Ground truth ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ SUP-B (suspect) │           46 │           46 │
│ SUP-D           │           32 │           32 │
│ SUP-E           │           28 │           28 │
│ SUP-A           │           24 │           24 │
│ SUP-C           │           21 │           21 │
└─────────────────┴──────────────┴──────────────┘
```

**Interpretation:**

- SUP-B is #1, but the gap to SUP-D is only 14 — **too narrow to
  confidently say "quarantine the top supplier."**
- This is the demo's deliberate trap. The generator did inject SUP-B
  with P(bad lot)=0.55, but AssemblyPressure noise *dilutes the supplier
  signal at the aggregate level*.
- The ops team looking at this table alone faces an ambiguous call:
  "ban SUP-B? or also SUP-D?" **Only L3 do-queries (Q7) resolve this.**

---

### Q3: "How are failures distributed across assembly-step conditions?"

**Layer:** L1 (single GROUP BY)

**Derivation:**
Failed products → their ProcessRuns → keep those `mfg:atStep mfg:StepAssembly`
→ GROUP BY `mfg:condition`.

**Query** (`failures_per_assembly_condition`):

```sparql
SELECT ?condition (COUNT(DISTINCT ?product) AS ?failures) WHERE {
    ?product mfg:hasQC ?qc .
    ?qc      mfg:verdict "fail" .
    ?run     mfg:produces ?product .
    ?run     mfg:atStep mfg:StepAssembly .
    ?run     mfg:condition ?condition .
}
GROUP BY ?condition
ORDER BY DESC(?failures)
```

**Result:**

```text
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Assembly condition ┃ Failures ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ low                │      110 │
│ normal             │       41 │
└────────────────────┴──────────┘
```

**Interpretation:**

- 110 vs 41 → "low assembly pressure correlates with ~2.7× more
  failures" — **correlational evidence.**
- **But L1 alone cannot prove this is causal.** Alternative explanations
  the data is consistent with:
  - Maybe bad lots happen to flow more through the low-pressure lines.
  - Maybe both pressure and component quality are influenced by a third
    latent factor (e.g., shift).
- L1 shows correlation only; the *intervention* question — "if we
  forced pressure to normal, would failures drop?" — is what Q8
  finally answers.

---

### Q4: "Which products came out of the suspect lot LOT-0047?"

**Layer:** L1 (forward graph traversal)

**Derivation:**
The exact reverse of Q1 — start at Lot, walk forward through
Component → ProcessRun → Product (4 hops).

**Query** (`products_from_lot`):

```sparql
SELECT DISTINCT ?productId WHERE {
    ?lot mfg:lotId "LOT-0047" .
    ?lot mfg:hasComponent ?component .
    ?component mfg:processedBy ?run .
    ?run mfg:produces ?product .
    ?product mfg:productId ?productId .
}
ORDER BY ?productId
```

**Result:**

```text
12 products: PRD-00047, PRD-00097, PRD-00147, PRD-00197, PRD-00247, PRD-00297, ...
```

**Interpretation:**

- 600 / 50 = 12 exactly → traversal works in both directions per the
  schema's inverse properties.
- The ops team gets an immediately actionable list — *"re-inspect these
  12 units before shipping."*
- This is traceability's real business value: **recall scope and
  attribution**. L2/L3 answer *why*; L1 answers *who/what*.

---

## L2 — questions answered by probabilistic inference

### Q5: "What's the marginal defect probability across the population?"

**Layer:** L2 (`compute_posterior` with no evidence)

**Derivation:**

1. Construct `BayesianEngine(MANUFACTURING_BN)`.
2. Call `compute_posterior(evidence={}, query=[ProductDefect_URI])`.
3. pgmpy variable-eliminates the 7-node × CPT joint down to ProductDefect's
   marginal.

**Call** (`verify/causal.py::baseline`):

```python
from ontorag.bayes.engine import BayesianEngine
from ontorag_demo.causal.model import MANUFACTURING_BN, NODES_BY_NAME

engine = BayesianEngine(MANUFACTURING_BN)
raw = await engine.compute_posterior(
    evidence={},
    query=[NODES_BY_NAME["ProductDefect"].uri],
)
# → {"<ProductDefect URI>": {"pass": 0.7355, "fail": 0.2645}}
```

**Result:** `P(fail) = 0.265`

**Interpretation:**

- Matches the actual observed rate of 25.2% (151/600). **Self-check that
  the data generator and the BN share the same CPTs.** Any drift would
  surface here as a mismatch.
- This is the **baseline** every other answer compares against.

---

### Q6: "What's the defect probability if we *observe* the supplier quality is bad?"

**Layer:** L2 (`compute_posterior` with evidence)

**Derivation:**

1. evidence = `{SupplierQuality: "bad"}`.
2. pgmpy updates the conditional joint and re-marginalises.
3. Effect path: SupplierQuality → LotQuality → ComponentQuality →
   ProductDefect, where bad supplier raises P(LotQuality=bad), which
   raises P(ComponentQuality=bad), which raises P(ProductDefect=fail).

**Call** (`observational_supplier_bad`):

```python
raw = await engine.compute_posterior(
    evidence={NODES_BY_NAME["SupplierQuality"].uri: "bad"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
)
```

**Result:** `P(fail | see Supplier=bad) = 0.467`

**Interpretation:**

- Baseline 0.265 → 0.467, **nearly 2× the jump**.
- "When we observe the supplier turned out bad, the defect probability
  for that line is almost half" — a strong **observational** conclusion.
- **The trap:** this number bakes in *all the reasons the supplier
  might be bad in the first place*, not just the causal arrow. The
  effect of *intervening* to make the supplier good is a different
  question — exactly the gap Q7 exposes.

---

## L3 — causal inference (intervention / counterfactual)

### Q7: "*If* we could force all suppliers to be good, what's the defect rate?"

**Layer:** L3 Rung 2 (do-calculus)

**Derivation:**

1. Build `CausalEngine(BN, DAG)`.
2. Call `do_query(do={SupplierQuality: "good"}, query=[ProductDefect])`.
3. ontorag/pgmpy *cuts* every incoming arrow into SupplierQuality (graph
   surgery), externally sets SupplierQuality=good, then marginalises.
4. Effect: only the supplier path
   (SupplierQuality→Lot→Component→Defect) contribution is isolated;
   other roots like AssemblyPressure stay at their priors.

**Call** (`do_supplier_good`):

```python
from ontorag.causal.engine import CausalEngine
engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)
raw = await engine.do_query(
    do={NODES_BY_NAME["SupplierQuality"].uri: "good"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
    evidence={},
)
```

**Result:** `P(fail | do(Supplier=good)) = 0.197`

**Interpretation:**

- Baseline 0.265 → 0.197 = **−0.067**.
- Compare to Q6's 0.467 (`see`): **gap of 0.27**. **"Observe" and
  "intervene" give completely different answers** — Pearl's core
  message in one number.
- Even a sweeping intervention ("make all suppliers good") shaves only
  7%pt off baseline. **The absolute effect of the supplier intervention
  is smaller than the correlation suggested.**

---

### Q8: "*If* we could force assembly pressure to normal everywhere?"

**Layer:** L3 Rung 2

**Derivation:** identical shape to Q7, but do() targets AssemblyPressure.

**Call** (`do_assembly_normal`):

```python
raw = await engine.do_query(
    do={NODES_BY_NAME["AssemblyPressure"].uri: "normal"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
    evidence={},
)
```

**Result:** `P(fail | do(Pressure=normal)) = 0.131`

**Interpretation:**

- Baseline 0.265 → 0.131 = **−0.134**.
- Compare to Q7's −0.067 → **process intervention is roughly 2×
  more effective than the supplier intervention**.
- **An ops team that started suspecting SUP-B from Q2 has its
  priorities flipped by this single result** — fix the assembly line
  first; that's where the ROI is.
- L1 alone could never produce this conclusion (Q3's 110 vs 41 is
  correlation, not intervention effect).

---

### Q9: "Do the two interventions stack additively?"

**Layer:** L3 Rung 2 (multi-variable do)

**Derivation:** specify both variables in do() at once.

**Call** (`do_both`):

```python
raw = await engine.do_query(
    do={
        NODES_BY_NAME["SupplierQuality"].uri: "good",
        NODES_BY_NAME["AssemblyPressure"].uri: "normal",
    },
    query=[NODES_BY_NAME["ProductDefect"].uri],
    evidence={},
)
```

**Result:** `P(fail | do(both)) = 0.064`

**Interpretation:**

- −0.20 = **the two interventions essentially add up**
  (0.067 + 0.134 = 0.201).
- This is because the two causal paths share no parent-child link in
  the DAG — they're separate paths to the same effect node, so they
  don't interfere.
- Operationally: "process gets you part of the way; supplier gets you
  the rest" — if budget allows, do both for maximum effect.

---

### Q10: "*Would this one specific failing product have passed* under normal pressure?"

**Layer:** L3 Rung 3 (counterfactual)

**Derivation (abduction-action-prediction):**

1. **Abduction** — invert from the observation
   (`AssemblyPressure=low ∧ ProductDefect=fail`) to learn what latent
   noise states must have been in play.
2. **Action** — keep that latent noise; override AssemblyPressure to
   "normal" (do).
3. **Prediction** — compute ProductDefect's distribution in that
   hypothetical world.

ontorag solves this exactly via response-function enumeration over the
canonical independent-noise SCM (same code path that the smoking
example verifies to within 1e-4).

**Call** (`counterfactual_assembly_was_normal`):

```python
raw = await engine.counterfactual(
    observed={
        NODES_BY_NAME["AssemblyPressure"].uri: "low",
        NODES_BY_NAME["ProductDefect"].uri: "fail",
    },
    intervention={NODES_BY_NAME["AssemblyPressure"].uri: "normal"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
)
```

**Result:** `P(fail | observed=(low, fail), intervened=(normal)) = 0.222`

**Interpretation:**

- This is **not an aggregate**. It's the probability that *this
  specific product* would have failed in a hypothetical where pressure
  had been normal.
- 0.222 = "78% chance it would have passed" — pressure was decisive
  for *this* unit.
- **Only L3 Rung 3 can answer this.** Rung 1 (see) and Rung 2 (do)
  cannot reason about "what would have happened to *this* event."
- Business uses: compensation claims, attribution analysis,
  post-incident review — quantitatively decide whether *this batch*
  was process-driven or part-driven.

---

## Flow — ontorag-flow composes the above questions into a decision loop

These steps **automate the job a human operator would normally do**.
If Q1–10 are the *analytic tools*, Q11–14 are about *what order to use
them in, who decides, and how it's recorded*.

### Q11: "When a case opens, how does the system automatically pick the suspect lot?"

**Layer:** Flow Action `PinpointSuspectLot` (calls L1 internally)

**Derivation:**

1. RuleEngine sees the initial case state `defect_rate_percent: 25` and
   the first rule triggers:

   ```yaml
   - name: "High defect rate — pinpoint suspect lot first"
     when:
       defect_rate_percent: { gte: 10 }
       suspect_lot_known: false
     then:
       action: "urn:demo:manufacturing:PinpointSuspectLot"
   ```

2. `PinpointSuspectLot.execute` internally runs the same SPARQL as Q1
   (`failures_per_lot(store, limit=5)`).
3. The top-1 lot is persisted to case state (`suspect_lot_id`,
   `suspect_lot_failures`, `suspect_lot_known=true`).

**Result (case state delta):**

```text
suspect_lot_id: LOT-0047
suspect_lot_failures: 10
suspect_lot_known: True
```

**Interpretation:**

- No operator needs to write SPARQL — *the question is automatically
  asked, the answer recorded* in case state.
- Every decision's starting point lands in the audit log, replayable
  via PROV-O.

---

### Q12: "How does the system automatically pick the most effective intervention?"

**Layer:** Flow Action `EvaluateIntervention` (wraps Q7–9)

**Derivation:**

1. Second rule fires (condition: `suspect_lot_known=true ∧
   causal_evaluation_done=false`).
2. `EvaluateIntervention.execute` calls Q7, Q8, Q9 in sequence.
3. Picks the intervention with the lowest expected P(fail).

**Call (pseudocode):**

```python
candidates = {
    "supplier_only": (await do_supplier_good()).p_fail,       # 0.1971
    "process_only":  (await do_assembly_normal()).p_fail,     # 0.1307
    "supplier_and_process": (await do_both()).p_fail,         # 0.0644
}
recommended = min(candidates, key=candidates.get)             # "supplier_and_process"
```

**Result (case state):**

```text
baseline_p_fail: 0.2645
intervention_p_fail: {
  'supplier_only': 0.1971,
  'process_only':  0.1307,
  'supplier_and_process': 0.0644
}
recommended_intervention: supplier_and_process
causal_evaluation_done: True
```

**Interpretation:**

- **Causal analysis results become persistent case properties** — anyone
  opening this case later sees exactly what numerical basis the
  recommendation rests on.
- When the human operator opens this case, they compare their intuition
  to the causal conclusion and decide whether to proceed to Q13.

---

### Q13: "Once the decision is made, how is it written back into ontorag?" (write-back)

**Layer:** Flow Actions `RequestQuarantineApproval` (HUMAN) +
`QuarantineLot` (ABOX_WRITE)

**Derivation:**

1. Third rule fires → `RequestQuarantineApproval` runs → `side_effect=HUMAN`
   → CaseManager **auto-suspends the case**.
2. External code calls `manager.resume(case_uri)` (the demo simulates this).
3. Runner reads `suspect_lot_id="LOT-0047"` from case state, recovers
   the URI via `lot_uri_for("LOT-0047")`.
4. Calls `manager.execute_action(case_uri, QuarantineLot, {"lot_uri": ...})`.
5. `QuarantineLot.execute` POSTs a SPARQL UPDATE to Fuseki's
   `/ontorag/update` endpoint.

**Call (SPARQL UPDATE — `flow/writeback.py::set_lot_quarantined`):**

```sparql
PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
WITH <urn:ontorag:manufacturing-demo:data>
DELETE { ?lot mfg:quarantined ?old }
INSERT { ?lot mfg:quarantined "true"^^xsd:boolean }
WHERE  {
  BIND(<https://ontorag-demo.dev/manufacturing#lot/LOT-0047> AS ?lot)
  OPTIONAL { ?lot mfg:quarantined ?old }
}
```

**Verify externally with a SPARQL SELECT:**

```sparql
PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>
SELECT ?lotId WHERE { ?lot mfg:lotId ?lotId ; mfg:quarantined true . }
```

```json
{
  "head": {"vars": ["lotId"]},
  "results": {"bindings": [{ "lotId": {"value": "LOT-0047"} }]}
}
```

**Interpretation:**

- The triple is *actually loaded* and visible to every other SPARQL
  consumer of ontorag → the loop is closed.
- Why the human gate is enforced: `QuarantineLot.auto_execute_disabled =
  True` locks out any automation from running this without an operator
  click. ABox write-backs always require human approval.

---

### Q14: "*What if* we hadn't quarantined and just left things alone?" (CF replay)

**Layer:** Flow Action `CounterfactualReplay` (calls Q10)

**Derivation:**

1. Fourth rule fires (`quarantined=true ∧ rca_complete=false`).
2. `CounterfactualReplay.execute` issues the same counterfactual call as Q10.
3. Result written to case state, `rca_complete=true` set → CaseManager
   transitions the case to CLOSED.

**Result:**

```text
counterfactual_p_fail: 0.2222
rca_complete: True
status: closed
```

**Interpretation:**

- This step *does not change the decision* (the quarantine already
  happened). Instead it serves **forensic recall** — when someone later
  asks "why did you quarantine?", the audit log has a quantitative
  answer alongside the action itself.
- "Had we not quarantined, this batch would have re-failed at 22%
  probability" — that *numerical justification* is permanently
  preserved in PROV-O. This is ontorag-flow's "provenance over
  replayability" principle in action.

---

## Putting it together — the picture the 14 questions paint

| Q | Layer | What it answers | What it can't |
|---|---|---|---|
| Q1 lot ranking | L1 | "where do failures cluster" | "is it causal" |
| Q2 supplier ranking | L1 | "frequency by supplier" | "would fixing the supplier help" |
| Q3 condition distribution | L1 | "condition-failure correlation" | "is the condition the cause" |
| Q4 lot → products | L1 | "recall scope" | — |
| Q5 baseline | L2 | "average failure rate" | — |
| Q6 see(supplier=bad) | L2 | "posterior under observation" | "same as intervening?" |
| Q7 do(supplier=good) | L3 R2 | "true effect of fixing supplier" | "what about this specific case?" |
| Q8 do(pressure=normal) | L3 R2 | "true effect of fixing process" | "what about this specific case?" |
| Q9 do(both) | L3 R2 | "additive effect" | "what about this specific case?" |
| Q10 counterfactual | L3 R3 | "what-if for this exact product" | — |
| Q11 Flow Pinpoint | Flow+L1 | "auto suspect lot" | — |
| Q12 Flow Evaluate | Flow+L3 | "auto intervention recommendation" | — |
| Q13 Flow Quarantine | Flow+write | "ABox closed loop" | — |
| Q14 Flow CF Replay | Flow+L3R3 | "post-decision rationale in audit" | — |

**Bottom line** — what the demo proves:

1. L1 traceability gives you **recall scope and ranking** (Q1, Q4).
2. L1 aggregates alone **cannot distinguish supplier from process**
   (Q2, Q3 → Q7, Q8).
3. Only L3 do-queries answer **"what's the most effective lever to
   change"** (Q7–9).
4. Only L3 counterfactual quantifies **individual-event what-ifs**
   (Q10).
5. ontorag-flow wraps the above into a single **propose → approve →
   act → reflect** loop with every step recorded in PROV-O (Q11–14).
