# ontorag-demo

> **🇺🇸 English README:** [README.md](./README.md)

[`ontorag`](https://github.com/nuri428/ontorag) (Semantic + Dynamic 추론)와
[`ontorag-flow`](https://github.com/nuri428/ontorag-flow)
(Kinetic / Adaptive Case Management)를 결합한 **합성 제조 traceability +
인과 RCA 데모**.

설계 의도는 [`ontorag_flow_demo_plan.md`](./ontorag_flow_demo_plan.md)에
있고, 이 README는 **실행 매뉴얼 + 실제 출력 로그** 역할입니다. 모든
스크립트의 실제 출력이 아래에 박혀 있어서, 직접 돌리지 않아도 데모를
처음부터 끝까지 읽을 수 있습니다.

세 개의 보조 문서가 한층 깊이 들어갑니다:

* **[docs/walkthrough.ko.md](./docs/walkthrough.ko.md)** — *"각 답이 어떻게
  도출되는가"* — 14개 질문 × (데이터, 쿼리, 결과, 해석).
* **[docs/implementation.ko.md](./docs/implementation.ko.md)** — *"왜 코드가
  이 모양이 되었나"* — 12개 설계 결정 × (문제, 옵션, 선택, 코드 적용, 검증).
* **[docs/dev_guide.ko.md](./docs/dev_guide.ko.md)** — *"이 위에서 어떻게
  작업하나"* — 5개 change recipes + 변경 영향 매트릭스 + 확장 포인트 +
  troubleshooting + 개발 사이클.

---

## 이 데모가 보여주는 이야기

완제품 QC 파이프라인에서 운영팀이 예상한 것보다 높은 불량률이
관측됐다고 합시다. 이때 두 가지 질문을 *동시에* 답하기가 어렵습니다 —
온톨로지 기반 추론 스택 없이는:

1. **좁히기 (traceability)** — 어떤 *로트 / 공급사 / 공정 런*이
   불량 제품에 과대표상되는가? (L1, 다중홉 SPARQL)
2. **인과로 설명하기** — 일단 범위가 좁혀지면, 진짜 원인이
   *부품*(공급사 / 로트 품질)인가, *공정*(조립 단계 조건)인가?
   단순 집계는 둘을 섞어버립니다. `do(SupplierQuality=good)` vs
   `do(AssemblyPressure=normal)` 만이 갈라줍니다. (L3, Pearl Rung 2 + 3)

그리고 마지막으로 루프를 닫습니다:

3. **감사 가능한 행동** — 추천 → 개입안 점수화 → 운영자 승인 →
   ontorag ABox에 `mfg:quarantined=true` write-back →
   counterfactual replay ("격리 안 했으면 어땠을까?") →
   PROV-O 활동 로그로 forensic 추적 가능.

---

## 구조

```
<parent>/                       # 세 자매 repo를 나란히 담는 임의의 디렉토리
├── ontorag/                    # https://github.com/nuri428/ontorag clone
├── ontorag-flow/               # https://github.com/nuri428/ontorag-flow clone
└── ontorag-demo/               # 이 repo
    ├── ontorag_flow_demo_plan.md   # 설계 의도 (먼저 읽기)
    ├── src/ontorag_demo/
    │   ├── schema/                 # 1단계 — OWL/Turtle TBox
    │   ├── causal/                 # 2단계 — Bayesian network + Causal DAG
    │   ├── generator/              # 3단계 — 합성 sampler + RDF writer
    │   ├── verify/                 # 4단계 — SPARQL traceability + posterior/do/CF
    │   └── flow/                   # 5단계 — 액션 + process YAML + runner
    ├── scripts/                    # 번호순으로 실행
    │   ├── bootstrap.sh            # 위 자매 repo가 없으면 clone
    │   ├── 01_generate_data.py
    │   ├── 02_load_ontorag.py
    │   ├── 03_run_trace.py
    │   ├── 04_run_causal.py
    │   └── 05_run_flow.py
    ├── tests/
    ├── data/generated/             # 01이 생성 (gitignored)
    └── runs/flow/                  # 05가 생성 (gitignored)
```

---

## 사전 준비

* Python 3.12+ 와 [`uv`](https://docs.astral.sh/uv/) (`brew install uv`).
* `FUSEKI_URL`(기본 `http://localhost:3030`)에서 동작 중인 Fuseki,
  데이터셋 이름은 `FUSEKI_DATASET`(기본 `ontorag`). 두 가지 방법:

  ```bash
  # A) ontorag의 compose 재활용 (검증된 조합).
  cd ../ontorag && docker compose up -d

  # B) 직접 Fuseki 5.x 이미지를 :3030에 dataset "ontorag"으로 띄우기.
  ```

  데모는 `manufacturing-demo` 라는 named-graph 스코프로 격리되므로
  같은 Fuseki에 다른 데이터가 있어도 충돌하지 않습니다.

* **자매 프레임워크 clone.** `ontorag`과 `ontorag-flow`는 이 repo
  *옆 디렉토리*(`../ontorag`, `../ontorag-flow`)에서 editable install로
  참조되므로, 프레임워크를 수정하면 demo에 즉시 반영됩니다. 다음으로
  받아두세요:

  ```bash
  ./scripts/bootstrap.sh   # 이미 있는 repo는 건너뜀
  ```

  `pyproject.toml`의 `[tool.uv.sources]`가 이미 위 자매 경로를 editable
  install로 가리킵니다.

* 의존성 설치:

  ```bash
  uv sync --extra dev
  cp .env.example .env       # 선택 — :3030이면 기본값으로 OK
  ```

---

## 5단계 워크스루 (실제 출력 포함)

### 1단계 — 스키마 (TBox, 실행 스크립트 없음)

`src/ontorag_demo/schema/manufacturing.ttl`이 **7개 클래스**와 **12개
프로퍼티**를 정의합니다. 한 가지 강조할 설계 결정: 공정 조건을
`ProcessRun`에 **이산 `mfg:condition` 문자열**로 둡니다. 그래야
pgmpy가 별도 binning 전처리 없이 그대로 소비할 수 있습니다 (플랜 §2).

```turtle
mfg:ProcessRun a owl:Class .
mfg:condition  a owl:DatatypeProperty ;
    rdfs:domain mfg:ProcessRun ;
    rdfs:range  xsd:string .   # 값: "normal" | "high" | "low"
```

### 2단계 — Bayesian network + Causal DAG (실행 스크립트 없음)

`src/ontorag_demo/causal/model.py`가 **단일 source of truth** 입니다.
3단계의 데이터 생성기를 정량화하면서, 동시에 4단계의 ontorag
`BayesianEngine` / `CausalEngine`에도 들어갑니다. 7개 노드, 하나의
상호작용, 두 개의 독립 공정 노이즈 변수:

```
SupplierQuality ─→ LotQuality ─→ ComponentQuality ─┐
                                                   ├─→ ProductDefect
                  AssemblyPressure ────────────────┘
MachiningTemperature   (노이즈 — 독립)
InspectionMoisture     (노이즈 — 독립)
```

### 3단계 — 합성 데이터 생성

```bash
uv run python scripts/01_generate_data.py
```

**실제 출력:**

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

**주목할 점.** 가장 빈도 높은 원인은 `process_only`(66건) — *공급사가
아님*. SUP-B가 공급사별 실패 카운트 1위이지만, SUP-D와의 격차가 14건
밖에 안 됩니다. "1위 공급사 격리"라고 자신 있게 부를 수 있는 격차가
아니죠. 이 간극을 4단계의 인과 레이어가 닫습니다.

> **읽을 때 주의 — heuristic attribution.** "Failures by attributed
> cause" 의 카테고리는 생성기 내부의 *휴리스틱 라벨* 입니다 (sampler
> 가 각 실패의 *지배적* 원인 하나만 선택). 따라서 `contaminated_lot
> = 3` 은 *LOT-0047 영향 받은 모든 실패의 수가 아니라*, lot 단독
> 영향이 두드러진 3 건만 의미합니다. LOT-0047 의 *전체* 실패 카운트는
> 4a 의 traceability 표에서 **10 건** (그 lot 의 12 개 추적 가능 제품
> 중 10 개) 으로 확인됩니다.

### 4단계 — ontorag 단독 검증

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

Sanity check — LOT-0047에서 추적되는 제품
  12개 제품: PRD-00047, PRD-00097, PRD-00147, PRD-00197, PRD-00247, PRD-00297, ...
```

**주목할 점.** 모든 카운트가 ground truth와 정확히 일치합니다. 즉
다중홉 SPARQL JOIN
(`QCResult ← Product ← ProcessRun ← Component ← Lot ← Supplier`)이
스키마를 제대로 따라간다는 증거입니다. 오염된 LOT-0047이 1위로
떠오릅니다 — **그 lot 에서 추적되는 12 개 제품 중 10 개 (≈83%) 가
실패**, 전체 평균 25.2% 의 약 3 배 (이게 *lot 신호의 강도*).
`조립 조건 vs 실패` 표는 *상관일 뿐* — 110 vs 41이 결정적으로 보이지만,
L1만으로는 인과를 증명할 수 없습니다.

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

**주목할 점 — 이 데모의 결정타.**

> **baseline 두 종류 구분.** 표의 `baseline (marginal) = 0.265` 는
> **BN 의 marginal P(fail)** (변수 소거로 계산된 모델값). 한편
> 합성 데이터의 **실측 비율은 25.2% (151/600)** — Stage 3 출력 참고.
> 두 값이 가까운 것이 *생성기-추론 모델 정합성의 증거* 입니다 (양쪽이
> 같은 CPT 를 공유하므로 자동 정합). 모든 Δ 는 *모델 baseline 0.265*
> 기준입니다.

* `see(SupplierQuality=bad) = 0.467` 이라서 SUP-B가 명백한 범인처럼
  보입니다. 이것이 **관찰적 / L2** 시각입니다.
* `do(SupplierQuality=good)`로 개입하면 P(fail)이 **0.07**만 떨어집니다.
  상관이 시사한 것보다 개입 효과가 훨씬 약합니다.
* `do(AssemblyPressure=normal)`은 P(fail)을 **0.13** 떨어뜨립니다 —
  공급사 개입의 *거의 2배*. **공정이 더 큰 지렛대**입니다.
* `do(both)` 의 효과는 ***near-additive***: 관측된 −0.200 ≈ 두 단일
  개입의 합 (0.067 + 0.134 = 0.201). 두 인과 경로가 DAG 에서
  부모-자식 관계가 아니라 거의 독립이라 *정확한 가법은 아니지만 매우
  근접*. 운영 의사결정에는 "둘 다 잡으면 둘의 합산에 가까운 효과
  기대" 정도로 읽으면 충분.
* `counterfactual = 0.222`는 *인스턴스 단위* 질문에 답합니다: "이
  특정 제품이 낮은 압력에서 실패했다. 압력이 정상이었다면 실패 확률이
  22% 였을 것이다". 이게 Pearl Rung 3이고, L1/L2 쿼리로는 절대
  생성할 수 없는 답입니다.

### 5단계 — ontorag-flow로 루프 닫기

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

──────────────────────────── 최종 케이스 상태 ──────────────────────────────────
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

#### Write-back이 실제로 ontorag에 반영됐는지 확인

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

이 한 줄이 추가된 트리플이 *어떤* downstream SPARQL 소비자에게도
보인다는 증거입니다 — 플랜 §6의 "closed loop" 반쪽이 완성된 거죠.

---

## 플랜 §6 부품 매핑

| `ontorag` / `ontorag-flow` 부품 | 데모에서 실제로 호출되는 곳 | 출력에서 보이는 자취 |
|---|---|---|
| L0 저장소 (Fuseki/Neo4j/FalkorDB) | `02_load_ontorag.py`의 `create_store()` | `TBox → 109 triples` 줄 |
| L1 논리 (다중홉 순회) | `verify/trace.py`의 SPARQL JOIN | 4a의 표들 |
| L2 확률 (`compute_posterior`) | `verify/causal.py::observational_supplier_bad` | `see(SupplierQuality=bad) = 0.467` |
| L3 개입 (`do_query`) | `verify/causal.py::do_*` | `do(...) [L3]` 행 |
| L3 반사실 | `verify/causal.py::counterfactual_assembly_was_normal` | `counterfactual: 0.222` |
| 결정 엔진 (6종) | `flow/process.yaml`의 RuleEngine (4 rule + 4 `requires`) | "#1..#3 picks" 로그 |
| Case + 상태머신 + saga | `flow/runner.py`의 `CaseManager` | `open → suspended → open → closed` 라이프사이클 |
| Provenance (PROV-O) | `runs/flow/audit.ttl`로 export | "PROV-O activities" 표 |
| write-back (`AssertTriple` 대체) | `flow/writeback.py`의 SPARQL UPDATE | 검증 curl이 돌려준 `LOT-0047` |

플랜 §6과 의도적으로 다른 한 가지: 데모는 ontorag-flow의 MCP 클라이언트를
우회하고, 커스텀 액션 안에서 ontorag의 Python API를 직접 호출합니다.
덕분에 두 개의 HTTP 서비스를 띄울 필요 없이 단일 `uv run`으로 전체
루프가 돌아갑니다. MCP 전송 방식으로 되돌리려면
`flow/actions.py::build_domain_actions`의 생성자를 ontorag-flow의
`with_triple_actions(client)`로 교체하면 됩니다.

---

## 테스트

```bash
uv run pytest -q
```

```text
...........                                                              [100%]
11 passed, 1 warning in 5.01s
```

테스트 11개가 BN/Causal 불변(CPT 행 합, DAG 엣지 미러링), 데이터
생성기의 결정성 + 오염 신호, 그리고 "공정 > 공급사" 주장을 엔진
수준에서 검증합니다. 모두 Fuseki 없이 돕니다.

---

## 라이선스

MIT.
