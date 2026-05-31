# 구현 노트 — 문제풀이 과정과 코드 적용

> **🇺🇸 English:** [implementation.md](./implementation.md)
> **연관 문서:** [walkthrough.ko.md](./walkthrough.ko.md) (답 도출 과정) · [dev_guide.ko.md](./dev_guide.ko.md) (이 위에서 작업하기) · [README.ko.md](../README.ko.md) (실행 매뉴얼)

이 문서는 `walkthrough.ko.md` 한 단계 위의 메타입니다.
walkthrough가 *"답에 어떻게 도달하는가"* 였다면, 여기는
**"왜 이 코드 모양이 되었는가"** — 추상적 추론 5단계를 실제 Python /
Turtle / YAML 코드로 풀어내면서 마주친 문제, 가능한 옵션,
채택한 해법, 그리고 그 결정이 *실제로 어느 줄 어느 함수* 가 되었는가.

12개 결정으로 구성합니다. 각 결정은 같은 5-블록 구조:

| 블록 | 의미 |
|---|---|
| **문제** | 무엇이 막혔는가, 왜 그게 어려운가 |
| **옵션** | 진지하게 검토한 대안들 (보통 2~4개) |
| **선택 + 이유** | 어떤 옵션을 골랐는가, 트레이드오프는 무엇인가 |
| **코드 적용** | 그 결정이 실제로 어느 파일/함수의 몇 줄로 박혔는가 |
| **검증/효과** | 그 결정이 잘 작동했다는 *증거* 는 무엇인가 |

---

## 들어가며 — 12개 결정을 관통하는 4개 원칙

코드를 짜기 전에 정해둔 작업 원칙들. 모든 결정이 이 4개 중 하나로
환원됩니다:

1. **단일 source of truth.** BN의 CPT가 데이터 생성과 추론 양쪽에서
   *같은 객체* 여야 한다. 둘이 갈라지면 데모가 자기 자신을 속이게 됨.
2. **결정론적.** `random_seed=20260601` 고정. 두 번 돌리면 byte 단위로
   같은 출력. README/walkthrough에 결과를 *박을 수 있는* 전제.
3. **ground truth 와 비교 가능.** 생성기는 답을 알고 있다. 그 답을
   별도 JSON으로 남겨, Stage 4 검증이 ontorag의 응답을 정답과
   바이트 단위로 대조할 수 있게.
4. **premature abstraction 금지.** 데모는 한 시나리오. "나중에 다른
   도메인에서 재사용" 같은 상상 요구는 받지 않는다. 코드는 최소,
   직접적, *지금 필요한 것만*.

---

## 결정 1 — 합성 데이터에 "노이즈" 를 얼마나 줄 것인가

### 문제

플랜 §3 의 가장 핵심 함정: "공급사 B 가 무조건 100% 불량이고 그 외는
0% 불량" 같이 자명한 데이터로 시작하면, ontorag 가 정답을 맞춰도
*그건 시스템이 똑똑해서가 아니라 데이터가 빤한 것*. 데모의 가치가
0이 됨.

### 옵션

- **A. 완전 무작위.** P(bad) 를 모든 공급사에서 같게. → 공급사 신호가
  사라져 traceability 의 가치가 없음.
- **B. 부분 노이즈.** SUP-B 만 base rate 보다 *살짝* 높게. → 의도와
  맞지만 lot 단위 anomaly 가 안 보임.
- **C. 2-층 노이즈.** SUP-B 의 P(bad) 를 ~4배 + 특정 lot 만
  추가 오염. → 플랜 §3 그대로.

### 선택 + 이유

**C 채택.** 두 anomaly 가 *다른 추상화 레벨* (공급사 vs lot) 에서
일어나야, L1 traceability 와 L3 do_query 가 *서로 다른 사실* 을
드러낼 수 있음. SUP-B 가 모든 lot 에서 동일하게 나쁘면 lot-level
드릴다운이 의미 없어짐.

### 코드 적용

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
    contaminated_bad_rate: float = 1.0      # lot #47 은 *확정* 오염
```

그리고 `generator/sampler.py` 에서 두 anomaly 를 lot 단위에 적용:

```python
supplier_quality = "bad" if rng.random() < profile.bad_quality_rate else "good"
is_contaminated = i == config.contaminated_lot_index
if is_contaminated:
    lot_quality = "bad" if rng.random() < config.contaminated_bad_rate else "good"
else:
    lot_quality = _sample_binary(rng, "LotQuality", (supplier_quality,))
```

### 검증/효과

첫 실행 (`num_products=300`, `contaminated_bad_rate=0.95`) 결과 :
LOT-0047 이 *1건* 만 떠서 시그널이 너무 약함. 이건 *데모의 메시지가
약해진다는 의미* 라 즉시 두 가지 조정:

- `num_products: 300 → 600` (lot 당 12개로 → expected failures 5+ 확보)
- `contaminated_bad_rate: 0.95 → 1.0` (불확정성 제거)

재실행 결과: LOT-0047 이 10건으로 #1 - 데모가 의도한 그림 완성.
이 조정 과정 자체가 `tests/test_generator.py::test_contaminated_lot_dominates`
에 lock-in 됨 (`assert top_count >= 5`).

---

## 결정 2 — 스키마에서 공정 조건을 *연속* vs *이산*

### 문제

실세계 공정은 연속 센서값 (온도 23.4°C, 압력 0.87 bar). pgmpy 는
*이산 변수만* 다룸. 둘을 잇는 길은?

### 옵션

- **A. 연속값 저장 + 추론 시 binning.** TBox 에 xsd:decimal, Stage 4
  추론 직전에 `discretize()` 호출. → 두 가지 모델 (연속 / 이산)
  관리 필요, 코드 복잡.
- **B. 처음부터 이산 저장.** TBox 의 `mfg:condition` 을 string
  ("normal"/"low"/"high"). pgmpy 가 바로 소비. → 합성 데이터니까
  실제 센서값 없어도 됨.

### 선택 + 이유

**B 채택.** 플랜 §2 의 명시적 결정: "합성이라 처음부터 이산으로 설계
가능 → discretize 전처리 불필요". 만약 실데이터였다면 binning 단계가
별도로 필요했을 지점인데, 합성의 장점을 최대로 이용.

### 코드 적용

`src/ontorag_demo/schema/manufacturing.ttl`:

```turtle
mfg:condition a owl:DatatypeProperty ;
    rdfs:label "condition" ;
    rdfs:domain mfg:ProcessRun ;
    rdfs:range  xsd:string ;
    rdfs:comment "Discrete state of the process condition recorded by this run (e.g., 'normal' / 'high' / 'low')." .
```

그리고 BN 노드 정의에서 이산 상태를 그대로 선언:

```python
NodeSpec("AssemblyPressure", ("normal", "low")),
NodeSpec("MachiningTemperature", ("normal", "high")),
NodeSpec("InspectionMoisture", ("normal", "high")),
```

### 검증/효과

`02_load_ontorag.py` 가 schema (109 triples) 와 ABox (14010 triples)
를 한 번에 적재해도 변환 단계 0개. `04_run_causal.py` 가 별도
discretization 없이 BN 을 바로 추론. 코드 라인 수 절감 약 100줄
(binning 로직 제거).

---

## 결정 3 — CPT 를 손으로 쓰지 말기

### 문제

pgmpy 의 CPT 는 2D 배열, "마지막 evidence 가 가장 빨리 변함" 컨벤션.
ProductDefect 처럼 두 부모를 가진 노드라면 4개 column 의 순서를 정확히
지켜야 함. 손으로 쓰면 column index 헷갈려서 데이터-모델 정합성이
미세하게 깨질 수 있음 (그리고 발견이 어려움).

### 옵션

- **A. 손으로 list-of-list 작성.** ontorag 의 smoking 예제 방식.
  → 4 column 까지는 그럭저럭, 그 이상은 hellish.
- **B. dict (parent_assignment → P(state0)) → helper 가 변환.** 사람이
  보기에 자연스러운 표현 + 컨벤션은 helper 가 캡슐화.

### 선택 + 이유

**B 채택.** 데이터를 *보면 그대로* 읽혀야 함. 컬럼 순서 같은 mechanical
detail 은 helper 가 책임. 그리고 helper 는 모든 CPD 가 binary 라는
조건을 강제 — `assert len(spec.states) == 2`.

### 코드 적용

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

이걸로 ProductDefect CPT 가 이렇게 정의됨:

```python
_binary_cpd("ProductDefect", ("ComponentQuality", "AssemblyPressure"), {
    ("good", "normal"): 0.98,
    ("good", "low"): 0.65,
    ("bad", "normal"): 0.50,
    ("bad", "low"): 0.15,
}),
```

사람이 한 줄씩 읽으면 그게 *바로* 의미. column index 0 ~ 3 따위는
helper 안에만 존재.

### 검증/효과

`tests/test_causal_model.py::test_cpd_rows_sum_to_one` 이 모든 CPT 의
column 합 = 1.0 을 보장 — `1.0 - p` 자동 계산이 floating-point 오차
없이 작동. 11/11 테스트 통과.

---

## 결정 4 — 데이터 생성기를 pgmpy.forward_sample 로 *안* 한 이유

### 문제

pgmpy 에는 BN 에서 샘플을 뽑는 `BayesianModelSampling.forward_sample()`
이 있음. 그걸 쓰면 코드가 3줄로 끝남. 그런데 우리는 다음 두 가지가
필요:

1. **per-entity anomaly injection** (SUP-B 의 P(bad)=0.55, lot #47 강제
   오염) — 이건 BN 의 marginal CPT 로는 표현 불가능.
2. **latent state 추적** — 각 제품의 실제 supplier_quality / lot_quality /
   component_quality 를 ground_truth.json 에 보존해야 검증 가능.
   pgmpy 의 forward_sample 은 query 한 변수만 돌려줌.

### 옵션

- **A. forward_sample + 사후 patch.** 일단 뽑고 supplier 별 라벨을
  patch. → 두 단계 일관성 깨짐.
- **B. 직접 sampler 작성, BN의 CPT 만 빌려옴.** sampling 로직은 우리가
  쓰지만 확률값은 BN 의 `_CPDS` 에서 직접 lookup. → 데이터-모델
  정합성 유지 + 우리가 필요한 control 확보.

### 선택 + 이유

**B 채택.** pgmpy 의 sampler 가 제공하는 "최적화된 forward sampling"
은 600개 product 데모 규모에서 의미 없음. 그 대신 *우리가 통제하는
sampling 으로 anomaly 와 latent state 를 모두 얻음*.

### 코드 적용

`src/ontorag_demo/generator/sampler.py`:

```python
from ontorag_demo.causal.model import _CPDS  # 같은 객체!

def _conditional_prob(node_name: str, state: str, parent_assignment: tuple[str, ...]) -> float:
    cpd = _cpd_for(node_name)
    # ... pgmpy column ordering 그대로 적용
    return cpd.values[row][col]

def _sample_binary(rng, node_name: str, parent_assignment: tuple[str, ...]) -> str:
    states = NODES_BY_NAME[node_name].states
    p_first = _conditional_prob(node_name, states[0], parent_assignment)
    return states[0] if rng.random() < p_first else states[1]
```

핵심 줄: `from ontorag_demo.causal.model import _CPDS` — sampler 가
사용하는 CPT 가 BN 으로 적재되는 CPT 와 *물리적으로 같은 객체*.
누가 _CPDS 를 변경하면 sampler 와 추론이 동시에 그 변경을 반영.
정합성 깨짐 *불가능*.

### 검증/효과

`tests/test_verify_causal.py::test_baseline_matches_expected_marginal`
이 `P(fail) baseline` 이 0.20~0.32 안에 있어야 한다고 강제. 실제로
0.265 (BN 추론) ≈ 0.252 (sampled 데이터의 실측 비율). 두 숫자가
가까운 것 자체가 정합성 증거.

---

## 결정 5 — async/sync 경계를 어디에 둘 것인가

### 문제

ontorag 의 store API 는 *모두 async* (`load_rdf`, `_sparql_select`,
`put_bayes_network` ...). 데이터 생성 (`generator/run.py`) 은 CPU-bound
sampling 이라 sync 가 자연스러움. 어떻게 섞는가?

### 옵션

- **A. 전체 async.** sampler 도 `async def`. → 이득 없음 (I/O 0), 테스트
  복잡 (모든 fixture 에 asyncio_mode).
- **B. sampler 는 sync, scripts/02-05 만 async.** 경계가 명확.

### 선택 + 이유

**B 채택.** async 는 I/O 대기가 있을 때만 의미. sampling 은 순수
연산이므로 sync. scripts 는 ontorag 호출하므로 async. 두 영역 사이의
경계는 `scripts/02_load_ontorag.py` 같은 entry point 에서 `asyncio.run()`
로 명시.

### 코드 적용

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

### 검증/효과

테스트 코드 (`test_generator.py`) 가 fixture 에 `@pytest.fixture` 만
쓰고 `@pytest.fixture(scope="...")` 같은 async 복잡도 없이 깔끔.
`asyncio_mode = "auto"` 는 pyproject 에 있지만 sampler 테스트는
sync 라 영향 없음.

---

## 결정 6 — Stage 4 traceability 에 *raw SPARQL* 을 노출한 이유

### 문제

ontorag 는 같은 traceability 질문에 *3가지 인터페이스* 를 제공:

- **L1** : `find_entities` + `traverse_graph` (의도 기반 고수준 툴)
- **L2** : `query_pattern` (JSON DSL → SPARQL 자동 변환)
- **L3 dev** : `_sparql_select` (raw SPARQL)

어느 걸 데모에 쓸 것인가?

### 옵션

- **A. L1.** 가장 안전, MCP 노출용. → 다중홉 + GROUP BY + COUNT 는
  L1 helper 로 깔끔히 안 됨.
- **B. L2 (query_pattern).** JSON 으로 triple pattern 작성. →
  COUNT/GROUP BY 가 1급 시민이 아니라서 표현이 어색.
- **C. raw SPARQL.** `_sparql_select` 직접 호출. → 풀 SPARQL 1.1
  표현력.

### 선택 + 이유

**C 채택.** 데모의 *교훈* 중 하나가 *"잘 설계된 스키마는 5홉 SPARQL
JOIN 으로 traceability 가 깔끔히 풀린다"*. 그 교훈을 보여주려면
SPARQL 이 그대로 보여야 함. L1/L2 로 추상화하면 그 메시지가 가려짐.
또한 데모 코드를 처음 읽는 사람이 *"이게 정말 5홉 join 인가?"* 라고
물을 때 정답을 즉시 보여줄 수 있음.

### 코드 적용

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

추가로 `_iter_rows()` helper 가 SPARQL JSON results format
(`{"head": ..., "results": {"bindings": [{var: {value}}]}}`) 을 plain
`[{var: value}]` 로 정규화 — 각 query 함수가 두 줄로 결과 처리 가능.

### 검증/효과

walkthrough.ko.md 의 Q1~Q4 가 *SPARQL 그대로* 인용 가능. 만약 L2 로
숨겼으면 그 부분이 "JSON pattern" 으로 변해서 독자가 머리로 SPARQL
을 복원해야 함.

---

## 결정 7 — L2/L3 검증을 Fuseki *없이* 도는 것

### 문제

`compute_posterior` 와 `do_query` 는 ontorag 의 메서드. 두 개의 적용
경로가 있음:

- **A. Fuseki 경유.** `put_bayes_network(BN)` 으로 적재 → `get_bayes_network()`
  로 복구 → `BayesianEngine(bn)` 으로 추론.
- **B. in-memory 직접.** `BayesianEngine(MANUFACTURING_BN)` 바로 호출.

A 는 *full stack* 을 거치지만 Fuseki 가 켜져 있어야 함. B 는 빠르고
독립적이지만 ontorag 의 Turtle 직렬화 / round-trip 검증을 skip.

### 옵션

분리하면 둘 다 가능. 핵심은 데모의 *각 스크립트가 무엇을 요구하는가*.

### 선택 + 이유

**둘 다 사용.** 책임을 분리:

- `02_load_ontorag.py` 가 `put_bayes_network(MANUFACTURING_BN)` 호출 →
  ontorag 의 정상 적재 경로 검증 (= A 경로).
- `04_run_causal.py` 가 `BayesianEngine(MANUFACTURING_BN)` 직접 사용
  → CI / 로컬 검증이 Fuseki 없이 돌 수 있음 (= B 경로).

같은 BN 객체 (`MANUFACTURING_BN`) 가 양쪽에 흘러가므로 두 경로의
정합성은 자동.

### 코드 적용

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

### 검증/효과

`tests/test_verify_causal.py` 가 Fuseki 없이 11개 테스트 다 통과
(`uv run pytest` 가 Fuseki 의존성 0). 동시에 적재 경로도 production-
대비 (다른 ontorag 클라이언트가 *공유 추론 모델* 을 발견할 수 있음).

---

## 결정 8 — Flow action 을 *5개* 로 쪼갠 이유

### 문제

RCA 워크플로 전체를 "do everything" 한 함수 한 방으로 끝낼 수도
있음. 왜 5개 action 으로 쪼갰는가?

### 옵션

- **A. 한 mono-action.** `RunFullRCA()` 가 traceability + causal +
  write-back + replay 다 함. → side effect 분류 불가능, 인간 승인 못
  넣음, 부분 실패 복구 불가.
- **B. 액션마다 단일 책임.** 각각 side_effect 명시. → ontorag-flow 의
  framework 가 자동으로 휴면/승인/감사 처리.

### 선택 + 이유

**B 채택.** ontorag-flow 의 핵심 가치 (HUMAN side effect → auto suspend,
ABOX_WRITE → auto_execute_disabled, PROV-O 단위 = action) 가
*action 단위 책임 분할* 위에 빌드되어 있음. mono-action 은 framework
혜택 0.

### 코드 적용

`src/ontorag_demo/flow/actions.py` — 5개 action class, 각각 약 30~50줄:

| Action | side_effects | auto_disabled | 의미 |
|---|---|---|---|
| `PinpointSuspectLot` | `{CASE_STATE}` | False | L1 SPARQL → state 업데이트만 |
| `EvaluateIntervention` | `{CASE_STATE}` | False | L3 do_query → state 업데이트만 |
| `RequestQuarantineApproval` | `{HUMAN, CASE_STATE}` | True | 자동 suspend |
| `QuarantineLot` | `{ABOX_WRITE, CASE_STATE}` | True | 운영자 클릭 필수 |
| `CounterfactualReplay` | `{CASE_STATE}` | False | L3 Rung 3 → state |

side_effect 가 *선언된 그대로* framework 가 처리:

```python
class RequestQuarantineApproval(BaseAction):
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.HUMAN, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True
```

이 두 줄만으로 CaseManager 가 *알아서* `OPEN → SUSPENDED` 전이.

### 검증/효과

`05_run_flow.py` 의 출력에서 "Phase 1 → suspended → Phase 2 (resume)
→ Phase 3 (explicit quarantine)" 의 4-phase 가 *자연스럽게* 발생.
runner 코드에는 "if action == ... then suspend" 같은 conditional 0줄.

---

## 결정 9 — RuleEngine 자동화 범위를 어디까지

### 문제

`process.yaml` 의 rule 들이 너무 적으면 워크플로 가치 X. 너무 많으면
운영자 결정 지점이 사라짐. 균형점은?

### 옵션

- **A. 5개 action 모두 rule 화.** quarantine 도 rule 로. → `lot_uri`
  파라미터를 어디서 가져오나? RuleEngine 은 템플릿 미지원.
- **B. 4개만 rule, quarantine 은 runner 에서 명시 호출.** → 한 곳에
  특수 케이스 (resume 후 명시적 호출) 가 있지만 명확.
- **C. 모두 명시 호출, rule 미사용.** → RuleEngine 데모 가치 0.

### 선택 + 이유

**B 채택.** 자동화 가능한 부분은 rule (PinpointSuspectLot,
EvaluateIntervention, RequestQuarantineApproval, CounterfactualReplay),
*동적 파라미터가 필요한 부분만* runner 명시 호출 (QuarantineLot 에
suspect_lot_id 주입). supply_chain_rca 예제의 "wrap-up after resume"
패턴 차용.

### 코드 적용

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

### 검증/효과

`05_run_flow.py` 출력 : Phase 1 에서 RuleEngine 이 3개 picks 자동
실행 (`#1 PinpointSuspectLot ... #2 EvaluateIntervention ... #3
RequestQuarantineApproval ...`), Phase 3 에서 QuarantineLot 만
명시 호출. process.yaml 의 주석이 *이유* 를 미래의 reader 에게 박아둠.

---

## 결정 10 — write-back 을 `_gsp_post` 가 아닌 *직접 SPARQL UPDATE*

### 문제

`mfg:quarantined = true` 한 triple 만 추가하면 됨. ontorag 가 제공하는
write 경로:

- `load_rdf(path, mode="data")` — 전체 ABox 교체
- `_gsp_post(graph, named_graph)` — GSP 로 named graph 에 append (private)
- (없음) SPARQL UPDATE 노출

### 옵션

- **A. `load_rdf` 로 단일-triple Turtle 적재.** → 전체 graph 다시 직렬화
  (낭비), append 가 아니라 replace 위험.
- **B. `_gsp_post` 호출.** → private API (`_` 접두), ontorag 가 향후 메서드
  변경 시 깨짐.
- **C. 직접 httpx 로 Fuseki `/update` 엔드포인트 POST.** → 표준 SPARQL
  1.1 UPDATE, ontorag 내부 메서드 미사용.

### 선택 + 이유

**C 채택.** SPARQL UPDATE 는 *표준* 이라 ontorag 가 어떻게 변하든 안전.
또한 DELETE+INSERT 한 묶음으로 *기존 값을 안전하게 교체* 가능 — 같은
lot 을 두 번 격리해도 멱등.

### 코드 적용

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

핵심 디테일:
- `WITH <graph_uri>` 로 named graph 명시 (manufacturing-demo 격리)
- `BIND(<lot_uri> AS ?lot)` 로 typo 시 silent 실패 방지 (URI 가 없으면
  DELETE 가 0 row 영향이지만 INSERT 도 0 row → 외부 SPARQL SELECT 로
  확인 가능)
- `return update` 로 PROV-O activity 에 *실제 보낸 SPARQL* 보존

### 검증/효과

`curl ... /ontorag/sparql ... SELECT ?lotId WHERE { ... ?lot
mfg:quarantined true . }` 가 `LOT-0047` 반환 → triple 이 실제로 적재됨.
PROV-O 활동 `QuarantineLot` 의 outputs 에 `sparql_update` 가 박혀서
나중에 누가 봐도 "정확히 어떤 SPARQL 이 보내졌나" 알 수 있음.

---

## 결정 11 — Runner 의 4-phase 구조

### 문제

`CaseManager.propose_next()` 는 "다음 후보 action 들" 을 돌려줌.
`execute_action()` 은 하나를 실행. 두 개로 *자동 루프* 를 어떻게 짤
것인가? 그리고 HUMAN suspend 와 어떻게 어울리게?

### 옵션

- **A. 한 `while OPEN: propose+execute` 루프.** → suspend 후 resume 사이
  에 명시적 quarantine 호출을 어떻게 끼우나?
- **B. Phase 별로 명시 분할.** Phase 1 (loop), Phase 2 (resume), Phase 3
  (explicit), Phase 4 (loop).

### 선택 + 이유

**B 채택.** supply_chain_rca 예제 (vendor/ontorag-flow) 의 패턴 그대로.
명시적 phase 가 *읽기 쉬움* — `05_run_flow.py` 출력만 봐도 어디서
무엇이 일어나는지 즉시 이해 가능. 헬퍼 함수 `_drive_until_terminal()`
이 propose+execute 루프를 캡슐화.

### 코드 적용

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

### 검증/효과

`05_run_flow.py` 출력의 phase 헤더 (`Phase 1 — automatic`,
`Phase 2 — human approval gate`, ...) 가 코드 구조와 1:1 대응.
debug 할 때 "Phase 3 에서 멈췄다" 라는 말이 정확히 어느 코드 줄을
가리키는지 즉시 알 수 있음.

---

## 결정 12 — 테스트가 검증할 것은 *코드가 아니라 주장*

### 문제

11개 테스트로 무엇을 검증할 것인가? 라인 커버리지 100% 를 노릴 수도
있고, 코드의 *주장* 만 lock-in 할 수도 있음.

### 옵션

- **A. 라인 커버리지 위주.** 모든 helper, edge case 다 cover.
- **B. 코드의 *논리적 주장* 만 cover.** 즉 "이 데모가 보여주려는 것"
  자체를 테스트.

### 선택 + 이유

**B 채택.** 데모는 *production code 가 아님*. 라인 커버리지는
maintainability 신호일 뿐 정답은 아님. 대신 데모의 *교훈* 이
무너지면 테스트가 즉시 fail 하도록 — 즉 회귀가 *의미론적 회귀* 일 때만
경보.

### 코드 적용

3개 테스트 파일, 각각 *주장 한 그룹*:

`tests/test_causal_model.py` — **모델 구조 주장**:

```python
def test_cpd_rows_sum_to_one():
    """확률은 1.0이 되어야 한다 — pgmpy가 거부할 invariant."""
    for cpd in MANUFACTURING_BN.cpds:
        for col in range(len(cpd.values[0])):
            total = sum(row[col] for row in cpd.values)
            assert total == pytest.approx(1.0, abs=1e-6)

def test_product_defect_cpt_interaction():
    """(bad, low) joint가 최대 P(fail)을 줘야 한다 — 의미론 invariant."""
    # ... assert p_fail[3] > p_fail[2] > p_fail[1] > p_fail[0]
```

`tests/test_generator.py` — **데이터 생성 주장**:

```python
def test_deterministic_with_fixed_seed(tmp_path):
    """같은 seed 두 번 → 같은 결과 (README/walkthrough의 숫자 재현 가능성)."""
    first = generate(..., output_dir=tmp_path / "a")
    second = generate(..., output_dir=tmp_path / "b")
    assert first.ground_truth == second.ground_truth

def test_contaminated_lot_dominates(generated):
    """오염된 lot이 #1 — 신호가 약해지면 즉시 fail."""
    top_lot, top_count = sorted(...)[0]
    assert top_lot == gt.contaminated_lot_id
    assert top_count >= 5
```

`tests/test_verify_causal.py` — **데모의 핵심 메시지 주장**:

```python
async def test_assembly_intervention_helps_more_than_supplier_only():
    """플랜 §1의 narrative 주장 — 엔진 레벨에서 검증."""
    sup = await do_supplier_good()
    pres = await do_assembly_normal()
    assert pres.p_fail < sup.p_fail
```

만약 누군가 BN 의 CPT 를 잘못 건드려서 "공정 개입이 공급사보다 효과
크다" 가 더 이상 성립하지 않으면 이 테스트가 즉시 fail → README 의
narrative 가 코드와 어긋나는 일이 *구조적으로 막힘*.

### 검증/효과

`uv run pytest -q` → `11 passed, 1 warning in 5.01s`. 11개 모두
Fuseki 없이 도는 unit test. CI 에 적합.

---

## 회고 — 12개 결정의 공통 패턴

이 12 개 결정을 돌아보면 *세 가지 공통 패턴* 이 보입니다:

### 패턴 A — "단일 source of truth, 다중 사용처"

같은 객체가 여러 코드 경로에 흘러가도록 설계.

- BN 의 `_CPDS` 가 sampler (결정 4) 와 BayesianEngine (결정 7) 양쪽에 흘러감
- `MANUFACTURING_BN` 이 in-memory 추론 (결정 7) 과 Fuseki 적재 (결정 7) 양쪽에 흘러감
- `random_seed=20260601` 이 README, walkthrough, 테스트 모두에서 같은 숫자 보장

**효과**: 정합성 검증이 *자동* . 한 곳을 바꾸면 다른 곳에 즉시 반영.

### 패턴 B — "표준을 직접, 추상화는 minimum"

framework / library 가 제공하는 추상을 *고급* 일수록 신중히 채택.

- raw SPARQL `_sparql_select` (결정 6) > query_pattern
- 직접 SPARQL UPDATE (결정 10) > `_gsp_post`
- 직접 sampler (결정 4) > `pgmpy.BayesianModelSampling.forward_sample`

**효과**: 코드 reader 가 *프레임워크 매뉴얼 없이* 읽힘. SPARQL /
Python 만 알면 충분.

### 패턴 C — "framework 의 메커니즘에 *자연스럽게* 올라타기"

ontorag-flow 가 제공하는 framework 의 *주된 기능* 을 충실히 활용.

- side_effects 선언 → auto suspend / auto disable (결정 8)
- RuleEngine 의 4 rule + 4 requires → 자동 phase 진행 (결정 9)
- PROV-O activity = action 단위 → audit log 가 자동 정합 (결정 11)

**효과**: 코드 줄 수 절감 + framework 가 *의도된 가드레일* 을 자동
제공.

---

이 세 패턴은 **소프트웨어 아키텍처 일반 원칙** 이 아니라 *이 데모의*
구체 문제 (추론 5 단계를 코드로 풀기) 에 대한 *이번* 답입니다.
다른 도메인 (예: 합성 데이터가 아닌 실 데이터, 단일 시나리오가 아닌
다중 워크플로) 이라면 같은 결정들이 다르게 떨어질 가능성이 큽니다.

여기 기록한 *결정의 근거* 가 미래에 이 코드를 손볼 때 "왜 이렇게
짰지?" 라는 질문에 즉시 답을 주는 것이 이 문서의 목적입니다.
