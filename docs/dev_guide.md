# Dev Guide — working *on top of* this demo

> **🇰🇷 한국어:** [dev_guide.ko.md](./dev_guide.ko.md)
> **Related:** [README.md](../README.md) · [walkthrough.md](./walkthrough.md) · [implementation.md](./implementation.md)

The other three documents are **descriptive** (what exists, how each
answer is derived, why the code is shaped this way). This one is
**prescriptive** ("to do X, modify these files in this order").

Five parts:

| Part | Covers |
|---|---|
| 1. Change recipes | How to add a new question / action / node — *where* and *in what order* |
| 2. Change-impact matrix | When you change one place, what auto-updates vs what needs manual update |
| 3. Extension points | LLM engine, MCP transport, other graph backends, real data |
| 4. Troubleshooting | Real errors you'll hit, and how to fix |
| 5. Standard dev cycle | Change → test → data → verify → docs sync loop |

---

# Part 1 — Change recipes

Each recipe follows the same five blocks:

1. **Goal** — one sentence of what you're adding/changing
2. **Files to modify (in order)** — dependency-ordered
3. **Change pattern** — copy-pasteable snippets
4. **Don't-forget checklist** — what won't be caught automatically
5. **Verification** — how to confirm the change landed as intended

---

## Recipe A — Add a new SPARQL traceability question

### Goal
e.g. "For a given supplier, which of its lots produced the most components?"

### Files to modify (in order)

1. `src/ontorag_demo/verify/trace.py` — add a new function
2. `scripts/03_run_trace.py` — call site + output (optional)
3. `tests/test_*.py` — add invariant (optional)
4. `docs/walkthrough.md` (+ `.ko.md`) — add a Q-number (optional)

### Change pattern

Add one function to `verify/trace.py`:

```python
@dataclass(frozen=True)
class LotComponentCount:
    lot_id: str
    component_count: int


async def components_per_lot_for_supplier(
    store: GraphStore, supplier_id: str
) -> list[LotComponentCount]:
    sparql = _PREFIXES + f"""
        SELECT ?lotId (COUNT(DISTINCT ?component) AS ?cnt) WHERE {{
            ?supplier mfg:supplierId "{supplier_id}" .
            ?supplier mfg:supplies ?lot .
            ?lot mfg:lotId ?lotId .
            ?lot mfg:hasComponent ?component .
        }}
        GROUP BY ?lotId
        ORDER BY DESC(?cnt)
    """
    result = await store._sparql_select(sparql)  # noqa: SLF001
    return [
        LotComponentCount(lot_id=r["lotId"], component_count=int(r["cnt"]))
        for r in _iter_rows(result)
    ]
```

### Don't forget

- [ ] `_PREFIXES` is already module-local — no extra import needed
- [ ] f-string interpolation is fine for the demo (trusted inputs), but
      **don't pass user input directly** in production — escape first
- [ ] Return type is a frozen dataclass — keeps the immutability rule
- [ ] `_iter_rows()` normalises SPARQL JSON results into plain dicts

### Verification

```bash
uv run python -c "
import asyncio
from ontorag.stores.factory import create_store
from ontorag_demo.verify.trace import components_per_lot_for_supplier

async def main():
    store = create_store()
    rows = await components_per_lot_for_supplier(store, 'SUP-B')
    for r in rows:
        print(r)

asyncio.run(main())
"
```

---

## Recipe B — Add a new domain action

### Goal
e.g. "Auto-send a Slack notification before the case closes" (= `NotifyOperator`).

### Files to modify (in order)

1. `src/ontorag_demo/flow/actions.py` — new `BaseAction` subclass + update the
   registration helper
2. `src/ontorag_demo/flow/process.yaml` — `allowed_actions` + (optional)
   `constraints.requires` + (optional) `rules`
3. `src/ontorag_demo/flow/runner.py` — explicit call if dynamic parameters
   are required
4. `tests/test_*.py` — action-level test (optional)

### Change pattern

`flow/actions.py`:

```python
class _NotifyParams(BaseModel):
    channel: str = Field(min_length=1)
    message: str


class NotifyOperator(BaseAction):
    uri: ClassVar[str] = "urn:demo:manufacturing:NotifyOperator"
    name: ClassVar[str] = "Notify operator"
    description: ClassVar[str] = "Send one-line message to an external notification channel."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.EXTERNAL_API, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True   # External call → operator click
    input_schema: ClassVar[type[BaseModel]] = _NotifyParams

    async def execute(self, params: _NotifyParams, state: CaseState) -> ActionResult:
        # Real HTTP call here (httpx)
        # For demo, simulate with a print
        return ActionResult(
            action_uri=self.uri,
            outputs={"channel": params.channel, "message": params.message},
            state_changes={"notified": True},
        )
```

Update `build_domain_actions()` in the same file:

```python
def build_domain_actions(store: GraphStore) -> tuple[BaseAction, ...]:
    return (
        PinpointSuspectLot(store),
        EvaluateIntervention(),
        RequestQuarantineApproval(),
        QuarantineLot(),
        CounterfactualReplay(),
        NotifyOperator(),          # ← add
    )
```

`flow/process.yaml`:

```yaml
allowed_actions:
  # ... existing ...
  - "urn:demo:manufacturing:NotifyOperator"   # ← add

constraints:
  requires:
    # ... existing ...
    "urn:demo:manufacturing:NotifyOperator":
      - "urn:demo:manufacturing:CounterfactualReplay"  # only after CF

# To automate via a rule:
rules:
  # ... existing ...
  - name: "RCA closed → notify operator"
    when:
      rca_complete: true
      notified: false
    then:
      action: "urn:demo:manufacturing:NotifyOperator"
      params:
        channel: "#ops-alerts"
        message: "RCA closed."
    confidence: 1.0
    rationale: "Operator should know whenever a case auto-closes."
```

### Don't forget

- [ ] `side_effects` is *accurate* — `EXTERNAL_API` causes the framework
      to auto-apply write-ahead audit (P7 hardening)
- [ ] Actions with `auto_execute_disabled = True` **won't fire from rules
      alone** — they need an explicit runner call or operator click
- [ ] Missing `constraints.requires` dependency breaks ordering — declare
      *what must precede this action*
- [ ] If `Params` is *dynamic* (sourced from case state), it can't be
      pinned in a rule's `params:` — needs explicit runner call (see
      Recipe D)
- [ ] Update the registration helper (`build_domain_actions`) — otherwise
      the action is not in the registry and the case can't find it

### Verification

```bash
uv run python scripts/05_run_flow.py 2>&1 | grep NotifyOperator
# the action should appear in the picks
```

A minimal test:

```python
@pytest.mark.unit
async def test_notify_operator_signals_state_change():
    action = NotifyOperator()
    result = await action.execute(
        action._NotifyParams(channel="#test", message="hi"),
        state=CaseState(properties={}),
    )
    assert result.state_changes["notified"] is True
```

---

## Recipe C — Modify a BN node or CPT value

### Goal

Two scenarios:

- **C1.** Change values only in an existing CPT (e.g., weaken
  AssemblyPressure's effect)
- **C2.** Add a brand-new node (e.g., add `ShiftOfDay` variable)

### Scenario C1 — value change only

#### Files

1. `src/ontorag_demo/causal/model.py` — the dict inside `_CPDS`

#### Change pattern

```python
_binary_cpd(
    "ProductDefect",
    ("ComponentQuality", "AssemblyPressure"),
    {
        ("good", "normal"): 0.99,   # 0.98 → 0.99 (more conservative on good case)
        ("good", "low"): 0.75,      # 0.65 → 0.75
        ("bad",  "normal"): 0.55,
        ("bad",  "low"): 0.20,
    },
),
```

#### Don't forget

- [ ] Only specify P(state0) per column — the helper fills 1−p for
      state1. **If you specify both, the helper takes only the first.**
- [ ] CPT column order is (last evidence varies fastest). The dict keys
      are *parent_assignment tuples* — order matters. Above, the
      evidence order is `("ComponentQuality", "AssemblyPressure")`, so
      the key tuples must be `(component_state, pressure_state)`.
- [ ] After the change you **must** regenerate data → reload → re-verify
      (Part 5 cycle)
- [ ] Test expected ranges (like `0.20 < p < 0.32` in
      `test_baseline_matches_expected_marginal`) may need updating too
- [ ] README's and walkthrough's *result-block numbers* will drift —
      manual update (see Part 2 matrix)

### Scenario C2 — add a new node

#### Files (in order)

1. `src/ontorag_demo/causal/model.py` — add a `NodeSpec` to `NODES`,
   add the corresponding CPD to `_CPDS`, and (if needed) re-declare
   `ProductDefect`'s parents and CPT
2. `src/ontorag_demo/generator/sampler.py` — sample the new node
3. `src/ontorag_demo/schema/manufacturing.ttl` — declare a new property
   (only if you want to persist it in the graph)
4. `src/ontorag_demo/generator/rdf_writer.py` — emit the new property
   triple
5. `tests/test_causal_model.py` — add invariants
6. README / walkthrough — update node-graph diagrams

#### Change pattern — `model.py` (e.g., `ShiftOfDay`)

```python
NODES: tuple[NodeSpec, ...] = (
    # ... existing 6 nodes ...
    NodeSpec("ShiftOfDay", ("day", "night")),
    NodeSpec(
        "ProductDefect",
        ("pass", "fail"),
        parents=("ComponentQuality", "AssemblyPressure", "ShiftOfDay"),  # ← add
    ),
)
```

CPT — 3 parents, so 8 columns:

```python
_binary_cpd(
    "ProductDefect",
    ("ComponentQuality", "AssemblyPressure", "ShiftOfDay"),
    {
        ("good", "normal", "day"):   0.98,
        ("good", "normal", "night"): 0.96,
        ("good", "low",    "day"):   0.65,
        ("good", "low",    "night"): 0.55,
        ("bad",  "normal", "day"):   0.50,
        ("bad",  "normal", "night"): 0.45,
        ("bad",  "low",    "day"):   0.15,
        ("bad",  "low",    "night"): 0.10,
    },
),
_binary_cpd("ShiftOfDay", (), {(): 0.60}),  # 60% day shift
```

#### Don't forget

- [ ] All entries in `NODES` and `_CPDS` are validated together (the
      pydantic validator catches mismatches, but its error messages
      aren't friendly)
- [ ] Adding a parent means **redefining every column of the existing
      CPT** — 4 columns becomes 8
- [ ] Sampler order must be topological — child nodes need their parents
      sampled first. `_sample_binary` takes a parent_assignment, so the
      sampling order in code matters.
- [ ] Also update `_attribute_failure()` so the new variable is
      reflected in ground-truth cause attribution
- [ ] If you added a TBox property, `02_load_ontorag.py` 's triple count
      will rise automatically (no manual touch)
- [ ] The DAG addition is automatic for `CausalEngine` (no separate
      code change)

#### Verification

```bash
uv run pytest -q                                # 11 → 11+ tests pass
uv run python scripts/01_generate_data.py       # new data
uv run python scripts/04_run_causal.py          # confirm P(fail) shifts
```

---

## Recipe D — Action with dynamic params that rules can't handle

### Goal
The new action's parameters need to be sourced from **specific case
state values**. RuleEngine has no templating → it can't be pinned in a
rule.

### Pattern (same one `QuarantineLot` uses)

In `flow/runner.py`, explicit call:

```python
async def run_flow(store, ...):
    # ... Phase 1 (RuleEngine auto) ...

    if case.status is CaseStatus.SUSPENDED:
        case = await manager.resume(case.case_uri)
        # extract the dynamic value from case state
        dynamic_value = case.state.properties.get("some_key")
        if not dynamic_value:
            raise RuntimeError("expected key missing from state")

        # explicit call
        case, _ = await manager.execute_action(
            case.case_uri,
            "urn:demo:manufacturing:YourAction",
            {"param": dynamic_value},
        )

        # Phase 4 (RuleEngine auto, drives to close)
        case = await _drive_until_terminal(manager, case.case_uri, console)
```

### Don't forget

- [ ] *Don't* create a parallel rule in process.yaml — the action would
      then execute twice and audit it twice
- [ ] Do leave a comment in process.yaml pointing to the runner ("the
      runner explicitly executes this after resume" — same pattern as
      the QuarantineLot block already there)
- [ ] Do register it in `constraints.requires` — the framework's
      ordering guardrail still applies

---

## Recipe E — Add a new process rule (static params only)

### Goal
A new action that the RuleEngine can fully drive based on booleans /
numbers in case state.

### Change pattern

`flow/process.yaml`:

```yaml
rules:
  # ... existing ...
  - name: "Symbolic name for the rule"
    when:
      some_state_key: true              # exact match
      another_key: { gte: 10 }          # comparison operators
      defect_rate_percent: { gt: 50 }
    then:
      action: "urn:demo:manufacturing:YourAction"
      params:
        static_param: "literal value"   # static values only
    confidence: 0.9
    rationale: "Why this rule fires."
```

Supported operators: `gt`, `gte`, `lt`, `lte`, `eq`, `neq`, `in`, `not_in`
(see `vendor/ontorag-flow/src/ontorag_flow/engines/rule.py` for the full
list).

### Don't forget

- [ ] **Rule evaluation order is not declaration order** — the
      RuleEngine proposes by descending confidence. Ties are broken by
      whether `constraints.requires` is satisfied.
- [ ] If a `when` key is **absent from case state**, the rule won't
      fire. Declare default values in `initial_state` first.
- [ ] When two rules for the same action trigger simultaneously, the
      higher confidence wins.
- [ ] Actions with `auto_execute_disabled = True` are *only proposed*
      by rules, never executed — operator click or explicit runner call
      is still required.

---

# Part 2 — Change-impact matrix

When you change one place, what updates automatically vs what needs a
manual update?

| Change location | Auto-updated | Manual update needed |
|---|---|---|
| **`_CPDS` probability values** | • sampler (imports the same object)<br>• BayesianEngine / CausalEngine<br>• new data from `01_generate_data.py`<br>• every number from scripts 02–05 | • README result blocks<br>• walkthrough result blocks<br>• `test_verify_causal.py` expected ranges<br>• re-run `02_load_ontorag.py` |
| **`NODES` — new node added** | • CPT validator (pydantic `model_validator`)<br>• CausalEngine recognises the DAG | • sampler call site<br>• `_attribute_failure()` cause categories<br>• schema TTL (if persisting)<br>• rdf_writer.py triple emit<br>• new tests |
| **`GeneratorConfig` — num_products / seed** | • data triple count<br>• ground truth counts<br>• every 03/04/05 result | • README / walkthrough numbers<br>• `test_contaminated_lot_dominates`'s `>= 5` threshold |
| **`SUPPLIER_PROFILES`** | • new data's supplier-level distribution | • ground truth's suspect_supplier_id<br>• 03's supplier table<br>• README/walkthrough supplier numbers |
| **`manufacturing.ttl` (schema)** | (on reload) Fuseki's TBox | • generator/rdf_writer.py (emit new property)<br>• verify/trace.py (use new property in queries)<br>• 02 schema triple count |
| **`process.yaml` — rule added** | • RuleEngine evaluation | • runner.py (if dynamic params)<br>• tests (action-execution checks)<br>• walkthrough Q11–14 |
| **New action (actions.py)** | • registry registration (if build_domain_actions is updated)<br>• executor's side_effect handling | • process.yaml (`allowed_actions`)<br>• constraints.requires<br>• rules (auto) or runner.py (explicit)<br>• tests |
| **`writeback.py` SPARQL UPDATE** | • call to Fuseki update endpoint | • If switching backends (Neo4j/FalkorDB), a separate implementation is needed |
| **`DEMO_ONTOLOGY` env var** | • named graph URI for loading<br>• writeback's WITH clause | • re-run 02 (previous graph is stale)<br>• 03 verification queries (different graph being loaded into) |
| **vendor/ontorag or vendor/ontorag-flow pull** | • editable install → code reflects immediately | • our call sites if API signatures changed<br>• `uv sync` if dependencies changed |

---

# Part 3 — Extension points

## A. Replace RuleEngine with LlmAgentEngine

### What changes
RuleEngine is declarative rule evaluation — static, deterministic,
predictable.
LlmAgentEngine is an LLM *reading the case state and action catalog
directly* to propose actions — dynamic, non-deterministic, adapts to
new situations.

### Code changes

`flow/process.yaml` — one line added:

```yaml
process_uri: "urn:demo:manufacturing:process:rca"
name: "Manufacturing high-defect-rate RCA"
engine: llm                                    # ← add (default is rule)
# ... rest unchanged ...
```

Environment:

```bash
export LLM_PROVIDER=anthropic
export LLM_MODEL=claude-sonnet-4-6
export ANTHROPIC_API_KEY=sk-ant-...
```

Run:

```bash
uv run python scripts/05_run_flow.py
```

### Guardrails that still hold

What the framework still blocks regardless of what the LLM does:

- **Unknown action_uri**: LlmAgentEngine's `_parse` filters URIs not in
  `allowed_actions`
- **Malformed JSON**: `_extract_json_array` tolerates code fences /
  prose preamble
- **Prerequisite violations**: `constraints.requires` is enforced by
  `CaseManager`, which raises `ConstraintViolationError`

### Demo caveats

- If the LLM doesn't know about a newly added action (you added it but
  the LLM wasn't trained on it), it won't propose it → make action
  descriptions rich
- Non-determinism breaks README/walkthrough reproducibility → use a
  deterministic fake mode (mimic the `run_demo_llm.py` pattern in
  vendor)

### Comparison variant
Run the same process.yaml through both engines and diff the audit:

```python
# rule engine
process_rule = load_process(PROCESS_YAML)

# llm engine
process_llm = process_rule.model_copy(update={"engine": "llm"})
```

---

## B. Switch ontorag calls to MCP transport

### Current vs after the switch

| Aspect | Current | After MCP switch |
|---|---|---|
| ontorag call site | Inside actions in `flow/actions.py` | Via ontorag_flow's `OntoragClient` |
| Transport | Python in-process | HTTP MCP |
| Process count | 1 (single driver) | 2 (ontorag MCP server + flow driver) |
| Upside | Simple, fast | Production-shape; many clients can share |
| Downside | flow and ontorag share a process | Two services to run + network latency |

### Where the code changes

1. **Start ontorag MCP server:**
   ```bash
   cd vendor/ontorag
   uv run ontorag serve --port 8000
   ```

2. **Change action constructors in `flow/actions.py`:**
   ```python
   # Current
   class PinpointSuspectLot(BaseAction):
       def __init__(self, store: GraphStore) -> None:
           self._store = store

   # After MCP switch
   from ontorag_flow.ontorag_client.client import OntoragClient
   from ontorag_flow.ontorag_client.tools import query_pattern  # or raw sparql

   class PinpointSuspectLot(BaseAction):
       def __init__(self, client: OntoragClient) -> None:
           self._client = client

       async def execute(self, ...):
           result = await query_pattern(self._client, sparql_or_pattern)
           # ...
   ```

3. **Change `build_domain_actions` parameter:**
   ```python
   def build_domain_actions(client: OntoragClient) -> tuple[BaseAction, ...]:
       return (
           PinpointSuspectLot(client),
           # ...
       )
   ```

4. **Change `writeback.py` to call `assert_triple` / `retract_triple` MCP
   tools instead of direct SPARQL UPDATE.**

### Don't forget

- [ ] The ontorag server must expose BN/Causal MCP tools
      (`compute_posterior`, `do_query`, `counterfactual` routes) —
      true since v0.7.3
- [ ] Decide whether `verify/causal.py` should also go through MCP —
      not strictly required but recommended for consistency
- [ ] Add env var `ONTORAG_MCP_URL=http://localhost:8000`

---

## C. Swap the graph backend (Neo4j / FalkorDB)

### Env-vars only

```bash
# Neo4j
export GRAPH_STORE=neo4j
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=...

# FalkorDB
export GRAPH_STORE=falkordb
export FALKORDB_HOST=localhost
export FALKORDB_PORT=6379
```

Extra ontorag dependency:

```bash
uv add 'ontorag[neo4j]'     # or [falkordb]
```

### Where code needs changing

- `create_store()` selects automatically by env var → no change needed
  from us
- `verify/trace.py`'s SPARQL — Neo4j / FalkorDB are Cypher-native.
  ontorag's `query_pattern` would auto-translate. But we use raw SPARQL,
  so **this part stops working** (`_sparql_select` on Neo4j/FalkorDB is
  either unimplemented or differently shaped)
- `flow/writeback.py` — **assumes Fuseki's `/update` endpoint**. For a
  different backend, you'd need to rewrite this as an MCP `assert_triple`
  call (Recipe B) or a backend-specific Cypher UPDATE

### Recommended migration order

1. Rewrite `verify/trace.py`'s SPARQL into `query_pattern` (L2 JSON DSL)
   — backend-agnostic
2. Rewrite `writeback.py` as an MCP `assert_triple` call (Recipe B)
3. Switch the backend env var

---

## D. Move to real data

### What changes most

- No ground truth → verification falls to a domain expert
- Much more noise → causal inference confidence drops
- Continuous sensor values → discretise preprocessor is mandatory

### Where the code changes

1. **Replace the entire `generator/` directory with ETL.** Read from
   external DB / files, populate the dataclasses in `entities.py`,
   reuse `rdf_writer.py`.
2. **Change `schema/manufacturing.ttl`'s `mfg:condition` to continuous
   (xsd:decimal)** + introduce a discretise function.
3. **Learn the BN CPTs from data** — use ontorag's `bayes/learn.py`
   (`ontorag bayes learn-cpt`).
4. **Learn the DAG from data** — use `ontorag.causal.discovery`'s PC
   algorithm (proposal-only).

### Demo value changes

Going real loses *reproducibility* (randomness + external systems).
That means you can't embed results into README/walkthrough → store
them as separate *example traces* instead.

---

# Part 4 — Troubleshooting

## "Fuseki connection refused"

```
httpx.ConnectError: All connection attempts failed
```

Checklist:

1. `lsof -nP -iTCP:3030 -sTCP:LISTEN` — see who owns port 3030
2. `curl http://localhost:3030/$/ping` — confirm alive
3. Container in `vendor/ontorag/docker-compose.yml` — running?
4. Is `FUSEKI_URL` pointing somewhere else by accident?

## "403 Access denied : only localhost access allowed"

Cause: Fuseki's admin endpoints (`/$/datasets`, etc.) are
localhost-only by default. Going through Docker can make the forwarded
IP look non-local.

Workaround: the regular SPARQL endpoints (`/ontorag/sparql`,
`/ontorag/update`) work fine — call those instead.

## "FUSEKI_DATASET not found"

```
{"error": "Dataset 'ontorag' not found"}
```

Fix:

```bash
curl -X POST http://localhost:3030/$/datasets -d "dbName=ontorag&dbType=tdb2"
```

(or use ontorag's docker-compose which auto-creates it)

## "pgmpy FutureWarning"

```
FutureWarning: `pgmpy.estimators.StructureScore` is deprecated and will be removed in v1.3.0.
```

Cause: ontorag v1.0 uses pgmpy v1.2 — pgmpy v1.3 is deprecating
something. No impact. Ignore. Will auto-resolve when ontorag updates.

## "Changes to vendor/ontorag aren't reflected in our code"

In theory `[tool.uv.sources]` editable install should reflect
immediately, but **uv lock can cache**.

Fix:

```bash
uv sync --reinstall-package ontorag
uv sync --reinstall-package ontorag-flow
```

## "LOT-0047 doesn't appear in results"

Checklist:

1. Has `random_seed` been changed? (`causal/model.py::GeneratorConfig`)
2. Is `contaminated_lot_index` still 47?
3. Did you re-run `01_generate_data.py` *with the latest config*?
4. Did you re-run `02_load_ontorag.py` too? Previous data may still be
   in Fuseki
5. If `DEMO_ONTOLOGY` was changed, you may be querying a different
   named graph

## "Tests pass but README numbers are different"

Cause: someone tweaked a CPT, or num_products. The tests check
*ranges*, so they still pass — but the README's *exact values* need
updating.

Fix: follow Part 5's step 7 (sync README numbers).

## "Previous quarantine results bleed into the next run"

Cause: write-back persists to Fuseki. The next run sees the triple
still present.

Fix:

```bash
# Drop just the manufacturing-demo data graph in Fuseki
curl -X DELETE "http://localhost:3030/ontorag/data?graph=urn:ontorag:manufacturing-demo:data"
# Then reload
uv run python scripts/02_load_ontorag.py
```

Or, more simply, use a different `--ontology` scope:

```bash
uv run python scripts/02_load_ontorag.py --ontology manufacturing-demo-2
```

---

# Part 5 — Standard dev cycle

The *ordered* workflow after any code change.

```
   Clarify intent
        ↓
   Pick a recipe (A–E)
        ↓
   Modify code
        ↓
   uv run pytest -q                 ← invariant regressions surface immediately
        ↓
   (if data changed)
   uv run python scripts/01_generate_data.py
        ↓
   (if loading changed)
   uv run python scripts/02_load_ontorag.py
        ↓
   uv run python scripts/03_run_trace.py
   uv run python scripts/04_run_causal.py
   uv run python scripts/05_run_flow.py
        ↓
   Sync README/walkthrough numbers (per change-impact matrix)
        ↓
   git commit
```

## Per-step checklist

### 1. Clarify intent

- [ ] What abstraction level is the change? (data / BN / schema / flow)
- [ ] Pre-identify *what needs manual updating* via the change-impact
      matrix (Part 2)
- [ ] Which recipe (A–E) does this match?

### 2. Modify code

- [ ] Keep frozen-dataclass / immutability patterns
- [ ] Honour single-source-of-truth (CLAUDE.md) — don't put the same
      information in two places

### 3. `uv run pytest -q`

- [ ] Does "11 passed" still hold?
- [ ] If a test broke, is it an *intended change* or *unintended
      regression*?
- [ ] If intended, update the test in the same commit

### 4. Regenerate data / reload

If the data itself changed, **always** 01 → 02:

- [ ] Regenerate `data/generated/manufacturing-instances.ttl`
- [ ] Regenerate `data/generated/ground_truth.json`
- [ ] Make sure 02 is idempotent — Fuseki shouldn't accumulate stale
      data (named-graph isolation handles this)

### 5. Verification scripts

- [ ] Does 03's SPARQL count still match ground truth?
- [ ] Did 04's P(fail) shift as expected?
- [ ] Does 05's 5-action lifecycle still reach `closed`?

### 6. Sync README/walkthrough numbers

The change-impact matrix's "manual update needed" column is your map.
Update both (Korean/English) at once — result blocks should be
identical bytes.

- [ ] README.{ko,}.md's "Real output" blocks
- [ ] walkthrough.{ko,}.md's per-Q result blocks
- [ ] implementation.{ko,}.md's validation/effect blocks (anywhere a
      probability is quoted)

### 7. git commit

- [ ] One commit = one conceptual change (~one recipe per commit)
- [ ] Follow CLAUDE.md's commit-message guidelines — type prefix
      (feat / fix / refactor / docs / test / chore)

---

With these five parts you can safely operate on top of the demo. When
you do get stuck — the best debugger is **deterministic re-runs**.
Same seed, same command, reproducible — so *where things start to
diverge* shows up immediately.
