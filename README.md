# ontorag-demo

> **🇰🇷 한국어 README:** [README.ko.md](./README.ko.md)

A synthetic manufacturing **traceability + causal-RCA** demo built on
[`ontorag`](https://github.com/nuri428/ontorag) (Semantic + Dynamic
reasoning) and [`ontorag-flow`](https://github.com/nuri428/ontorag-flow)
(Kinetic / Adaptive Case Management).

The design rationale lives in [`ontorag_flow_demo_plan.md`](./ontorag_flow_demo_plan.md).
This README is the **runbook + annotated output log** — every script's
real output is captured below so you can read the demo end-to-end
without running it.

Three companion documents go deeper:

* **[docs/walkthrough.md](./docs/walkthrough.md)** — *"how each answer is
  derived"* — 14 questions × (data, query, result, interpretation).
* **[docs/implementation.md](./docs/implementation.md)** — *"why the code
  looks the way it looks"* — 12 design decisions × (problem, options,
  choice, code applied, validation).
* **[docs/dev_guide.md](./docs/dev_guide.md)** — *"how to actually work
  on this"* — 5 change recipes + change-impact matrix + extension
  points + troubleshooting + dev cycle.

---

## The story this demo tells

A finished-goods QC pipeline shows a defect rate higher than operations
expected. Two questions follow, and they are hard to answer *at the
same time* without an ontology-aware reasoning stack:

1. **Trace narrowly** — *which lots / suppliers / process runs* are
   over-represented in the failing products? (L1, multi-hop SPARQL.)
2. **Explain causally** — once scope is narrowed, is the dominant cause
   *the parts* (supplier / lot quality) or *the process* (assembly-step
   condition)? Naive aggregation conflates them; only
   `do(SupplierQuality=good)` vs `do(AssemblyPressure=normal)`
   separates them. (L3, Pearl Rung 2 + 3.)

Then close the loop:

3. **Act with audit** — propose → score interventions → human approval
   → write `mfg:quarantined=true` back to ontorag's ABox →
   counterfactual replay (`what if we had not quarantined?`) → PROV-O
   activity log for forensic recall.

---

## Layout

```
ontorag-demo/
├── ontorag_flow_demo_plan.md   # design rationale (read first)
├── vendor/                     # local-only checkouts (gitignored)
│   ├── ontorag/                # clone of https://github.com/nuri428/ontorag
│   └── ontorag-flow/           # clone of https://github.com/nuri428/ontorag-flow
├── src/ontorag_demo/
│   ├── schema/                 # Stage 1 — OWL/Turtle TBox
│   ├── causal/                 # Stage 2 — Bayesian network + Causal DAG
│   ├── generator/              # Stage 3 — synthetic sampler + RDF writer
│   ├── verify/                 # Stage 4 — SPARQL traceability + posterior/do/CF
│   └── flow/                   # Stage 5 — actions + process YAML + runner
├── scripts/                    # Numbered entry points (run in order)
│   ├── 01_generate_data.py
│   ├── 02_load_ontorag.py
│   ├── 03_run_trace.py
│   ├── 04_run_causal.py
│   └── 05_run_flow.py
├── tests/
├── data/generated/             # produced by 01 (gitignored)
└── runs/flow/                  # produced by 05 (gitignored)
```

---

## Prerequisites

* Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).
* A running Fuseki at `FUSEKI_URL` (default `http://localhost:3030`)
  with a dataset named in `FUSEKI_DATASET` (default `ontorag`). Two ways:

  ```bash
  # A) Reuse ontorag's compose (pre-tested combo).
  cd vendor/ontorag && docker compose up -d

  # B) Or run any Fuseki 5.x image yourself on :3030 with dataset "ontorag".
  ```

  The demo isolates itself under the named-graph scope
  `manufacturing-demo`, so it won't collide with whatever else lives in
  that Fuseki.

* **Local vendor checkouts.** `vendor/` is gitignored; bootstrap it
  manually:

  ```bash
  mkdir -p vendor
  git clone https://github.com/nuri428/ontorag.git       vendor/ontorag
  git clone https://github.com/nuri428/ontorag-flow.git  vendor/ontorag-flow
  ```

  `pyproject.toml`'s `[tool.uv.sources]` already points editable
  installs at those paths.

* Install deps:

  ```bash
  uv sync --extra dev
  cp .env.example .env       # optional — defaults are fine on :3030
  ```

---

## Five-stage walkthrough (with real output)

### Stage 1 — schema (TBox, no script)

`src/ontorag_demo/schema/manufacturing.ttl` defines **7 classes** and
**12 properties**. The single design choice worth highlighting:
process conditions live on `ProcessRun` as **discrete `mfg:condition`
strings**, so pgmpy consumes them directly without a binning
preprocessor (plan §2).

```turtle
mfg:ProcessRun a owl:Class .
mfg:condition  a owl:DatatypeProperty ;
    rdfs:domain mfg:ProcessRun ;
    rdfs:range  xsd:string .   # values: "normal" | "high" | "low"
```

### Stage 2 — Bayesian network + Causal DAG (no script)

`src/ontorag_demo/causal/model.py` is a **single source of truth** that
quantifies the data generator (Stage 3) *and* feeds ontorag's
`BayesianEngine` / `CausalEngine` (Stage 4). 7 nodes, one interaction,
two independent process-noise variables:

```
SupplierQuality ─→ LotQuality ─→ ComponentQuality ─┐
                                                   ├─→ ProductDefect
                  AssemblyPressure ────────────────┘
MachiningTemperature   (noise — independent)
InspectionMoisture     (noise — independent)
```

### Stage 3 — generate synthetic data

```bash
uv run python scripts/01_generate_data.py
```

**Real output:**

```text
────────────────────────────── Generation summary ──────────────────────────────
Turtle:        data/generated/manufacturing-instances.ttl  (14010 triples)
Ground truth:  data/generated/ground_truth.json

products: 600   failures: 151   (25.2% defect rate)
suspect supplier: SUP-B   contaminated lot: LOT-0047

  Failures by attributed cause (heuristic)
  ┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
  ┃ Cause            ┃ Count ┃
  ┡━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
  │ process_only     │    66 │
  │ interaction      │    44 │
  │ random_component │    21 │
  │ supplier_chain   │    11 │
  │ random_noise     │     6 │
  │ contaminated_lot │     3 │
  └──────────────────┴───────┘

  Failures by supplier
  ┏━━━━━━━━━━┳━━━━━━━━━━┓
  ┃ Supplier ┃ Failures ┃
  ┡━━━━━━━━━━╇━━━━━━━━━━┩
  │ SUP-B    │       46 │
  │ SUP-D    │       32 │
  │ SUP-E    │       28 │
  │ SUP-A    │       24 │
  │ SUP-C    │       21 │
  └──────────┴──────────┘
```

**What to notice.** The most frequent attributed cause is
`process_only` (66 failures) — *not* the supplier. SUP-B is #1 by
supplier failure count, but the gap to SUP-D is only 14 — too narrow
for a confident "quarantine the top supplier" call. That's the gap the
causal layer closes in Stage 4.

> **A note on the heuristic attribution.** The categories in "Failures
> by attributed cause" are *heuristic labels* assigned inside the
> generator (the sampler picks the single *dominant* cause per
> failure). So `contaminated_lot = 3` is *not the count of every
> failure influenced by LOT-0047* — only the 3 where the lot's
> standalone effect was dominant. LOT-0047's *total* failure count
> shows up in 4a's traceability table as **10** (out of the 12
> traceable products from that lot).

### Stage 4 — verify with ontorag

```bash
uv run python scripts/02_load_ontorag.py   # schema + ABox + BN + Causal → Fuseki
```

```text
GRAPH_STORE = fuseki, ontology scope = 'manufacturing-demo'
  TBox  → 109 triples (.../manufacturing.ttl)
  ABox  → 14010 triples (data/generated/manufacturing-instances.ttl)
  BN    → 97 CPT statements stored
  Causal → 35 DAG statements stored
```

#### 4a) L1 SPARQL traceability

```bash
uv run python scripts/03_run_trace.py
```

```text
───────────────────── L1 SPARQL — failures per lot (top 5) ─────────────────────
┏━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Rank ┃ Lot                     ┃ SPARQL count ┃ Ground truth ┃ Match ┃
┡━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━┩
│    1 │ LOT-0047 (contaminated) │           10 │           10 │ ✓     │
│    2 │ LOT-0027                │            9 │            9 │ ✓     │
│    3 │ LOT-0005                │            8 │            8 │ ✓     │
│    4 │ LOT-0014                │            8 │            8 │ ✓     │
│    5 │ LOT-0017                │            8 │            8 │ ✓     │
└──────┴─────────────────────────┴──────────────┴──────────────┴───────┘

────────────────────── L1 SPARQL — failures per supplier ───────────────────────
┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Supplier        ┃ SPARQL count ┃ Ground truth ┃
┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ SUP-B (suspect) │           46 │           46 │
│ SUP-D           │           32 │           32 │
│ SUP-E           │           28 │           28 │
│ SUP-A           │           24 │           24 │
│ SUP-C           │           21 │           21 │
└─────────────────┴──────────────┴──────────────┘

─────── L1 SPARQL — assembly-step condition vs failures (observational) ───────
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Assembly condition ┃ Failures ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ low                │      110 │
│ normal             │       41 │
└────────────────────┴──────────┘

Sanity check — products traceable to LOT-0047
  12 products: PRD-00047, PRD-00097, PRD-00147, PRD-00197, PRD-00247, PRD-00297, ...
```

**What to notice.** Every count matches the ground truth exactly,
meaning the multi-hop SPARQL JOIN
(`QCResult ← Product ← ProcessRun ← Component ← Lot ← Supplier`)
walks the schema correctly. The contaminated lot surfaces at rank #1
— **10 of the 12 traceable products from that lot fail (≈83%), ~3×
the population-wide 25.2% rate** (this is the *lot signal's
strength*). The `assembly condition vs failures` table is
*correlative only* — 110 vs 41 looks like a smoking gun, but L1
can't prove it's causal.

#### 4b) L2 posterior + L3 do() + counterfactual

```bash
uv run python scripts/04_run_causal.py
```

```text
      L2 / L3 — P(ProductDefect = fail) under different queries
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━┓
┃ Query                                    ┃ P(fail) ┃ Δ vs baseline ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━┩
│ baseline (marginal)                      │   0.265 │        +0.000 │
│ see(SupplierQuality=bad)                 │   0.467 │        +0.202 │
│ do(SupplierQuality=good)  [L3]           │   0.197 │        −0.067 │
│ do(AssemblyPressure=normal)  [L3]        │   0.131 │        −0.134 │
│ do(both)                     [L3]        │   0.064 │        −0.200 │
│ counterfactual: pressure had been normal │   0.222 │        −0.042 │
└──────────────────────────────────────────┴─────────┴───────────────┘
```

**What to notice — the demo's punchline.**

> **Two kinds of "baseline".** The table's `baseline (marginal) =
> 0.265` is the **BN's marginal P(fail)** (computed by variable
> elimination). Separately, the **observed rate in the synthetic data
> is 25.2% (151/600)** — see the Stage 3 output. The two being close
> is the *generator ↔ inference-model consistency check* (both share
> the same CPTs, so alignment is automatic). All Δ values are against
> the *model baseline of 0.265*.

* `see(SupplierQuality=bad) = 0.467` makes SUP-B look like the obvious
  culprit. This is the **observational / L2** view.
* `do(SupplierQuality=good)` only drops P(fail) by **0.07**.
  Intervention is much weaker than the correlation suggested.
* `do(AssemblyPressure=normal)` drops P(fail) by **0.13** — *almost
  twice as much* as the supplier intervention. **The process is the
  bigger lever.**
* `do(both)` is ***near-additive***: the observed −0.200 ≈ the sum of
  the two single interventions (0.067 + 0.134 = 0.201). The two
  causal paths aren't in a parent-child relationship on the DAG, so
  they're nearly independent — *close to but not exactly additive*.
  Operationally: "fix both and expect roughly the sum of their
  effects" is the right intuition.
* `counterfactual = 0.222` answers a *per-instance* question: "this
  specific product failed under low pressure — had pressure been
  normal, P(fail) would have been 22%". That's Pearl Rung 3, and no
  L1/L2 query can produce it.

### Stage 5 — close the loop with ontorag-flow

```bash
uv run python scripts/05_run_flow.py
```

```text
────────────────── Process urn:demo:manufacturing:process:rca ──────────────────
goal:        {'rca_complete': True}
actions:     5
rules:       4
requires:    {'EvaluateIntervention': ['PinpointSuspectLot'],
              'RequestQuarantineApproval': ['EvaluateIntervention'],
              'QuarantineLot': ['RequestQuarantineApproval'],
              'CounterfactualReplay': ['QuarantineLot']}

opened urn:ontorag-flow:case:<uuid> with defect rate 25%

──────────────── Phase 1 — automatic (RuleEngine until suspend) ────────────────
  #1 picks PinpointSuspectLot       (conf 0.95) — narrow scope with L1 traceability.
  #2 picks EvaluateIntervention     (conf 0.95) — separate process from parts via do().
  #3 picks RequestQuarantineApproval (conf 1.00) — policy: ABox write-back is human-gated.
  status after phase: suspended

──────────────────────── Phase 2 — human approval gate ─────────────────────────
  reason: 'L3 evaluation recommends an intervention; lot quarantine requires sign-off.'
  ...simulating the operator clicking 'approve' ...

────────────────── Phase 3 — ABox write-back (QuarantineLot) ───────────────────
  wrote: mfg:quarantined = true on LOT-0047
  (https://ontorag-demo.dev/manufacturing#lot/LOT-0047)

────────────── Phase 4 — counterfactual replay (closes the case) ───────────────
  #1 picks CounterfactualReplay (conf 1.00) — record the "what if" for the audit trail.
  status after phase: closed

──────────────────────────────── Audit trail ───────────────────────────────────
                     PROV-O activities
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ # ┃ Action                    ┃ Agent        ┃ Status    ┃
┡━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ 1 │ PinpointSuspectLot        │ urn:demo:ops │ completed │
│ 2 │ EvaluateIntervention      │ urn:demo:ops │ completed │
│ 3 │ RequestQuarantineApproval │ urn:demo:ops │ completed │
│ 4 │ QuarantineLot             │ urn:demo:ops │ completed │
│ 5 │ CounterfactualReplay      │ urn:demo:ops │ completed │
└───┴───────────────────────────┴──────────────┴───────────┘

PROV-O Turtle export: runs/flow/audit.ttl (6860 bytes)

──────────────────────────── Final case state ──────────────────────────────────
  rca_complete: True
  quarantined: True
  quarantined_lot_uri: https://ontorag-demo.dev/manufacturing#lot/LOT-0047
  suspect_lot_id: LOT-0047            (10 failures)
  baseline_p_fail: 0.2645
  intervention_p_fail: {'supplier_only': 0.1971,
                        'process_only': 0.1307,
                        'supplier_and_process': 0.0644}
  recommended_intervention: supplier_and_process
  counterfactual_p_fail: 0.2222
```

#### Verify the write-back actually landed in ontorag

```bash
curl -s 'http://localhost:3030/ontorag/sparql' \
  --data-urlencode 'query=
    PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>
    SELECT ?lotId WHERE { ?lot mfg:lotId ?lotId ; mfg:quarantined true . }' \
  -H 'Accept: application/sparql-results+json'
```

```json
{
  "head": {"vars": ["lotId"]},
  "results": {
    "bindings": [
      { "lotId": {"type": "literal", "value": "LOT-0047"} }
    ]
  }
}
```

The triple wrote back is visible to *any* downstream SPARQL consumer —
that's the "closed loop" half of plan §6.

---

## Plan §6 component coverage

| `ontorag` / `ontorag-flow` capability | Where the demo exercises it | Visible in output |
|---|---|---|
| L0 storage (Fuseki/Neo4j/FalkorDB) | `02_load_ontorag.py` via `create_store()` | `TBox → 109 triples` line |
| L1 logic (multi-hop traversal) | `verify/trace.py` SPARQL JOINs | Stage 4a tables |
| L2 probabilistic (`compute_posterior`) | `verify/causal.py::observational_supplier_bad` | `see(SupplierQuality=bad) = 0.467` |
| L3 interventional (`do_query`) | `verify/causal.py::do_*` | `do(...) [L3]` rows |
| L3 counterfactual | `verify/causal.py::counterfactual_assembly_was_normal` | `counterfactual: 0.222` |
| Decision engine (6 kinds) | `flow/process.yaml` RuleEngine (4 rules + 4 `requires` constraints) | "#1..#3 picks" log lines |
| Case + state machine + saga | `flow/runner.py` via `CaseManager` | `open → suspended → open → closed` lifecycle |
| Provenance (PROV-O) | exported to `runs/flow/audit.ttl` | "PROV-O activities" table |
| Write-back (`AssertTriple`-equivalent) | `flow/writeback.py` SPARQL UPDATE | `LOT-0047` returned from the verify curl |

The intentional deviation from plan §6: the demo bypasses
ontorag-flow's MCP client and calls ontorag's Python API directly
inside the custom actions, so a single `uv run` driver runs the whole
loop without spinning up two HTTP services. Swapping back to the MCP
transport means replacing the constructor in
`flow/actions.py::build_domain_actions` with `ontorag_flow`'s
`with_triple_actions(client)`.

---

## Tests

```bash
uv run pytest -q
```

```text
...........                                                              [100%]
11 passed, 1 warning in 5.01s
```

11 tests cover BN/Causal invariants (CPT row sums, DAG edge mirroring),
the data generator's determinism + contamination signal, and the
"process > supplier" claim at the engine level. None of them need
Fuseki.

---

## License

MIT.
