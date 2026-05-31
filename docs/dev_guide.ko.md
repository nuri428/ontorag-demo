# Dev Guide — 이 데모 위에서 작업하기

> **🇺🇸 English:** [dev_guide.md](./dev_guide.md)
> **연관 문서:** [README.ko.md](../README.ko.md) · [walkthrough.ko.md](./walkthrough.ko.md) · [implementation.ko.md](./implementation.ko.md)

다른 3개 문서가 **descriptive** (서술 — 무엇이 있고, 어떻게 도출되고,
왜 이렇게 짰는가) 였다면, 이 문서는 **prescriptive** (지시 — "X 를
하려면 다음을 다음 순서로") 입니다.

5 개 영역:

| Part | 다루는 것 |
|---|---|
| 1. Change Recipes | 새 질문 / 액션 / 노드를 *어디에 어떤 순서로* 추가할 것인가 |
| 2. 변경 영향 매트릭스 | 한 곳을 바꾸면 어디까지 자동 / 어디는 수동 갱신 |
| 3. 확장 포인트 | LLM 엔진, MCP transport, 다른 graph backend 등 |
| 4. Troubleshooting | 실제 마주칠 만한 에러와 대응 |
| 5. 표준 개발 사이클 | 변경 → 테스트 → 데이터 → 검증 → 문서 동기화 |

---

# Part 1 — Change Recipes

각 recipe 는 동일한 5-블록:

1. **목표** — 한 줄로 무엇을 추가/변경하려는가
2. **수정 파일 (순서대로)** — 의존성 순서로 나열
3. **각 파일의 변경 패턴** — copy-paste 가능한 snippet
4. **잊지 말 것 체크리스트** — 자동 못 잡는 영역
5. **검증** — 변경이 의도대로 들었는지 어떻게 확인

---

## Recipe A — 새 SPARQL traceability 질문 추가

### 목표
예: "특정 supplier 의 lot 중 어떤 것이 가장 많은 component 를 생산했나?"

### 수정 파일 (순서대로)

1. `src/ontorag_demo/verify/trace.py` — 새 함수 추가
2. `scripts/03_run_trace.py` — 호출 + 출력 (선택)
3. `tests/test_*.py` — invariant 추가 (선택)
4. `docs/walkthrough.ko.md` (+ `.md`) — Q 번호 추가 (선택)

### 변경 패턴

`verify/trace.py` 에 함수 한 개 추가:

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

### 잊지 말 것

- [ ] `_PREFIXES` 상수를 이미 import 했는가 (같은 파일 안에 있음)
- [ ] SPARQL 인터폴레이션은 f-string 으로 — 단, **사용자 입력을 그대로
      넣지 말 것** (이 데모는 신뢰된 환경이라 OK, production 은 escape)
- [ ] return type 이 frozen dataclass — immutability 원칙 (CLAUDE.md)
- [ ] `_iter_rows()` 가 SPARQL JSON 결과를 plain dict 로 정규화 함

### 검증

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

## Recipe B — 새 도메인 액션 추가

### 목표
예: "case 가 닫히기 전에 자동으로 슬랙 알림 보내기" (= `NotifyOperator`).

### 수정 파일 (순서대로)

1. `src/ontorag_demo/flow/actions.py` — `BaseAction` 서브클래스 + 등록 helper 갱신
2. `src/ontorag_demo/flow/process.yaml` — `allowed_actions` + (선택) `constraints.requires` + (선택) `rules`
3. `src/ontorag_demo/flow/runner.py` — 동적 파라미터가 필요하면 명시 호출 추가
4. `tests/test_*.py` — 액션 단위 테스트 (선택)

### 변경 패턴

`flow/actions.py`:

```python
class _NotifyParams(BaseModel):
    channel: str = Field(min_length=1)
    message: str


class NotifyOperator(BaseAction):
    uri: ClassVar[str] = "urn:demo:manufacturing:NotifyOperator"
    name: ClassVar[str] = "Notify operator"
    description: ClassVar[str] = "외부 알림 채널에 한 줄 메시지 송신."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.EXTERNAL_API, SideEffectKind.CASE_STATE}
    )
    auto_execute_disabled: ClassVar[bool] = True   # 외부 호출 → 운영자 click
    input_schema: ClassVar[type[BaseModel]] = _NotifyParams

    async def execute(self, params: _NotifyParams, state: CaseState) -> ActionResult:
        # 실제 HTTP 호출은 여기서 (httpx)
        # 데모 목적이라면 print 로 시뮬레이션
        return ActionResult(
            action_uri=self.uri,
            outputs={"channel": params.channel, "message": params.message},
            state_changes={"notified": True},
        )
```

같은 파일의 `build_domain_actions()` 에 추가:

```python
def build_domain_actions(store: GraphStore) -> tuple[BaseAction, ...]:
    return (
        PinpointSuspectLot(store),
        EvaluateIntervention(),
        RequestQuarantineApproval(),
        QuarantineLot(),
        CounterfactualReplay(),
        NotifyOperator(),          # ← 추가
    )
```

`flow/process.yaml`:

```yaml
allowed_actions:
  # ... 기존 ...
  - "urn:demo:manufacturing:NotifyOperator"   # ← 추가

constraints:
  requires:
    # ... 기존 ...
    "urn:demo:manufacturing:NotifyOperator":
      - "urn:demo:manufacturing:CounterfactualReplay"  # CF 후에만 알림

# rule 로 자동화하려면:
rules:
  # ... 기존 ...
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

### 잊지 말 것

- [ ] `side_effects` 가 *정확한* 분류인가 — `EXTERNAL_API` 가 들어가면
      framework 가 audit 의 write-ahead 를 자동 적용 (P7 hardening)
- [ ] `auto_execute_disabled = True` 인 액션은 **rule 만으로는 못 실행됨** —
      runner 에서 명시 호출 또는 운영자 click 필요
- [ ] `constraints.requires` 에 dependency 빠뜨리면 순서가 깨짐 — 새
      액션이 *어느 액션 이후에야 의미 있는가* 명시
- [ ] `Params` 가 *동적* 이면 (예: case state 에서 가져온 값) rule 의
      `params:` 에 못 박을 수 없음 → runner 명시 호출 필요
      (Recipe D 참고)
- [ ] 등록 helper (`build_domain_actions`) 까지 갱신 — 안 하면 액션이
      registry 에 없어 case 가 못 찾음

### 검증

```bash
uv run python scripts/05_run_flow.py 2>&1 | grep NotifyOperator
# 출력에 액션이 한 줄 떠야 함
```

테스트 한 개:

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

## Recipe C — BN 노드 / CPT 값 수정

### 목표

두 가지 scenario:

- **C1.** 기존 CPT 의 확률값만 변경 (예: AssemblyPressure 효과 약화)
- **C2.** 노드를 새로 추가 (예: `ShiftOfDay` 변수 추가)

### Scenario C1 — CPT 값만 변경

#### 수정 파일

1. `src/ontorag_demo/causal/model.py` — `_CPDS` 의 해당 dict

#### 변경 패턴

```python
_binary_cpd(
    "ProductDefect",
    ("ComponentQuality", "AssemblyPressure"),
    {
        ("good", "normal"): 0.99,   # 0.98 → 0.99 (예: 정상 케이스 더 보수적)
        ("good", "low"): 0.75,      # 0.65 → 0.75
        ("bad",  "normal"): 0.55,
        ("bad",  "low"): 0.20,
    },
),
```

#### 잊지 말 것

- [ ] 한 column 의 P(state0) 만 명시 — 나머지는 helper 가 1-p 로 자동
      계산. **양쪽 다 쓰면 헬퍼가 무시함, 첫번째만 본다**
- [ ] CPT 의 column 순서는 (마지막 evidence varies fastest). dict 키는
      *parent_assignment 튜플* 이라 순서 중요. 위 예의 evidence 순서는
      `("ComponentQuality", "AssemblyPressure")` 이므로 키는
      `(component_state, pressure_state)` 튜플.
- [ ] 변경 후 **반드시** 데이터 재생성 → 적재 → 검증 (Part 5 사이클)
- [ ] 테스트의 expected 범위 (`test_baseline_matches_expected_marginal`
      의 0.20~0.32 같은 것) 도 같이 갱신해야 할 수 있음
- [ ] README 와 walkthrough 의 *결과 블록 숫자* 가 어긋남 → 수동 갱신
      (변경 영향 매트릭스, Part 2 참고)

### Scenario C2 — 새 노드 추가

#### 수정 파일 (순서대로)

1. `src/ontorag_demo/causal/model.py` — `NODES` tuple 에 `NodeSpec` +
   `_CPDS` 에 해당 CPD + (필요 시) `ProductDefect` 의 parents/CPT 도 갱신
2. `src/ontorag_demo/generator/sampler.py` — 새 노드 sampling 호출
3. `src/ontorag_demo/schema/manufacturing.ttl` — 새 property 선언
   (graph 에 저장하려는 경우)
4. `src/ontorag_demo/generator/rdf_writer.py` — 새 property 트리플 추가
5. `tests/test_causal_model.py` — invariant 추가
6. README / walkthrough — 노드 그래프 다이어그램 갱신

#### 변경 패턴 — `model.py` (예: `ShiftOfDay`)

```python
NODES: tuple[NodeSpec, ...] = (
    # ... 기존 6 노드 ...
    NodeSpec("ShiftOfDay", ("day", "night")),
    NodeSpec(
        "ProductDefect",
        ("pass", "fail"),
        parents=("ComponentQuality", "AssemblyPressure", "ShiftOfDay"),  # ← 추가
    ),
)
```

CPT — 부모가 3개라 8 column:

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
_binary_cpd("ShiftOfDay", (), {(): 0.60}),  # 60% 주간
```

#### 잊지 말 것

- [ ] `NODES` 와 `_CPDS` 의 *모든* CPD 가 매칭 (validator 가 잡아주지만
      에러 메시지가 깔끔하진 않음)
- [ ] 부모 추가 시 *기존 CPT 의 모든 column 을 재정의* 해야 — 4 column
      이 8 column 으로 늘어남
- [ ] sampler 의 sampling 순서 — 자식 노드는 부모가 먼저 sampling 된
      후에 sample 해야. `_sample_binary` 가 parent_assignment 를 받으니
      sample 호출 순서가 topological 이어야 함
- [ ] `_attribute_failure()` 의 cause attribution 로직도 갱신해야
      ground truth 의 cause 카테고리에 새 변수가 반영됨
- [ ] 스키마에 property 추가했으면 `02_load_ontorag.py` 의 적재가
      증가한 triple 카운트를 반영함 (자동)
- [ ] DAG 추가 → `CausalEngine` 도 자동으로 새 변수 인식 (별도 코드 수정 X)

#### 검증

```bash
uv run pytest -q                                # 11 → 11+ tests pass
uv run python scripts/01_generate_data.py       # 새 데이터
uv run python scripts/04_run_causal.py          # P(fail) 변화 확인
```

---

## Recipe D — Rule 로는 못 잡는 동적 파라미터 액션

### 목표
새 액션의 파라미터가 **case state 의 특정 값** 에서 와야 하는 경우.
RuleEngine 은 templating 미지원 → rule 로는 못 박음.

### 패턴 (이미 `QuarantineLot` 이 동일 패턴)

`flow/runner.py` 에서 명시 호출:

```python
async def run_flow(store, ...):
    # ... Phase 1 (RuleEngine 자동) ...

    if case.status is CaseStatus.SUSPENDED:
        case = await manager.resume(case.case_uri)
        # case state 에서 동적 값 추출
        dynamic_value = case.state.properties.get("some_key")
        if not dynamic_value:
            raise RuntimeError("expected key missing from state")

        # 명시 호출
        case, _ = await manager.execute_action(
            case.case_uri,
            "urn:demo:manufacturing:YourAction",
            {"param": dynamic_value},
        )

        # Phase 4 (RuleEngine 자동으로 닫기)
        case = await _drive_until_terminal(manager, case.case_uri, console)
```

### 잊지 말 것

- [ ] process.yaml 에 *유사한 rule 을 만들지 말 것* — 두 곳에서 실행되어
      audit 가 이중으로 남음
- [ ] 대신 process.yaml 에 주석으로 "runner 가 명시 호출" 명시 (이미
      QuarantineLot 위에 같은 주석 패턴 있음)
- [ ] `constraints.requires` 에는 등록 — framework 가 순서 강제하는
      가드레일은 여전히 작동

---

## Recipe E — 새 process rule 추가 (정적 파라미터)

### 목표
case state 의 boolean / 숫자 만으로 결정 가능한 자동 액션 추가.

### 변경 패턴

`flow/process.yaml`:

```yaml
rules:
  # ... 기존 ...
  - name: "Symbolic name for the rule"
    when:
      some_state_key: true              # 정확 매치
      another_key: { gte: 10 }          # 비교 연산자
      defect_rate_percent: { gt: 50 }
    then:
      action: "urn:demo:manufacturing:YourAction"
      params:
        static_param: "literal value"   # 정적 값만
    confidence: 0.9
    rationale: "Why this rule fires."
```

지원되는 연산자: `gt`, `gte`, `lt`, `lte`, `eq`, `neq`, `in`, `not_in`
(자세한 건 `vendor/ontorag-flow/src/ontorag_flow/engines/rule.py` 참고).

### 잊지 말 것

- [ ] **rule 평가 순서는 *선언 순서* 가 아님** — RuleEngine 이 confidence
      높은 rule 부터 propose. 같은 confidence 면 의존성 (`constraints.requires`
      만족 여부) 으로 한 번 더 필터
- [ ] rule 의 `when` 키가 **case state 에 없으면** 해당 rule 은 안 fire.
      반드시 `initial_state` 에 default 값을 미리 선언
- [ ] 같은 액션의 두 rule 이 동시에 trigger 되면 confidence 가 높은 게 이김
- [ ] `auto_execute_disabled = True` 인 액션은 rule 이 fire 해도 *propose
      만* 되고 실행은 안 됨 → 운영자 click 또는 runner 명시 호출 필요

---

# Part 2 — 변경 영향 매트릭스

한 곳을 바꾸면 어디까지 *자동* 갱신, 어디는 *수동* 갱신이 필요한가.

| 변경 위치 | 자동 갱신되는 곳 | 수동 갱신 필요 |
|---|---|---|
| **`_CPDS` 의 확률값** | • sampler (같은 객체 import)<br>• BayesianEngine / CausalEngine<br>• `01_generate_data.py` 의 새 데이터<br>• 02-05 스크립트의 모든 숫자 | • README 의 결과 블록<br>• walkthrough 의 결과 블록<br>• `test_verify_causal.py` 의 expected 범위<br>• 적재 재실행 (`02_load_ontorag.py`) 필요 |
| **`NODES` 새 노드 추가** | • CPT validator (model_validator)<br>• CausalEngine 의 DAG 인식 | • sampler 의 sampling 호출<br>• `_attribute_failure()` cause 카테고리<br>• schema TTL (저장하려면)<br>• rdf_writer.py 의 트리플 emit<br>• 테스트 추가 |
| **`GeneratorConfig` 의 num_products / seed** | • 데이터 트리플 수<br>• ground truth 카운트<br>• 모든 03/04/05 결과 | • README / walkthrough 숫자<br>• `test_contaminated_lot_dominates` 의 `>= 5` 기준 |
| **`SUPPLIER_PROFILES` 변경** | • 새 데이터의 supplier-level 분포 | • ground truth 의 suspect_supplier_id<br>• 03 의 supplier 테이블<br>• README/walkthrough 의 supplier 숫자 |
| **`manufacturing.ttl` (schema) 변경** | (적재 재실행 시) Fuseki 의 TBox | • generator/rdf_writer.py (새 property emit)<br>• verify/trace.py (새 property 활용 query)<br>• 02 의 schema triple 카운트 |
| **`process.yaml` rule 추가** | • RuleEngine 평가 | • runner.py (동적 파라미터면)<br>• tests (액션 실행 검증)<br>• walkthrough 의 Q11~14 |
| **새 액션 (actions.py)** | • registry 등록 (build_domain_actions 갱신 시)<br>• executor 의 side_effect 처리 | • process.yaml (`allowed_actions`)<br>• constraints.requires (의존성)<br>• rules (자동화) 또는 runner.py (명시 호출)<br>• 테스트 |
| **`writeback.py` SPARQL UPDATE 변경** | Fuseki update endpoint 호출 | • 다른 backend (Neo4j/FalkorDB) 사용 시 별도 구현 필요 |
| **`DEMO_ONTOLOGY` 환경변수 변경** | • 적재되는 named graph URI<br>• writeback 의 WITH clause | • 02 적재 재실행 (이전 graph 는 stale)<br>• 03 의 verification 쿼리 (다른 graph 에 적재됨) |
| **vendor/ontorag 또는 vendor/ontorag-flow pull** | • editable install 이라 코드는 즉시 반영 | • API 시그니처 변경 시 우리 호출부 갱신<br>• 의존성 변경 시 `uv sync` 재실행 |

---

# Part 3 — 확장 포인트

## A. LlmAgentEngine 으로 RuleEngine 대체

### 무엇이 바뀌나
RuleEngine 은 선언적 rule 평가 — 정적, deterministic, 예측 가능.
LlmAgentEngine 은 LLM 이 case state 와 액션 카탈로그를 *직접 읽고*
proposal 생성 — 동적, non-deterministic, 새 상황에 적응.

### 코드 변경

`flow/process.yaml` 한 줄 추가:

```yaml
process_uri: "urn:demo:manufacturing:process:rca"
name: "Manufacturing high-defect-rate RCA"
engine: llm                                    # ← 추가 (기본은 rule)
# ... 나머지 동일 ...
```

환경변수:

```bash
export LLM_PROVIDER=anthropic
export LLM_MODEL=claude-sonnet-4-6
export ANTHROPIC_API_KEY=sk-ant-...
```

실행:

```bash
uv run python scripts/05_run_flow.py
```

### 보존되는 가드레일

LLM 이 무엇을 하든 framework 가 막아주는 것:

- **Unknown action_uri**: LlmAgentEngine 의 `_parse` 가 `allowed_actions`
  에 없는 URI 는 filter
- **Malformed JSON**: `_extract_json_array` 가 code fence / 산문 preamble
  tolerantly 처리
- **Prerequisite violations**: `constraints.requires` 위반 시
  `ConstraintViolationError` (CaseManager 가 강제)

### 데모 시 주의

- LLM 이 새 액션을 모르면 (action 추가했는데 LLM 이 학습 안 됨) propose
  안 함 → action description 을 풍부하게 작성
- 비결정성으로 README/walkthrough 숫자 재현 불가 → 별도 deterministic
  fake mode (`run_demo_llm.py` 패턴 차용) 추천

### 비교용 변형
같은 process.yaml 을 두 엔진으로 한 번씩 돌려 audit 차이 비교:

```python
# rule 엔진
process_rule = load_process(PROCESS_YAML)

# llm 엔진
process_llm = process_rule.model_copy(update={"engine": "llm"})
```

---

## B. MCP transport 로 ontorag 호출 전환

### 현재 vs 전환 후

| 항목 | 현재 | MCP 전환 후 |
|---|---|---|
| ontorag 호출 위치 | `flow/actions.py` 의 액션 내부 | ontorag_flow 의 `OntoragClient` 경유 |
| transport | Python in-process | HTTP MCP |
| 프로세스 수 | 1 (단일 driver) | 2 (ontorag MCP server + flow driver) |
| 장점 | 단순, 빠름 | production-shape, 다중 client 가능 |
| 단점 | flow 와 ontorag 가 같은 프로세스 | 두 서비스 운영 + 네트워크 latency |

### 코드 변경 위치

1. **ontorag MCP server 띄우기:**
   ```bash
   cd vendor/ontorag
   uv run ontorag serve --port 8000
   ```

2. **`flow/actions.py` 의 액션 생성자 변경:**
   ```python
   # 현재
   class PinpointSuspectLot(BaseAction):
       def __init__(self, store: GraphStore) -> None:
           self._store = store

   # MCP 전환 후
   from ontorag_flow.ontorag_client.client import OntoragClient
   from ontorag_flow.ontorag_client.tools import query_pattern  # 또는 raw sparql

   class PinpointSuspectLot(BaseAction):
       def __init__(self, client: OntoragClient) -> None:
           self._client = client

       async def execute(self, ...):
           result = await query_pattern(self._client, sparql_or_pattern)
           # ...
   ```

3. **`build_domain_actions` 의 인자 변경:**
   ```python
   def build_domain_actions(client: OntoragClient) -> tuple[BaseAction, ...]:
       return (
           PinpointSuspectLot(client),
           # ...
       )
   ```

4. **`writeback.py` 도 직접 SPARQL UPDATE 대신 `assert_triple`/`retract_triple`
   MCP tool 호출로 변경.**

### 잊지 말 것

- [ ] ontorag 서버가 BN/Causal MCP tool 을 expose 해야 (`compute_posterior`,
      `do_query`, `counterfactual` 라우트) — v0.7.3 이후 OK
- [ ] `verify/causal.py` 도 in-memory 대신 MCP 호출로 갈지 결정 — 안 가도
      되지만 일관성 위해 가는 게 권장
- [ ] env var `ONTORAG_MCP_URL=http://localhost:8000` 추가

---

## C. Graph backend 교체 (Neo4j / FalkorDB)

### 환경변수만

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

ontorag 의 추가 의존성:

```bash
uv add 'ontorag[neo4j]'     # 또는 [falkordb]
```

### 코드 변경 필요한 곳

- `create_store()` 는 환경변수로 자동 선택 → 우리 코드 변경 없음
- `verify/trace.py` 의 SPARQL — Neo4j/FalkorDB 는 Cypher 가 native.
  ontorag 의 `query_pattern` 으로 작성하면 자동 변환. 하지만 우리는
  raw SPARQL 을 쓰니까 — **이 부분은 동작 안 함** (Neo4j/FalkorDB 의
  `_sparql_select` 는 미구현 또는 다른 형태)
- `flow/writeback.py` — **Fuseki 의 `/update` 엔드포인트 가정**. 다른
  backend 면 ontorag 의 `assert_triple` MCP 또는 backend-specific
  Cypher UPDATE 로 재작성 필요

### 권장 마이그레이션 순서

1. `verify/trace.py` 의 SPARQL 을 `query_pattern` (L2 JSON DSL) 로 변경
   — backend 무관
2. `writeback.py` 를 MCP `assert_triple` 호출로 변경 (Recipe B 참고)
3. backend 환경변수 변경

---

## D. 실데이터로 전환

### 가장 큰 차이

- ground truth 없음 → 검증은 도메인 전문가
- 노이즈가 훨씬 많아 인과 분석 신뢰도 ↓
- 연속 센서값 → discretize preprocessor 필요

### 코드 변경 위치

1. **`generator/` 디렉터리 통째로 ETL 로 교체.** 외부 DB / 파일에서
   읽어 `entities.py` 의 dataclass 로 채운 뒤 `rdf_writer.py` 재사용.
2. **`schema/manufacturing.ttl` 의 `mfg:condition` 을 연속값 (xsd:decimal)
   으로 변경** + 별도 discretize 함수 도입.
3. **BN 의 CPT 를 데이터에서 학습** — ontorag 의 `bayes/learn.py` 활용
   (`ontorag bayes learn-cpt`).
4. **DAG 도 데이터에서 학습** — `ontorag.causal.discovery` 의 PC 알고리즘
   (proposal-only).

### 데모로서의 가치 변화

실데이터로 가면 *재현성* 이 사라짐 (랜덤성, 외부 시스템 의존). 즉
README/walkthrough 에 결과를 박을 수 없음 → 별도 *example trace* 형태로
보관.

---

# Part 4 — Troubleshooting

## "Fuseki connection refused"

```
httpx.ConnectError: All connection attempts failed
```

체크리스트:

1. `lsof -nP -iTCP:3030 -sTCP:LISTEN` 으로 누가 3030 잡고 있는지 확인
2. `curl http://localhost:3030/$/ping` 으로 alive 확인
3. `vendor/ontorag/docker-compose.yml` 의 컨테이너 가동 확인
4. `FUSEKI_URL` env var 가 다른 호스트 가리키는 건 아닌지

## "403 Access denied : only localhost access allowed"

원인: Fuseki 의 admin endpoint (`/$/datasets` 등) 는 기본적으로
localhost-only. Docker 경유 시 forwarded IP 가 localhost 가 아닌
것으로 인식될 수 있음.

대응: 일반 SPARQL endpoint (`/ontorag/sparql`, `/ontorag/update`) 는
정상 동작 — 그쪽으로만 호출.

## "FUSEKI_DATASET 가 없다고 한다"

```
{"error": "Dataset 'ontorag' not found"}
```

대응:

```bash
curl -X POST http://localhost:3030/$/datasets -d "dbName=ontorag&dbType=tdb2"
```

(또는 ontorag 의 docker-compose 가 자동 생성)

## "pgmpy FutureWarning"

```
FutureWarning: `pgmpy.estimators.StructureScore` is deprecated and will be removed in v1.3.0.
```

원인: ontorag v1.0 이 pgmpy v1.2 사용, pgmpy v1.3 에서 deprecate 예정.
영향 없음 — 무시 가능. ontorag 가 업데이트되면 자동 해결.

## "vendor/ontorag 의 코드 변경이 우리 코드에 반영 안 된다"

이론적으로 `[tool.uv.sources]` 의 editable install 이라 바로 반영되어야
하지만, **uv lock 이 캐시** 할 수 있음.

대응:

```bash
uv sync --reinstall-package ontorag
uv sync --reinstall-package ontorag-flow
```

## "LOT-0047 이 결과에 안 나온다"

체크리스트:

1. `random_seed` 가 변경되지 않았는가 (`causal/model.py::GeneratorConfig`)
2. `contaminated_lot_index` 가 47 인가
3. `01_generate_data.py` 를 *최신 config 로 다시* 돌렸는가
4. `02_load_ontorag.py` 도 *재* 적재 (이전 데이터가 fuseki 에 남아있음)
5. `DEMO_ONTOLOGY` 가 어긋나면 다른 named graph 를 조회 중일 수 있음

## "테스트는 통과하는데 README 의 숫자가 다르다"

원인: 누군가 CPT 를 바꿨거나, num_products 를 바꿨음. 테스트는 *범위*
검증이라 통과하지만 README 의 *정확한 값* 은 갱신 필요.

대응: Part 5 표준 사이클의 step 7 (README 숫자 동기화) 수행.

## "이전 quarantine 결과가 다음 실행에 영향"

원인: write-back 이 Fuseki 에 영속. 다음 실행 시 그 triple 이 남아있음.

대응:

```bash
# Fuseki 의 manufacturing-demo 데이터 그래프만 지우기
curl -X DELETE "http://localhost:3030/ontorag/data?graph=urn:ontorag:manufacturing-demo:data"
# 그리고 다시 적재
uv run python scripts/02_load_ontorag.py
```

또는 더 간단히 `--ontology` 옵션으로 다른 scope 에 적재:

```bash
uv run python scripts/02_load_ontorag.py --ontology manufacturing-demo-2
```

---

# Part 5 — 표준 개발 사이클

코드를 한 줄이라도 바꾼 뒤의 *순서 있는* 작업 흐름.

```
   변경 의도 명확화
        ↓
   Recipe 선택 (A-E)
        ↓
   코드 수정
        ↓
   uv run pytest -q                 ← invariant 회귀 즉시 발견
        ↓
   (데이터 변경이면)
   uv run python scripts/01_generate_data.py
        ↓
   (적재 변경이면)
   uv run python scripts/02_load_ontorag.py
        ↓
   uv run python scripts/03_run_trace.py
   uv run python scripts/04_run_causal.py
   uv run python scripts/05_run_flow.py
        ↓
   README/walkthrough 숫자 동기화 (변경 영향 매트릭스 참고)
        ↓
   git commit
```

## 각 단계 체크리스트

### 1. 변경 의도 명확화

- [ ] "어느 추상화 레벨" 에서의 변경인가? (data / BN / schema / flow)
- [ ] 변경 영향 매트릭스 (Part 2) 로 *수동 갱신 필요한 곳* 미리 파악
- [ ] 어느 Recipe (A-E) 에 해당하나

### 2. 코드 수정

- [ ] frozen dataclass / immutable 패턴 유지
- [ ] 단일 source of truth 원칙 (CLAUDE.md) — 같은 정보를 두 곳에 안 둠

### 3. `uv run pytest -q`

- [ ] 11 passed 가 유지되는가
- [ ] 깨진 테스트가 *의도된 변경* 인지 *의도치 않은 회귀* 인지 판단
- [ ] 의도된 변경이면 테스트도 같이 갱신

### 4. 데이터 / 적재 재실행

데이터 자체가 바뀌었으면 **반드시** 01 → 02 순서:

- [ ] `data/generated/manufacturing-instances.ttl` 재생성
- [ ] `data/generated/ground_truth.json` 도 같이 새 값으로
- [ ] Fuseki 의 이전 데이터가 남아있지 않게 02 가 idempotent
      (load_rdf 의 `replace=True` 또는 named graph 격리)

### 5. 검증 스크립트

- [ ] 03 의 SPARQL 카운트가 ground truth 와 일치하는가
- [ ] 04 의 P(fail) 값이 예상대로 변했는가
- [ ] 05 의 5-action lifecycle 이 close 까지 도달하는가

### 6. README/walkthrough 숫자 동기화

변경 영향 매트릭스 (Part 2) 의 "수동 갱신 필요" 컬럼이 안내자.
양쪽 (한국어/영어) 모두 동시 갱신 — 결과 블록은 동일 텍스트.

- [ ] README.{ko,}.md 의 "Real output" 블록
- [ ] walkthrough.{ko,}.md 의 각 Q 결과 블록
- [ ] implementation.{ko,}.md 의 검증/효과 블록 (확률값 인용한 곳)

### 7. git commit

- [ ] 한 commit = 한 개념적 변경 (Recipe 1개 = 1 commit 정도)
- [ ] CLAUDE.md 의 commit message 가이드라인 따라 — type prefix
      (feat/fix/refactor/docs/test/chore)

---

이 다섯 part 로 데모 위에서 안전하게 작업할 수 있습니다. 그래도 막힐
때는 — 가장 좋은 디버그 도구는 **결정론적 재실행** 입니다. 같은 seed,
같은 명령으로 재생산되니까 *어디서부터 다른가* 가 즉시 보입니다.
