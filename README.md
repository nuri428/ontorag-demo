# ontorag-demo

Synthetic manufacturing traceability + causal-RCA demo built on
[`ontorag`](https://github.com/nuri428/ontorag) (Semantic + Dynamic
reasoning) and [`ontorag-flow`](https://github.com/nuri428/ontorag-flow)
(Kinetic / Adaptive Case Management).

The design rationale is in [`ontorag_flow_demo_plan.md`](./ontorag_flow_demo_plan.md);
this README only covers *how to run it* and *what the output means*.

## The story this demo tells

A finished-goods QC pipeline shows a defect rate that's higher than
operations expected. Two questions follow, and they're hard to answer
*at the same time* without an ontology-aware reasoning stack:

1. **Trace narrowly** — *which lots / suppliers / process runs* are
   over-represented in the failing products? (L1, multi-hop SPARQL.)
2. **Explain causally** — once you've narrowed scope, is the dominant
   cause *the parts* (supplier / lot quality) or *the process*
   (assembly-step condition)? Naive aggregation conflates them; only
   `do(SupplierQuality=good)` vs `do(AssemblyPressure=normal)`
   separates them. (L3, Pearl Rung 2 + 3.)

Then close the loop:

3. **Act with audit** — propose → score interventions → human approval →
   write `mfg:quarantined=true` back into ontorag's ABox →
   counterfactual replay (`what if we had not quarantined?`) → PROV-O
   activity log for forensic recall.

## Layout

```
ontorag-demo/
├── ontorag_flow_demo_plan.md   # design rationale (read first)
├── vendor/                     # local-only checkouts (gitignored — see Prerequisites)
│   ├── ontorag/                # clone of https://github.com/nuri428/ontorag
│   └── ontorag-flow/           # clone of https://github.com/nuri428/ontorag-flow
├── src/ontorag_demo/
│   ├── schema/                 # Stage 1 — OWL/Turtle TBox
│   ├── causal/                 # Stage 2 — Bayesian network + Causal DAG
│   ├── generator/              # Stage 3 — synthetic data sampler + RDF writer
│   ├── verify/                 # Stage 4 — SPARQL traceability + posterior/do/CF
│   └── flow/                   # Stage 5 — ontorag-flow actions + process YAML
├── scripts/                    # Numbered entry points (run in order)
│   ├── 01_generate_data.py
│   ├── 02_load_ontorag.py
│   ├── 03_run_trace.py
│   ├── 04_run_causal.py
│   └── 05_run_flow.py
├── tests/                      # pytest — unit + invariant tests
├── data/generated/             # produced by 01 (gitignored)
└── runs/flow/                  # produced by 05 (gitignored)
```

## Prerequisites

* Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).
* A running Fuseki at `FUSEKI_URL` (default `http://localhost:3030`)
  with a dataset named in `FUSEKI_DATASET` (default `ontorag`). Two ways
  to get one:

  ```bash
  # A) Use the ontorag submodule's compose (recommended — pre-tested combo).
  cd vendor/ontorag && docker compose up -d

  # B) Or run any Fuseki 5.x image yourself on :3030 with dataset "ontorag".
  ```

  The demo writes under the named-graph scope `manufacturing-demo`, so
  it won't collide with whatever else is in that Fuseki instance.

* Local vendor checkouts. `vendor/` is gitignored — every developer
  brings their own clone, and `pyproject.toml`'s `[tool.uv.sources]`
  points editable installs at those paths. Bootstrap:

  ```bash
  mkdir -p vendor
  git clone https://github.com/nuri428/ontorag.git       vendor/ontorag
  git clone https://github.com/nuri428/ontorag-flow.git  vendor/ontorag-flow
  ```

  To track a specific revision, just `git checkout <sha>` inside each
  vendor clone — nothing in this repo will record the pin, so write
  the SHA into a note for your team if reproducibility matters.

## Five-stage walkthrough

```bash
uv sync --extra dev
cp .env.example .env       # optional — defaults are fine if Fuseki is on :3030
```

### Stage 1 — schema (no code to run)

`src/ontorag_demo/schema/manufacturing.ttl` defines the TBox
(7 classes, 12 properties). It's loaded automatically by Stage 4. The
key design choice is **discrete process conditions on `ProcessRun`** so
pgmpy can consume them without a binning preprocessor (plan §2).

### Stage 2 — causal model (no code to run)

`src/ontorag_demo/causal/model.py` declares the Bayesian network and
the causal DAG side-by-side from a single source of truth. The same
spec quantifies the data generator (Stage 3) *and* the
posterior / do / counterfactual engines (Stage 4). 7 nodes, one
interaction (`ProductDefect ← ComponentQuality × AssemblyPressure`),
two independent process noise variables — the smallest model that
still makes "is it parts or process?" a non-trivial question.

### Stage 3 — generate synthetic data

```bash
uv run python scripts/01_generate_data.py
```

Writes:
* `data/generated/manufacturing-instances.ttl` — RDF ABox
  (~14k triples; 5 suppliers, 50 lots, 600 products).
* `data/generated/ground_truth.json` — the latent answers (which lot is
  contaminated, which supplier is suspect, per-supplier/per-lot
  failure counts).

The summary shown by the script highlights the **deliberate
under-determinacy**: SUP-B (the seeded suspect) shows up #1 in
per-supplier failures, but the gap to SUP-D is too small for a simple
"quarantine the top supplier" decision to be obviously correct. That's
the gap Stage 4's causal layer closes.

### Stage 4 — verify with ontorag (single-pass + reasoning)

```bash
uv run python scripts/02_load_ontorag.py    # schema + ABox + BN + Causal DAG → Fuseki
uv run python scripts/03_run_trace.py       # L1 SPARQL traceability vs ground truth
uv run python scripts/04_run_causal.py      # L2 posterior + L3 do() + counterfactual
```

`03_run_trace.py` runs three multi-hop SPARQL queries (failures per lot
/ per supplier / per assembly condition) and shows that each result
matches the ground truth byte-for-byte. The contaminated lot
(`LOT-0047`) lands at rank #1 with the expected failure count.

`04_run_causal.py` prints the table that *is* the demo's punchline:

| Query | P(fail) | Δ vs baseline |
|---|---|---|
| baseline (marginal) | 0.265 | — |
| see(SupplierQuality=bad)  [L2, correlative] | 0.467 | +0.20 |
| do(SupplierQuality=good)  [L3] | 0.197 | −0.07 |
| do(AssemblyPressure=normal)  [L3] | 0.131 | **−0.13** |
| do(both)  [L3] | 0.064 | −0.20 |
| counterfactual (had pressure been normal) | 0.222 | −0.04 |

The 0.467 row says *"supplier looks like the obvious villain"*. The
0.131 vs 0.197 split says *"actually, the process is almost twice as
big a lever as the supplier."* No L1 query can produce that split —
that's the reason the causal layer exists.

### Stage 5 — close the loop with ontorag-flow

```bash
uv run python scripts/05_run_flow.py
```

Drives one RCA case end-to-end:

```
Phase 1 (RuleEngine drives until human handoff)
  #1 PinpointSuspectLot       — L1 SPARQL → LOT-0047 (10 failures)
  #2 EvaluateIntervention     — L3 do() scoring → recommends supplier+process
  #3 RequestQuarantineApproval — HUMAN side effect → case suspends
Phase 2 (operator approves; runner resumes)
Phase 3 (ABox write-back)
  QuarantineLot               — SPARQL UPDATE writes mfg:quarantined=true
Phase 4 (close)
  CounterfactualReplay        — Pearl Rung 3 → rca_complete=true → CLOSED
```

Outputs:
* `runs/flow/audit.ttl` — PROV-O Turtle activity log (5 activities).
* `runs/flow/case_state.json` — final case state including the L3
  intervention rankings and the counterfactual verdict.

Verify the write-back actually landed in ontorag:

```bash
curl -s 'http://localhost:3030/ontorag/sparql' \
  --data-urlencode 'query=
    PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>
    SELECT ?lotId WHERE { ?lot mfg:lotId ?lotId ; mfg:quarantined true . }' \
  -H 'Accept: application/sparql-results+json'
```

→ `LOT-0047`.

## Plan §6 component coverage

| `ontorag` / `ontorag-flow` capability | Where the demo exercises it |
|---|---|
| L0 storage (Fuseki/Neo4j/FalkorDB) | `02_load_ontorag.py` via `create_store()` |
| L1 logic (multi-hop traversal) | `verify/trace.py` SPARQL JOINs |
| L2 probabilistic (`compute_posterior`) | `verify/causal.py::observational_supplier_bad` |
| L3 interventional (`do_query`) | `verify/causal.py::do_*` |
| L3 counterfactual | `verify/causal.py::counterfactual_assembly_was_normal` |
| Decision engine (6 kinds) | `flow/process.yaml` RuleEngine (4 rules + 4 `requires` constraints) |
| Case + state machine + saga | `flow/runner.py` via `CaseManager` |
| Provenance (PROV-O) | `runs/flow/audit.ttl` exported via `ontorag_flow.core.provenance.render` |
| Write-back (`AssertTriple`-equivalent) | `flow/writeback.py` SPARQL UPDATE (the self-contained MCP-less analogue) |

The only intentional deviation from plan §6: the demo bypasses
ontorag-flow's MCP client and calls ontorag's Python API directly
inside the custom actions, so a single `uv run` driver can execute the
whole loop without spinning up two HTTP services. Swapping back to the
MCP transport is a matter of replacing the constructor in
`flow/actions.py::build_domain_actions` with `ontorag_flow`'s
`with_triple_actions(client)`.

## Tests

```bash
uv run pytest -q                  # unit tests (no Fuseki needed)
```

11 tests cover BN/Causal invariants (CPT row sums, DAG edge mirroring),
the data generator's determinism + contamination signal, and the
"process > supplier" claim at the engine level.

## License

MIT.
