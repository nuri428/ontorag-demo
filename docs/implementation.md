# Implementation notes — problem-solving process and how the code was shaped

> **🇰🇷 한국어:** [implementation.ko.md](./implementation.ko.md)
> **Related:** [walkthrough.md](./walkthrough.md) (how each answer is derived) · [dev_guide.md](./dev_guide.md) (working on top of this) · [README.md](../README.md) (runbook)

This document sits one layer above `walkthrough.md`.
Where walkthrough covered *"how the answer is derived"*, this one
covers **"why the code looks the way it looks"** — what problems came
up while translating five abstract reasoning stages into actual
Python / Turtle / YAML, what options were considered, what was chosen,
and where that decision physically lives in the codebase.

12 decisions, each in the same five-block shape:

| Block | Meaning |
|---|---|
| **Problem** | What was blocking, why it was non-trivial |
| **Options** | The 2–4 alternatives that were seriously considered |
| **Choice + rationale** | Which option won, what the trade-off is |
| **Code applied** | Which file / function / lines that decision became |
| **Validation / effect** | What evidence shows the decision actually worked |

---

## Prelude — four principles that thread through all 12 decisions

These were settled before any code was written. Every decision below
reduces to one of these four:

1. **Single source of truth.** The BN's CPTs must be the *same object*
   in both data generation and inference. Once they drift, the demo
   starts lying to itself.
2. **Deterministic.** `random_seed=20260601` pinned. Two runs produce
   byte-identical outputs. That's the precondition for being able to
   *embed* results into README/walkthrough.
3. **Ground-truth-comparable.** The generator *knows* the answers. It
   exports them to a separate JSON so Stage 4 verification can compare
   ontorag's responses byte-for-byte.
4. **No premature abstraction.** The demo is one scenario. Imagined
   "what if we reuse this for a different domain later" requests are
   ignored. Code stays minimal, direct, *what's needed right now*.

---

## Decision 1 — How much "noise" to inject into the synthetic data

### Problem

Plan §3's central trap: if SUP-B is "100% bad, others 0% bad," and
ontorag gets the answer right, *that's not because the system is
smart — the data is just trivial*. Demo value: zero.

### Options

- **A. Pure random.** P(bad) identical across suppliers. → Supplier
  signal vanishes, traceability has no value.
- **B. Light noise.** SUP-B *slightly* above the base rate. → Captures
  the intent but lot-level anomalies stay invisible.
- **C. Two-layer noise.** SUP-B with ~4× the base rate + a specific
  contaminated lot. → Plan §3 verbatim.

### Choice + rationale

**C.** The two anomalies need to live at *different abstraction levels*
(supplier vs lot) so that L1 traceability and L3 do-queries can reveal
*different facts*. If SUP-B were uniformly bad across all its lots,
the lot-level drilldown would be meaningless.

### Code applied

`src/ontorag_demo/causal/model.py`:

```python
SUPPLIER_PROFILES: tuple[SupplierProfile, ...] = (
    SupplierProfile("SUP-A", 0.10),
    SupplierProfile("SUP-B", 0.55, is_suspect=True),  # 4× baseline
    SupplierProfile("SUP-C", 0.15),
    SupplierProfile("SUP-D", 0.12),
    SupplierProfile("SUP-E", 0.18),
)

@dataclass(frozen=True)
class GeneratorConfig:
    contaminated_lot_index: int = 47
    contaminated_bad_rate: float = 1.0      # lot #47 is *definitively* contaminated
```

And in `generator/sampler.py`, the two anomalies apply at the lot level:

```python
supplier_quality = "bad" if rng.random() < profile.bad_quality_rate else "good"
is_contaminated = i == config.contaminated_lot_index
if is_contaminated:
    lot_quality = "bad" if rng.random() < config.contaminated_bad_rate else "good"
else:
    lot_quality = _sample_binary(rng, "LotQuality", (supplier_quality,))
```

### Validation / effect

First run (`num_products=300`, `contaminated_bad_rate=0.95`) had
LOT-0047 showing *only 1 failure* — too weak a signal. That meant *the
demo's message was getting diluted*, so two immediate tweaks:

- `num_products: 300 → 600` (12 per lot → expected failures of 5+)
- `contaminated_bad_rate: 0.95 → 1.0` (remove the uncertainty)

Re-run: LOT-0047 at 10 failures, rank #1 — exactly the picture the
demo needed. That tuning itself is locked in by
`tests/test_generator.py::test_contaminated_lot_dominates` (which
asserts `top_count >= 5`).

---

## Decision 2 — Continuous vs discrete process conditions in the schema

### Problem

Real-world process conditions are continuous (23.4°C, 0.87 bar). pgmpy
only handles *discrete* variables. How do you bridge?

### Options

- **A. Store continuous, discretise at inference time.** TBox declares
  `xsd:decimal`, Stage 4 calls `discretize()` before reasoning. → Two
  models (continuous / discrete) to maintain, code complexity goes up.
- **B. Discrete from day one.** `mfg:condition` is an `xsd:string`
  ("normal"/"low"/"high"). pgmpy consumes it directly. → We're
  synthetic, so we don't need fake continuous sensor values.

### Choice + rationale

**B.** Plan §2's explicit decision: "since we're synthetic, design as
discrete from day one — no discretise preprocessor needed." This is
the spot where a real-data version would need a binning stage; we get
to skip it as the upside of synthetic.

### Code applied

`src/ontorag_demo/schema/manufacturing.ttl`:

```turtle
mfg:condition a owl:DatatypeProperty ;
    rdfs:label "condition" ;
    rdfs:domain mfg:ProcessRun ;
    rdfs:range  xsd:string ;
    rdfs:comment "Discrete state of the process condition recorded by this run (e.g., 'normal' / 'high' / 'low')." .
```

And the BN node specs declare the discrete states directly:

```python
NodeSpec("AssemblyPressure", ("normal", "low")),
NodeSpec("MachiningTemperature", ("normal", "high")),
NodeSpec("InspectionMoisture", ("normal", "high")),
```

### Validation / effect

`02_load_ontorag.py` loads schema (109 triples) and ABox (14,010
triples) end-to-end with zero conversion steps. `04_run_causal.py`
reasons over the BN with no separate discretisation. About 100 LOC
saved (no binning logic).

---

## Decision 3 — Don't write CPTs by hand

### Problem

pgmpy's CPT is a 2D array under "last evidence varies fastest"
convention. For a 2-parent node like ProductDefect that's 4 columns —
get the order wrong and the data ↔ model alignment is silently
broken (and hard to spot).

### Options

- **A. Hand-write lists of lists.** Matches ontorag's smoking example.
  → Tolerable for 4 columns, hellish beyond.
- **B. dict (parent_assignment → P(state0)) + a helper that translates.**
  Natural human notation + the convention is encapsulated inside the
  helper.

### Choice + rationale

**B.** Data should *read at face value*. Column-index mechanics belong
inside a helper. The helper also enforces that every CPD is binary —
`assert len(spec.states) == 2`.

### Code applied

`src/ontorag_demo/causal/model.py`:

```python
def _binary_cpd(
    variable: str,
    evidence: tuple[str, ...],
    p_state0: dict[tuple[str, ...], float],
) -> CPD:
    """Build a 2-state CPD where ``p_state0`` gives P(state[0] | parents)."""
    spec = NODES_BY_NAME[variable]
    assert len(spec.states) == 2, f"{variable} must be binary"
    if evidence:
        parent_specs = [NODES_BY_NAME[p] for p in evidence]
        columns: list[tuple[str, ...]] = [()]
        for parent in parent_specs:
            columns = [c + (s,) for c in columns for s in parent.states]
        row0 = [p_state0[col] for col in columns]
    else:
        row0 = [p_state0[()]]
    row1 = [round(1.0 - v, 6) for v in row0]
    return CPD(variable=spec.uri, evidence=[...], values=[row0, row1])
```

So ProductDefect's CPT reads like:

```python
_binary_cpd("ProductDefect", ("ComponentQuality", "AssemblyPressure"), {
    ("good", "normal"): 0.98,
    ("good", "low"): 0.65,
    ("bad", "normal"): 0.50,
    ("bad", "low"): 0.15,
}),
```

Line-by-line, this *is* the meaning. Column indices 0–3 exist only
inside the helper.

### Validation / effect

`tests/test_causal_model.py::test_cpd_rows_sum_to_one` guarantees each
column of every CPT sums to 1.0 — `1.0 - p` auto-compute floats clean.
11/11 tests pass.

---

## Decision 4 — Why the data generator *doesn't* use `pgmpy.forward_sample`

### Problem

pgmpy has `BayesianModelSampling.forward_sample()` that would sample
from the BN in 3 lines. But two requirements rule it out:

1. **Per-entity anomaly injection** (SUP-B's P(bad)=0.55, lot #47
   forced contamination) — none of this is expressible in the BN's
   marginal CPTs.
2. **Latent state tracking** — each product's actual supplier_quality
   / lot_quality / component_quality has to be preserved in
   `ground_truth.json` for verification. pgmpy returns only the
   queried variables.

### Options

- **A. forward_sample + post-patch.** Sample first, then patch
  supplier-specific labels afterwards. → Two-stage consistency breaks.
- **B. Hand-write the sampler, but borrow the BN's CPTs.** Sampling
  logic is ours; probability values are looked up directly from the
  BN's `_CPDS`. → Data ↔ model consistency preserved, we get the
  control we need.

### Choice + rationale

**B.** The "optimised forward sampling" pgmpy provides has zero value
at our scale (600 products). What we win instead: *full control over
anomaly injection and latent-state retention*.

### Code applied

`src/ontorag_demo/generator/sampler.py`:

```python
from ontorag_demo.causal.model import _CPDS  # same object!

def _conditional_prob(node_name: str, state: str, parent_assignment: tuple[str, ...]) -> float:
    cpd = _cpd_for(node_name)
    # ... applies pgmpy column ordering as-is
    return cpd.values[row][col]

def _sample_binary(rng, node_name: str, parent_assignment: tuple[str, ...]) -> str:
    states = NODES_BY_NAME[node_name].states
    p_first = _conditional_prob(node_name, states[0], parent_assignment)
    return states[0] if rng.random() < p_first else states[1]
```

The critical line: `from ontorag_demo.causal.model import _CPDS` — the
CPTs the sampler reads are *physically the same Python objects* as
the CPTs that get loaded into the BN. If anyone mutates `_CPDS`, the
sampler and the inference engine reflect that mutation simultaneously.
Drift is *structurally impossible*.

### Validation / effect

`tests/test_verify_causal.py::test_baseline_matches_expected_marginal`
asserts the baseline P(fail) sits within 0.20–0.32. In practice:
0.265 (BN inference) ≈ 0.252 (observed rate in the sampled data).
The closeness of those two numbers is itself the alignment proof.

---

## Decision 5 — Where to put the async/sync boundary

### Problem

ontorag's store API is *all async* (`load_rdf`, `_sparql_select`,
`put_bayes_network`, ...). The data generator (`generator/run.py`) is
CPU-bound sampling — natural fit for sync. How do they mix?

### Options

- **A. Everything async.** `async def` even for the sampler. → No
  benefit (no I/O), complicates tests (every fixture needs asyncio
  mode).
- **B. Sampler is sync; only scripts/02–05 are async.** Boundary is
  explicit.

### Choice + rationale

**B.** async earns its keep when there's I/O waiting. Sampling is pure
computation → sync. Scripts call ontorag → async. The boundary
between the two zones is at entry points like
`scripts/02_load_ontorag.py` where `asyncio.run()` makes the handoff
explicit.

### Code applied

`generator/run.py`:

```python
def generate(config, output_dir) -> GeneratorOutput:
    """The function is deliberately synchronous — sampling is CPU-bound and
    keeping it sync makes it trivial to call from tests without spinning
    up an event loop."""
```

`scripts/02_load_ontorag.py`:

```python
async def _load(schema_path: Path, data_path: Path, ontology: str | None) -> None:
    store = create_store()
    schema_result = await store.load_rdf(...)
    ...

@app.command()
def main(...) -> None:
    asyncio.run(_load(...))
```

### Validation / effect

Test code (`test_generator.py`) uses plain `@pytest.fixture` with no
async-scope complications. The `asyncio_mode = "auto"` in pyproject
covers the verify-causal tests, but the sampler tests are untouched
by it.

---

## Decision 6 — Why expose *raw SPARQL* in Stage 4 traceability

### Problem

ontorag offers *three interfaces* for the same traceability question:

- **L1**: `find_entities` + `traverse_graph` (intent-based, MCP-exposed)
- **L2**: `query_pattern` (JSON DSL → auto-translated to SPARQL)
- **L3 dev**: `_sparql_select` (raw SPARQL)

Which one does the demo use?

### Options

- **A. L1.** Safest, MCP-exposed. → Multi-hop + GROUP BY + COUNT
  doesn't compose cleanly out of L1 helpers.
- **B. L2 (query_pattern).** JSON-encoded triple patterns. → COUNT /
  GROUP BY aren't first-class citizens, expression becomes awkward.
- **C. Raw SPARQL.** Call `_sparql_select` directly. → Full SPARQL 1.1
  expressivity.

### Choice + rationale

**C.** One of the demo's lessons is *"a well-designed schema makes a
5-hop SPARQL JOIN solve traceability cleanly."* To teach that lesson
the SPARQL has to be *visible*. Abstracting it behind L1/L2 hides
the message. It also lets a first-time reader literally see *"yes,
this is really a 5-hop join"* when they ask.

### Code applied

`src/ontorag_demo/verify/trace.py`:

```python
_PREFIXES = f"""
PREFIX mfg:  <{NAMESPACE}>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

async def failures_per_lot(store, limit=10) -> list[LotFailureCount]:
    sparql = _PREFIXES + """
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
    """ + f"LIMIT {int(limit)}\n"

    result = await store._sparql_select(sparql)
    return [LotFailureCount(lot_id=r["lotId"], failure_count=int(r["failures"]))
            for r in _iter_rows(result)]
```

Plus an `_iter_rows()` helper that normalises SPARQL's JSON results
format (`{"head": ..., "results": {"bindings": [{var: {value}}]}}`)
into plain `[{var: value}]` — so each query function processes results
in two lines.

### Validation / effect

walkthrough.md's Q1–Q4 can quote the *exact SPARQL*. If we'd hidden it
behind L2, that section would have become "JSON pattern" and the
reader would have to mentally reverse-engineer the SPARQL.

---

## Decision 7 — Why L2/L3 verification runs *without* Fuseki

### Problem

`compute_posterior` and `do_query` are ontorag methods. Two ways to
apply them:

- **A. Through Fuseki.** `put_bayes_network(BN)` to store → `get_bayes_network()`
  to retrieve → `BayesianEngine(bn)` to reason.
- **B. In-memory directly.** Call `BayesianEngine(MANUFACTURING_BN)`
  immediately.

A exercises the full stack but requires Fuseki running. B is fast and
independent but skips ontorag's Turtle round-trip.

### Options

Both, separated by responsibility. Key question: *what does each
script need?*

### Choice + rationale

**Use both, with split responsibility:**

- `02_load_ontorag.py` calls `put_bayes_network(MANUFACTURING_BN)` →
  exercises ontorag's storage path (= path A).
- `04_run_causal.py` uses `BayesianEngine(MANUFACTURING_BN)` directly
  → CI / local verification runs without Fuseki (= path B).

Since the same BN object (`MANUFACTURING_BN`) flows into both, the two
paths' consistency is automatic.

### Code applied

`src/ontorag_demo/verify/causal.py`:

```python
def _engines() -> tuple[BayesianEngine, CausalEngine]:
    """Build the engine pair once; engines are stateless wrappers."""
    bn_engine = BayesianEngine(MANUFACTURING_BN)
    causal_engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)
    return bn_engine, causal_engine
```

`scripts/02_load_ontorag.py`:

```python
bn_count = await store.put_bayes_network(MANUFACTURING_BN, ontology=ontology)
console.print(f"  BN    → {bn_count} CPT statements stored")
```

### Validation / effect

`tests/test_verify_causal.py` passes all 11 tests with zero Fuseki
dependency (`uv run pytest` boots cleanly with no containers).
Meanwhile the loading path is production-ready (other ontorag clients
can discover the *shared reasoning model*).

---

## Decision 8 — Why the flow has *5* actions

### Problem

The whole RCA workflow could be one big "do everything" function. Why
five separate actions?

### Options

- **A. One mono-action.** `RunFullRCA()` that does traceability +
  causal + write-back + replay all in one. → Can't classify side
  effects, can't insert human approval, can't recover from partial
  failure.
- **B. One action = one responsibility.** Each declares its side
  effects explicitly. → ontorag-flow's framework auto-handles
  suspend/approve/audit.

### Choice + rationale

**B.** ontorag-flow's core value (HUMAN side effect → auto suspend,
ABOX_WRITE → auto_execute_disabled, PROV-O unit = action) is *built
on action-level responsibility decomposition*. A mono-action gets zero
of that framework benefit.

### Code applied

`src/ontorag_demo/flow/actions.py` — 5 action classes, each ~30–50 lines:

| Action | side_effects | auto_disabled | Meaning |
|---|---|---|---|
| `PinpointSuspectLot` | `{CASE_STATE}` | False | L1 SPARQL → state update only |
| `EvaluateIntervention` | `{CASE_STATE}` | False | L3 do_query → state update only |
| `RequestQuarantineApproval` | `{HUMAN, CASE_STATE}` | True | auto-suspends |
| `QuarantineLot` | `{ABOX_WRITE, CASE_STATE}` | True | operator click required |
| `CounterfactualReplay` | `{CASE_STATE}` | False | L3 Rung 3 → state |

side_effects *as declared* are what the framework processes:

```python
class RequestQuarantineApproval(BaseAction):
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.HUMAN, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True
```

These two lines alone make the CaseManager *automatically* transition
`OPEN → SUSPENDED`.

### Validation / effect

`05_run_flow.py`'s output shows "Phase 1 → suspended → Phase 2 (resume)
→ Phase 3 (explicit quarantine)" — the 4-phase pattern emerges
*naturally*. The runner code has zero conditionals like "if action ==
... then suspend."

---

## Decision 9 — How much should the RuleEngine automate

### Problem

Too few rules in `process.yaml` → workflow loses value. Too many →
human decision points disappear. Where's the balance?

### Options

- **A. All 5 actions as rules.** Including quarantine. → Where does
  the `lot_uri` parameter come from? RuleEngine doesn't support
  templating.
- **B. 4 actions as rules, quarantine as explicit runner call.** → A
  single special case (explicit call after resume) but the boundary
  is clear.
- **C. No rules at all, all explicit.** → Zero demo value for the
  RuleEngine.

### Choice + rationale

**B.** Rules for what can be automated (PinpointSuspectLot,
EvaluateIntervention, RequestQuarantineApproval, CounterfactualReplay).
Explicit runner call *only where dynamic params are needed*
(QuarantineLot needs suspect_lot_id injected). Borrows the supply_chain_rca
example's "wrap-up after resume" pattern.

### Code applied

`src/ontorag_demo/flow/process.yaml`:

```yaml
rules:
  - name: "High defect rate — pinpoint suspect lot first"
    when:
      defect_rate_percent: { gte: 10 }
      suspect_lot_known: false
    then:
      action: "urn:demo:manufacturing:PinpointSuspectLot"
      params: { top_n: 5 }
    confidence: 0.95
  # ... 3 more rules

  # NOTE: after the human resumes the case, the runner explicitly executes
  # QuarantineLot with the suspect lot URI (the RuleEngine doesn't template
  # params, so we mirror supply_chain_rca's "wrap-up after sign-off" pattern
  # in runner.py rather than declaring a rule with an unfilled placeholder).
```

`src/ontorag_demo/flow/runner.py`:

```python
suspect_lot_id = case.state.properties.get(SUSPECT_LOT_KEY)
if not suspect_lot_id:
    raise RuntimeError("...")
case, _ = await manager.execute_action(
    case.case_uri,
    QUARANTINE_ACTION,
    {"lot_uri": lot_uri_for(suspect_lot_id)},
)
```

### Validation / effect

`05_run_flow.py` output: Phase 1 has the RuleEngine pick 3 actions
automatically (`#1 PinpointSuspectLot ... #2 EvaluateIntervention
... #3 RequestQuarantineApproval ...`), Phase 3 only calls
QuarantineLot explicitly. The comment in process.yaml pins the
*reason* for a future reader.

---

## Decision 10 — Write-back as *direct SPARQL UPDATE* instead of `_gsp_post`

### Problem

We need to add one triple: `mfg:quarantined = true`. ontorag's write
paths:

- `load_rdf(path, mode="data")` — replaces the entire ABox
- `_gsp_post(graph, named_graph)` — GSP append to named graph (private)
- (none) SPARQL UPDATE not exposed

### Options

- **A. `load_rdf` with a single-triple Turtle.** → Re-serialises the
  whole graph (wasteful), risks replace rather than append.
- **B. Call `_gsp_post`.** → Private API (`_` prefix), breaks if
  ontorag's method renames.
- **C. POST directly to Fuseki's `/update` endpoint via httpx.** →
  Standard SPARQL 1.1 UPDATE, no ontorag internals touched.

### Choice + rationale

**C.** SPARQL UPDATE is a *standard*, so it stays safe regardless of
how ontorag evolves. DELETE+INSERT also lets us *safely replace* an
existing value — quarantining the same lot twice is idempotent.

### Code applied

`src/ontorag_demo/flow/writeback.py`:

```python
async def set_lot_quarantined(
    lot_uri: str,
    *,
    quarantined: bool = True,
    ontology: str | None = None,
) -> str:
    graph_uri = data_graph_uri(
        ontology or os.environ.get("DEMO_ONTOLOGY", "manufacturing-demo")
    )
    new_value = "true" if quarantined else "false"
    update = (
        "PREFIX mfg: <https://ontorag-demo.dev/manufacturing#>\n"
        "PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>\n"
        f"WITH <{graph_uri}>\n"
        "DELETE { ?lot mfg:quarantined ?old }\n"
        f'INSERT {{ ?lot mfg:quarantined "{new_value}"^^xsd:boolean }}\n'
        "WHERE  {\n"
        f"  BIND(<{lot_uri}> AS ?lot)\n"
        "  OPTIONAL { ?lot mfg:quarantined ?old }\n"
        "}"
    )

    async with httpx.AsyncClient(...) as client:
        response = await client.post(_build_update_url(), data={"update": update})
        response.raise_for_status()

    return update
```

Critical details:
- `WITH <graph_uri>` pins the named graph (manufacturing-demo isolation)
- `BIND(<lot_uri> AS ?lot)` so a typo'd URI doesn't silently succeed
  (DELETE affects 0 rows + INSERT affects 0 rows → externally
  detectable via SPARQL SELECT)
- `return update` preserves the *actual SPARQL sent* in the PROV-O
  activity for forensic replay

### Validation / effect

`curl ... /ontorag/sparql ... SELECT ?lotId WHERE { ... ?lot
mfg:quarantined true . }` returns `LOT-0047` → the triple really
landed. The PROV-O `QuarantineLot` activity's outputs contain
`sparql_update`, so a future reader can ask "exactly what SPARQL was
sent?" and get the answer.

---

## Decision 11 — Runner's 4-phase structure

### Problem

`CaseManager.propose_next()` returns "next candidate actions."
`execute_action()` runs one. How do you build an *auto-loop* from
these two? And how does it interact with HUMAN suspend?

### Options

- **A. One `while OPEN: propose+execute` loop.** → How do you inject
  the explicit quarantine call between suspend and resume?
- **B. Explicit phase split.** Phase 1 (loop), Phase 2 (resume),
  Phase 3 (explicit), Phase 4 (loop).

### Choice + rationale

**B.** Borrows supply_chain_rca's pattern. Explicit phases *read
clearly* — `05_run_flow.py` output alone tells you where what
happens. The helper `_drive_until_terminal()` encapsulates the
propose+execute loop.

### Code applied

`src/ontorag_demo/flow/runner.py`:

```python
async def run_flow(store, *, initial_defect_rate_percent=25, ...) -> FlowResult:
    # ... setup ...
    case = await manager.create_case(process.process_uri, initial_state=incident_state)

    # Phase 1
    case = await _drive_until_terminal(manager, case.case_uri, console)

    # Phase 2 + 3
    if case.status is CaseStatus.SUSPENDED:
        case = await manager.resume(case.case_uri)
        suspect_lot_id = case.state.properties.get(SUSPECT_LOT_KEY)
        case, _ = await manager.execute_action(
            case.case_uri, QUARANTINE_ACTION,
            {"lot_uri": lot_uri_for(suspect_lot_id)},
        )
        # Phase 4
        case = await _drive_until_terminal(manager, case.case_uri, console)

    # Audit export
    activities = await case_store.list_by_case(case.case_uri)
    ttl_path.write_text(render(activities, "ttl"), encoding="utf-8")
    return FlowResult(...)


async def _drive_until_terminal(manager, case_uri, console):
    case = await manager.get_case(case_uri)
    while case.status is CaseStatus.OPEN:
        proposals = await manager.propose_next(case_uri)
        if not proposals:
            break
        top = proposals[0]
        case, _ = await manager.execute_action(case_uri, top.action_uri, top.params)
    return case
```

### Validation / effect

`05_run_flow.py`'s phase headers (`Phase 1 — automatic`, `Phase 2 —
human approval gate`, ...) correspond 1:1 to the code structure. When
debugging, "stuck in Phase 3" maps to a precise code location.

---

## Decision 12 — Tests verify *claims*, not code

### Problem

What should 11 tests cover? You could chase 100% line coverage, or
lock in just the *claims* the code makes.

### Options

- **A. Line coverage.** Every helper, every edge case.
- **B. Logical claims only.** Test "what the demo is trying to
  demonstrate."

### Choice + rationale

**B.** This is *not production code*. Line coverage is a
maintainability signal, not an answer. Instead: when the demo's
*lesson* would break, the tests fail immediately — i.e., only alarm
on *semantic* regressions.

### Code applied

3 test files, each one *claim group*:

`tests/test_causal_model.py` — **model structure claims**:

```python
def test_cpd_rows_sum_to_one():
    """Probabilities must sum to 1.0 — an invariant pgmpy would reject otherwise."""
    for cpd in MANUFACTURING_BN.cpds:
        for col in range(len(cpd.values[0])):
            total = sum(row[col] for row in cpd.values)
            assert total == pytest.approx(1.0, abs=1e-6)

def test_product_defect_cpt_interaction():
    """(bad, low) joint must produce max P(fail) — semantic invariant."""
    # ... assert p_fail[3] > p_fail[2] > p_fail[1] > p_fail[0]
```

`tests/test_generator.py` — **data generation claims**:

```python
def test_deterministic_with_fixed_seed(tmp_path):
    """Same seed twice → same result (so README/walkthrough numbers stay reproducible)."""
    first = generate(..., output_dir=tmp_path / "a")
    second = generate(..., output_dir=tmp_path / "b")
    assert first.ground_truth == second.ground_truth

def test_contaminated_lot_dominates(generated):
    """Contaminated lot must rank #1 — alarm if the signal weakens."""
    top_lot, top_count = sorted(...)[0]
    assert top_lot == gt.contaminated_lot_id
    assert top_count >= 5
```

`tests/test_verify_causal.py` — **the demo's core message claims**:

```python
async def test_assembly_intervention_helps_more_than_supplier_only():
    """Plan §1's narrative claim — verified at the engine level."""
    sup = await do_supplier_good()
    pres = await do_assembly_normal()
    assert pres.p_fail < sup.p_fail
```

If anyone mistakenly tweaks a CPT so "process intervention beats
supplier intervention" no longer holds, this test fails immediately
→ the README's narrative *cannot* silently desync from the code.

### Validation / effect

`uv run pytest -q` → `11 passed, 1 warning in 5.01s`. All 11 are
Fuseki-free unit tests. CI-friendly.

---

## Retrospective — three patterns across all 12 decisions

Looking back at these 12 decisions, *three common patterns* emerge:

### Pattern A — "Single source of truth, multiple consumers"

Design so the same object flows through multiple code paths.

- The BN's `_CPDS` flows into the sampler (Decision 4) and the
  BayesianEngine (Decision 7)
- `MANUFACTURING_BN` flows into both in-memory inference (Decision 7)
  and Fuseki storage (Decision 7)
- `random_seed=20260601` guarantees the same numbers in README,
  walkthrough, and tests

**Effect**: alignment verification is *automatic*. Change one place,
the rest reflect it immediately.

### Pattern B — "Standards directly; abstractions minimum"

The higher-level the framework abstraction, the more carefully it
was adopted.

- raw SPARQL `_sparql_select` (Decision 6) > query_pattern
- direct SPARQL UPDATE (Decision 10) > `_gsp_post`
- hand-written sampler (Decision 4) > `pgmpy.BayesianModelSampling.forward_sample`

**Effect**: a code reader can navigate *without the framework
manual*. SPARQL / Python knowledge alone is enough.

### Pattern C — "Ride the framework's mechanisms naturally"

Faithfully use the *primary features* of the ontorag-flow framework.

- Declare side_effects → auto suspend / auto disable (Decision 8)
- 4 rules + 4 requires in the RuleEngine → automatic phase
  progression (Decision 9)
- PROV-O activity = action unit → audit log stays automatically
  consistent (Decision 11)

**Effect**: less code + the framework provides the *intended
guardrails* for free.

---

These three patterns aren't **general software architecture
principles** — they're *this* demo's specific answers to *this*
problem (translating five reasoning stages into code). A different
domain (e.g., real data instead of synthetic; multiple workflows
instead of one) would very likely land different decisions.

The point of recording the *rationale* here is so that when someone
later edits this code, the question "why is it written like this?"
already has an answer.
