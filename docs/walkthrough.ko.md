# 데모 walkthrough — 데이터, 질의, 결과, 해석

> **🇺🇸 English:** [walkthrough.md](./walkthrough.md)
> **상위 README:** [README.ko.md](../README.ko.md)
> **자매 문서:** [implementation.ko.md](./implementation.ko.md) (코드 설계 결정) · [dev_guide.ko.md](./dev_guide.ko.md) (이 위에서 작업하기)

이 문서는 README의 "무엇이 나오는가"를 한 발 더 깊이 들어가서,
**각 질문에 어떻게 답을 도출했는지** 를 단계별로 보여줍니다.

구성은 한결같습니다 — 14개 질문 각각에 대해:

| 항목 | 의미 |
|---|---|
| **질문 (자연어)** | 운영팀이 던질 법한 비즈니스 질문 |
| **사용 레이어** | L0(저장) / L1(SPARQL) / L2(posterior) / L3(do·counterfactual) / Flow |
| **도출 과정** | 데이터를 어떻게 거치고, 어떤 추론을 어디서 수행하는가 |
| **쿼리/호출** | 실제 코드/SPARQL, 가짜 의사코드 아님 |
| **결과** | 스크립트의 실제 출력 (재현 가능, seed 고정) |
| **해석** | 이 답이 왜 의미 있고, 왜 다른 레이어로는 답할 수 없는가 |

---

## 0. 데이터 설명 — "이 데모의 우주에는 무엇이 있나"

### 엔티티 통계 (`01_generate_data.py` 1회 실행 후)

| 클래스 | 인스턴스 수 | 비고 |
|---|---:|---|
| `mfg:Supplier` | 5 | SUP-A ~ SUP-E |
| `mfg:Lot` | 50 | LOT-0001 ~ LOT-0050 |
| `mfg:Component` | 600 | 각 제품마다 1개 (1:1) |
| `mfg:ProcessRun` | 1,800 | 부품당 3개 공정 (machining/assembly/inspection) |
| `mfg:Product` | 600 | |
| `mfg:QCResult` | 600 | pass 449 / fail 151 (25.2%) |
| **총 RDF 트리플** | **14,010** | Turtle 직렬화 후 |

### 관계 그래프 (스키마 = 검색 경로)

```
Supplier ─supplies→ Lot ─hasComponent→ Component ─processedBy→ ProcessRun ─produces→ Product ─hasQC→ QCResult
                                                                     │
                                                                 atStep ↓
                                                                 ProcessStep
```

`mfg:condition` (예: "normal" / "low" / "high")이 각 ProcessRun에 달려서
공정 조건을 이산값으로 보존합니다. 이게 4단계 인과 추론의 입력입니다.

### 정답표 (`ground_truth.json` — 검증용으로만 사용)

생성기는 실제 공장 데이터엔 없을 "숨겨진 진실"을 따로 보관합니다:

```json
{
  "suspect_supplier_id": "SUP-B",          // P(bad lot)이 0.55 (평균 ~0.14의 4배)
  "contaminated_lot_id": "LOT-0047",       // P(bad lot)을 강제로 1.0으로 주입
  "causal_process_step_uri": ".../StepAssembly",  // 진짜 인과 공정
  "total_products": 600,
  "total_failures": 151,
  "failures_by_supplier": {"SUP-B": 46, "SUP-D": 32, ...},
  "failures_by_lot": {"LOT-0047": 10, "LOT-0027": 9, ...}
}
```

**왜 합성 데이터인가** — 실제 공장의 부품→로트→공급사→완제품 관계형
데이터는 영업비밀이라 공개본이 거의 없습니다. 합성이면 인과·관계 구조를
직접 통제하고, ground truth를 알고 있어 ontorag의 답을 *바이트 단위로*
검증할 수 있습니다 (질문 1~4가 그걸 보여줍니다).

### 인과 모델 (생성기 = 추론 모델, 동일)

```
SupplierQuality ─→ LotQuality ─→ ComponentQuality ─┐
                                                   ├─→ ProductDefect
                  AssemblyPressure ────────────────┘
MachiningTemperature   (노이즈 — ProductDefect와 무관)
InspectionMoisture     (노이즈 — ProductDefect와 무관)
```

CPT 일부:

| Condition | P(Defect=fail) |
|---|---:|
| Component=good, Pressure=normal | 0.02 |
| Component=good, Pressure=low    | 0.35 |
| Component=bad,  Pressure=normal | 0.50 |
| Component=bad,  Pressure=low    | 0.85 |

이 한 표가 데모의 모든 인과 결론의 뿌리입니다.

---

## L1 — 그래프 순회로 답할 수 있는 질문들

### 질문 1: "어떤 lot이 불량 제품을 가장 많이 만들었나?"

**사용 레이어:** L1 (다중홉 SPARQL)

**도출 과정:**

1. 모든 QCResult 중 `verdict="fail"` 만 필터.
2. QCResult → Product 역으로 1홉 ( `mfg:hasQC` 의 inverse ).
3. Product → ProcessRun 역으로 1홉 ( `mfg:produces` 의 inverse ).
4. ProcessRun → Component 역으로 1홉 ( `mfg:processedBy` 의 inverse ).
5. Component → Lot 역으로 1홉 ( `mfg:hasComponent` 의 inverse ).
6. Lot의 `lotId`별 GROUP BY + COUNT DISTINCT.
7. DESC 정렬 + LIMIT.

**쿼리** (`src/ontorag_demo/verify/trace.py::failures_per_lot`):

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

**결과:**

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

**해석:**

- 카운트가 ground truth와 모두 일치 → 5홉 SPARQL JOIN이 스키마 inverse
  관계를 따라 정확히 traversal 함. 즉 *데이터 자체에는 거짓이 없음*.
- **오염된 LOT-0047이 1위로 떠오릅니다.** 만약 운영팀이 이 표만 보고
  결정한다면 "LOT-0047 격리"가 자연스럽고 *옳은* 1순위 조치입니다.
  더 정량화하면: 질문 4의 traceability 가 보여주듯 *LOT-0047 에서
  나온 제품은 12 개* → **그 중 10 개 (≈83%) 가 실패**, 전체 평균
  25.2% 의 약 3 배. 즉 lot 단위 신호가 명백히 비정상.
- 그러나 2~5위가 다 8~9건이라, 단일 lot 격리만으론 위험을 다 못
  잡습니다 → 질문 3, 5~9로 이어집니다.

---

### 질문 2: "어떤 공급사가 불량과 가장 많이 연관됐나?"

**사용 레이어:** L1 (질문 1에 supplier로 1홉 추가)

**도출 과정:**
질문 1의 5홉을 그대로 따라가서 Lot까지 도달한 다음, Lot → Supplier로
한 번 더 거꾸로 (`mfg:supplies`의 inverse). 그 다음 supplierId 별 COUNT.

**쿼리** (`failures_per_supplier`):

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

**결과:**

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

**해석:**

- SUP-B가 1위지만 SUP-D와의 격차는 14건뿐 → **"1위 공급사 격리"라고
  자신 있게 결정하기엔 격차가 약합니다.**
- 이게 데모의 핵심 함정입니다. 생성기는 SUP-B에 P(bad lot)=0.55를
  명시적으로 심었지만, AssemblyPressure 노이즈가 supplier 효과를
  희석시켜 *집계 수준에서는 supplier 신호가 흐려집니다*.
- 즉 운영팀이 이 표만 보면 "SUP-B를 끊어야 하나? 아니면 SUP-D도?" 라는
  애매한 판단을 하게 됩니다. **L3 do_query만이 이걸 해결합니다 (질문 7).**

---

### 질문 3: "조립 공정 조건별로 불량은 어떻게 분포하나?"

**사용 레이어:** L1 (단순 GROUP BY)

**도출 과정:**
실패 제품 → 그 제품을 만든 ProcessRun들 → 그 중 `mfg:atStep mfg:StepAssembly`
인 것 → `mfg:condition` 별 카운트.

**쿼리** (`failures_per_assembly_condition`):

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

**결과:**

```text
┏━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┓
┃ Assembly condition ┃ Failures ┃
┡━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━┩
│ low                │      110 │
│ normal             │       41 │
└────────────────────┴──────────┘
```

**해석:**

- 110 vs 41 → "조립 압력이 낮을 때 약 2.7배 불량이 많다" 는 **상관관계
  증거**.
- **하지만 이게 인과인지 단언할 수 없습니다.** 가능한 대안 설명들:
  - 압력이 낮은 라인에 마침 나쁜 lot이 더 많이 흘러갔을 수도.
  - 압력과 부품 품질이 모두 다른 잠재 요인(예: 시간대)에 의해 영향받을 수도.
- 즉 L1은 *상관까지만* 보여주고, "압력을 정상으로 만들면 불량이 줄어드는가?"
  라는 **개입 질문(intervention)** 에는 답하지 않습니다. → 질문 8로 이어집니다.

---

### 질문 4: "오염 의심 lot(LOT-0047)에서 만들어진 제품은 어떤 것들인가?"

**사용 레이어:** L1 (그래프 순방향 순회)

**도출 과정:**
질문 1과 정반대 방향 — Lot에서 시작해서 Component → ProcessRun → Product
로 4홉 forward traversal.

**쿼리** (`products_from_lot`):

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

**결과:**

```text
12개 제품: PRD-00047, PRD-00097, PRD-00147, PRD-00197, PRD-00247, PRD-00297, ...
```

**해석:**

- 600 / 50 = 12 정확히 일치 → forward/inverse 양방향 traversal이 모두
  스키마 정의대로 동작한다는 확인.
- 운영팀에 "다음 출고 전에 이 12개를 다시 검사하자" 같은 *실행 가능한
  조치 리스트*를 즉시 제공할 수 있습니다.
- 이것이 traceability의 진짜 비즈니스 가치 — *책임 추적과 회수 범위
  확정*. L2/L3가 *왜* 라면, L1은 *누구를/무엇을*.

---

## L2 — 확률 추론으로 답하는 질문들

### 질문 5: "전체 평균 불량 확률은 얼마인가?" (baseline / marginal)

**사용 레이어:** L2 (`compute_posterior` with no evidence)

**도출 과정:**

1. ontorag의 `BayesianEngine(MANUFACTURING_BN)` 생성.
2. `compute_posterior(evidence={}, query=[ProductDefect_URI])` 호출.
3. pgmpy가 7개 노드 × 각 노드의 CPT를 변수 소거(Variable Elimination)로
   marginalize.

**호출** (`verify/causal.py::baseline`):

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

**결과:** `P(fail) = 0.265`

**해석:**

- 합성 데이터의 실제 관측 비율 25.2%와 거의 일치 (151/600). **데이터
  생성기와 BN이 같은 CPT를 공유한다는 자기검증.** 만약 둘이 어긋났으면
  여기서 격차가 났을 것.
- 이게 모든 다음 질문의 **비교 기준선**입니다.

---

### 질문 6: "공급사 품질이 나쁘다고 *관찰*되면 그 제품의 불량 확률은?"

**사용 레이어:** L2 (`compute_posterior` with evidence)

**도출 과정:**

1. evidence = `{SupplierQuality: "bad"}`.
2. pgmpy가 그 evidence를 조건부 분포에 반영해서 ProductDefect의 posterior
   계산.
3. 경로: SupplierQuality → LotQuality → ComponentQuality → ProductDefect
   에서, evidence가 추가로 들어와 LotQuality의 P(bad)이 증가 → 연쇄적으로
   ComponentQuality의 P(bad) 증가 → ProductDefect의 P(fail) 증가.

**호출** (`observational_supplier_bad`):

```python
raw = await engine.compute_posterior(
    evidence={NODES_BY_NAME["SupplierQuality"].uri: "bad"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
)
```

**결과:** `P(fail | see Supplier=bad) = 0.467`

**해석:**

- baseline 0.265 → 0.467 으로 거의 **2배 점프**.
- "공급사가 나쁜 게 확인되면 그 라인의 불량 확률은 거의 절반에 가깝다"
  — 강력한 **관찰적 결론**.
- **함정:** 이 값은 "공급사가 어쩌다 나쁜 것이 관측됐다" 라는 사실에
  *공급사가 나쁘게 만들어진 다른 이유들* 도 함께 업데이트된 결과입니다.
  즉 "공급사를 좋게 바꾸면" 이라는 *개입* 의 효과와는 다릅니다. 그
  격차가 질문 7에서 정확히 드러납니다.

---

## L3 — 인과 추론 (개입 / 반사실)

### 질문 7: "*만약* 모든 공급사를 좋게 만들 수 있다면, 불량 확률은?"

**사용 레이어:** L3 Rung 2 (do-calculus)

**도출 과정:**

1. CausalEngine(BN, DAG) 생성.
2. `do_query(do={SupplierQuality: "good"}, query=[ProductDefect])` 호출.
3. ontorag/pgmpy가 SupplierQuality로 들어오는 모든 화살표를 *잘라내고*
   (graph surgery), SupplierQuality=good을 외부에서 설정한 뒤 나머지를
   marginalize.
4. 결과: 공급사 경로(SupplierQuality→Lot→Component→Defect)의 효과만
   고립되어 측정됨. AssemblyPressure 등 다른 root는 자기 prior로 그대로.

**호출** (`do_supplier_good`):

```python
from ontorag.causal.engine import CausalEngine
engine = CausalEngine(MANUFACTURING_BN, MANUFACTURING_CAUSAL)
raw = await engine.do_query(
    do={NODES_BY_NAME["SupplierQuality"].uri: "good"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
    evidence={},
)
```

**결과:** `P(fail | do(Supplier=good)) = 0.197`

**해석:**

- baseline 0.265 → 0.197 = **−0.067**.
- 질문 6의 0.467(see)과 비교하면 **격차가 0.27**. **"관찰"과 "개입"이
  완전히 다른 답**을 준다는 증거 — Pearl의 핵심 메시지.
- 즉 "공급사를 모두 좋게 만든다"는 매우 큰 개입을 해도 baseline에서
  7%p만 떨어집니다. **공급사 개입의 절대 효과는 생각보다 작다.**

---

### 질문 8: "*만약* 조립 압력을 모두 정상으로 만들 수 있다면?"

**사용 레이어:** L3 Rung 2

**도출 과정:** 질문 7과 동일한 구조, 다만 do() 대상을 AssemblyPressure로 변경.

**호출** (`do_assembly_normal`):

```python
raw = await engine.do_query(
    do={NODES_BY_NAME["AssemblyPressure"].uri: "normal"},
    query=[NODES_BY_NAME["ProductDefect"].uri],
    evidence={},
)
```

**결과:** `P(fail | do(Pressure=normal)) = 0.131`

**해석:**

- baseline 0.265 → 0.131 = **−0.134**.
- 질문 7의 −0.067과 비교 → **공정 개입이 공급사 개입의 약 2배 효과**.
- **L1 traceability(질문 2)에서 SUP-B를 의심하던 운영팀이라면, 이
  결과 하나로 *우선 순위가 뒤집힙니다*** — 공정 라인을 먼저 잡아야
  ROI가 더 큽니다.
- 이 결론은 L1에서는 절대 도출 불가능 (질문 3의 110 vs 41은 상관이지
  개입 효과가 아님).

---

### 질문 9: "둘 다 개입한다면 효과는 합산되나?"

**사용 레이어:** L3 Rung 2 (multi-variable do)

**도출 과정:** do()에 두 변수를 동시 지정.

**호출** (`do_both`):

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

**결과:** `P(fail | do(both)) = 0.064`

**해석:**

- 관측된 Δ −0.200 ≈ 두 단일 개입의 합 0.201 (= 0.067 + 0.134). 즉
  ***near-additive*** 이지 정확한 가법은 아님 (0.001 의 작은 음의
  상호작용 — DAG 상 두 경로가 같은 자식 노드 ProductDefect 에서
  *함께* CPT 의 비선형 셀에 매핑되기 때문).
- 거의 가법이 되는 이유는 두 인과 경로가 DAG 에서 부모-자식 관계가
  아니라 *간섭이 거의 없는* 별개 경로이기 때문.
- 운영 의사결정 측면에서: "공정만 잡으면 어느 정도, 공급사도 잡으면
  추가로 거의 합산" — 예산이 허락하면 둘 다 하는 게 가장 효과적
  (단, 인과 경로가 *겹치는* 도메인에서는 합산이 깨질 수 있음을 유의).

---

### 질문 10: "*이 한 제품*이 정상 압력에서 만들어졌다면 통과했을까?"

**사용 레이어:** L3 Rung 3 (counterfactual)

**도출 과정 (abduction-action-prediction):**

1. **Abduction** — 관측된 사실
   (`AssemblyPressure=low ∧ ProductDefect=fail`)을 만들어낸 latent noise
   상태들이 무엇이었을지 inverse 계산.
2. **Action** — 그 latent noise는 유지한 채, AssemblyPressure만
   "normal"로 강제 (do).
3. **Prediction** — 그 hypothetical world에서 ProductDefect의 분포 계산.

ontorag은 canonical independent-noise SCM 위에서 response-function
enumeration으로 이걸 정확히 풉니다 (smoking 예제의 P5 검증과 동일 코드 경로).

**호출** (`counterfactual_assembly_was_normal`):

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

**결과:** `P(fail | observed=(low, fail), intervened=(normal)) = 0.222`

**해석:**

- 이 답은 *집계 평균* 이 아닙니다. **이 특정 제품이 "압력이 정상이었다면"
  실패했을 확률**.
- 0.222 = "78% 확률로 통과했을 것" → 이 한 제품에게는 압력이
  결정적이었다는 결론.
- **이게 L3 Rung 3의 유일한 답변 영역입니다.** Rung 1(보기)나 Rung 2(개입)는
  "이 특정 사건이 어쨌으면 어땠을까"에 답할 수 없습니다.
- 비즈니스 용도: 보상 청구, 책임 분석, 운영 사후검토 — "*이* 출하분이
  공정 탓이었나 부품 탓이었나" 를 정량적으로 판단.

---

## Flow — ontorag-flow가 위 질문들을 결정 흐름으로 조합

이 단계는 **인간 한 명의 직무를 자동화** 하는 부분입니다.
질문 1~10이 *분석 도구* 였다면, 11~14는 *그 도구들을 어느 순서로 쓰고
누가 결정하고 어떻게 기록하는가* 를 다룹니다.

### 질문 11: "case가 열리면 *자동으로* 의심 lot을 어떻게 선택하나?"

**사용 레이어:** Flow Action `PinpointSuspectLot` (내부에서 L1 호출)

**도출 과정:**

1. RuleEngine이 case 초기 상태 `defect_rate_percent: 25` 를 보고 첫 번째
   rule을 trigger:

   ```yaml
   - name: "High defect rate — pinpoint suspect lot first"
     when:
       defect_rate_percent: { gte: 10 }
       suspect_lot_known: false
     then:
       action: "urn:demo:manufacturing:PinpointSuspectLot"
   ```

2. `PinpointSuspectLot.execute`가 내부에서 질문 1과 같은 SPARQL을 돌림
   (`failures_per_lot(store, limit=5)`).
3. 1위 lot을 case state에 기록 (`suspect_lot_id`, `suspect_lot_failures`,
   `suspect_lot_known=true`).

**결과 (case state 변화):**

```text
suspect_lot_id: LOT-0047
suspect_lot_failures: 10
suspect_lot_known: True
```

**해석:**

- 운영자가 SPARQL을 직접 쓸 필요 없이, *질문이 자동으로 던져지고 답이
  case 상태에 기록* 됩니다.
- 모든 결정의 출발점이 audit log에 남아 PROV-O로 재추적 가능.

---

### 질문 12: "어떤 개입이 가장 효과적인지 *자동으로* 어떻게 결정하나?"

**사용 레이어:** Flow Action `EvaluateIntervention` (질문 7~9 묶음)

**도출 과정:**

1. 두 번째 rule이 fire (조건: `suspect_lot_known=true ∧
   causal_evaluation_done=false`).
2. `EvaluateIntervention.execute`가 질문 7, 8, 9를 차례로 호출.
3. 셋 중 P(fail)이 가장 낮은 개입을 추천.

**호출 (의사 코드):**

```python
candidates = {
    "supplier_only": (await do_supplier_good()).p_fail,       # 0.1971
    "process_only":  (await do_assembly_normal()).p_fail,     # 0.1307
    "supplier_and_process": (await do_both()).p_fail,         # 0.0644
}
recommended = min(candidates, key=candidates.get)             # "supplier_and_process"
```

**결과 (case state):**

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

**해석:**

- **인과 분석 결과가 case의 영속 속성** 으로 박힙니다 → 나중에 누가 봐도
  "이 결정의 근거가 무엇이었는가"를 정확히 알 수 있음.
- 인간 운영자가 이 case를 열어보면, 본인의 직관과 데이터의 인과 결론을
  비교한 뒤 다음 단계 (질문 13의 승인)로 진행할지 결정.

---

### 질문 13: "결정한 다음 그걸 ontorag에 어떻게 반영하나?" (write-back)

**사용 레이어:** Flow Action `RequestQuarantineApproval` (HUMAN) +
`QuarantineLot` (ABOX_WRITE)

**도출 과정:**

1. 세 번째 rule이 `RequestQuarantineApproval` 호출 → side_effect=`HUMAN`
   이라 CaseManager가 **자동으로 케이스를 suspend**.
2. 외부에서 `manager.resume(case_uri)` 호출 (데모는 이걸 시뮬레이션).
3. runner가 case state에서 `suspect_lot_id="LOT-0047"`을 읽어
   `lot_uri_for("LOT-0047")` 로 URI 복원.
4. `manager.execute_action(case_uri, QuarantineLot, {"lot_uri": ...})` 호출.
5. `QuarantineLot.execute`가 Fuseki의 `/ontorag/update` 엔드포인트에
   SPARQL UPDATE POST.

**호출 (SPARQL UPDATE — `flow/writeback.py::set_lot_quarantined`):**

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

**검증 (외부에서 SPARQL SELECT로 확인):**

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

**해석:**

- 트리플이 *실제로* 적재돼 있어 ontorag의 다른 쿼리에서도 이 격리 사실을
  볼 수 있음 → 닫힌 루프.
- 인간 승인이 강제되는 이유: `QuarantineLot`의 `auto_execute_disabled =
  True` 가 어떤 자동 정책도 이 액션을 임의로 못 실행하게 잠금. ABox
  write-back은 항상 운영자 click 필요.

---

### 질문 14: "*만약* 격리하지 않고 그냥 뒀다면 어땠을까?" (CF replay)

**사용 레이어:** Flow Action `CounterfactualReplay` (질문 10 호출)

**도출 과정:**

1. 네 번째 rule이 fire (`quarantined=true ∧ rca_complete=false`).
2. `CounterfactualReplay.execute`가 질문 10과 동일한 counterfactual 호출.
3. 결과를 case state에 기록하고 `rca_complete=true`로 goal 달성 →
   CaseManager가 case를 CLOSED로 전이.

**결과:**

```text
counterfactual_p_fail: 0.2222
rca_complete: True
status: closed
```

**해석:**

- 이 단계는 *의사결정에 영향을 주지 않습니다* (이미 격리는 끝남). 그
  대신 **forensic recall** 을 위한 것 — 추후 누가 "왜 격리했냐"고 물으면
  audit log에 정량적 답이 같이 있음.
- 즉 격리한 후 "안 했으면 22% 확률로 또 실패했을 것"이라는 *수치적
  근거* 가 PROV-O로 영구 보존됨. 이게 ontorag-flow가 표방하는
  "provenance over replayability" 원칙의 실증.

---

## 종합 — 14개 질문이 만드는 한 그림

| 질문 | 레이어 | 답하는 것 | 답 못하는 것 |
|---|---|---|---|
| Q1 lot 순위 | L1 | "어디서 가장 많이 실패하나" | "이게 인과인가" |
| Q2 supplier 순위 | L1 | "공급사 별 빈도" | "supplier만 바꾸면 효과 있나" |
| Q3 condition 분포 | L1 | "조건-실패 상관" | "조건이 원인인가" |
| Q4 lot → product | L1 | "회수 범위" | — |
| Q5 baseline | L2 | "평균 실패율" | — |
| Q6 see(supplier=bad) | L2 | "공급사 나쁘다 관찰 시 사후확률" | "개입과 같은가" |
| Q7 do(supplier=good) | L3 R2 | "공급사 개입의 실제 효과" | "이 특정 사건은?" |
| Q8 do(pressure=normal) | L3 R2 | "공정 개입의 실제 효과" | "이 특정 사건은?" |
| Q9 do(both) | L3 R2 | "near-additive 효과" | "이 특정 사건은?" |
| Q10 counterfactual | L3 R3 | "이 특정 제품의 if-only" | — |
| Q11 Flow Pinpoint | Flow+L1 | "자동 의심 lot" | — |
| Q12 Flow Evaluate | Flow+L3 | "자동 개입 추천" | — |
| Q13 Flow Quarantine | Flow+write | "ABox 닫힌 루프" | — |
| Q14 Flow CF Replay | Flow+L3R3 | "결정의 사후 근거 기록" | — |

**핵심 메시지** — 이 데모가 증명하는 것:

1. L1 traceability는 **회수 범위와 우선순위** 를 줍니다 (Q1, Q4).
2. L1 집계만으로는 **공급사 vs 공정** 을 가를 수 없습니다 (Q2, Q3 → Q7, Q8).
3. L3 do-query만이 **"무엇을 바꿔야 가장 효과적인가"** 에 답합니다 (Q7-9).
4. L3 counterfactual만이 **개별 사건의 if-only** 를 정량화합니다 (Q10).
5. ontorag-flow는 이 모든 추론을 **결정 → 승인 → 행동 → 회고** 의 한 흐름으로
   감싸고, 매 단계를 PROV-O 감사 로그로 남깁니다 (Q11-14).
