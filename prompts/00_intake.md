# 역할: 접수·분류 (refresh-intake / refresh-classify)

## 목적
보고서 PDF를 서랍(`reports/<id>/`)에 넣어 글자로 바꾸고(접수), 어떤 도메인·유형·연구설계의 보고서인지 표시한다(분류). 이후 모든 단계가 여기서 만든 `01_meta.json`·`02_classification.json`을 읽는다.

## 입력
- 보고서 ID(`R01`~`R07` 형식, 정규식 `^R\d{2}$`)와 PDF 경로(예: `samples/pdf/01_[2023.04]_….pdf`)
- 파일명이 `NN_[YYYY.MM]_제목.pdf`(또는 `예비NN_…`) 규칙이면 발간연월·제목이 자동 추출된다. 규칙에 맞지 않으면 접수 후 `01_meta.json`의 `published`(`YYYY-MM`)·`title`을 손으로 채운다.

## 1단계 접수
```
python scripts/intake.py <id> <pdf>
```
- 산출: `reports/<id>/00_source/<id>.md`(페이지마다 `<!-- page N -->` 표시), `reports/<id>/01_meta.json`(report_id, source_pdf, pages, chars, published, title).
- 확인: `chars`가 `pages × 200` 미만이면 텍스트가 없는 스캔 PDF일 가능성이 크다. 하네스는 OCR을 하지 않으므로 OCR 처리된 PDF를 다시 투입한다.
- **HWP/HWPX/DOCX는 현재 지원하지 않는다(PDF만).** 한컴오피스·워드에서 "PDF로 저장"하거나 `markitdown` 스킬의 `scripts/hwp_to_md.py`(한컴 COM → PDF)로 변환한 뒤 그 PDF를 투입한다. 변환한 PDF의 파일명도 위 규칙을 따르게 한다.

## 2단계 분류
`00_source/<id>.md`의 요약문·제1장(연구목적·방법)·목차·결론 장을 읽고 `reports/<id>/02_classification.json`을 쓴다. 스키마는 `prompts/01_chains.md`의 classification 스키마와 **동일**하다(단일 원본). 아래는 R01에서 실제로 쓴 확장 필드를 포함한 예다.
```json
{"report_id":"R01","title":"…","publisher":"…","published":"2023-04",
 "page_convention":"page = 원문 md의 <!-- page N -->(PDF 쪽), printed_page = 인쇄 쪽번호",
 "domains":["network_5g6g","spectrum"],"topics":["private_5g","smart_factory"],
 "type_mix":{"F":0.45,"M":0.30,"P":0.15,"B":0.10},
 "research_design":{"rq":"…","methods":["…"],"data":["…"],"sample":"…","limits":["…(p.NN)"]},
 "structure":[{"chapter":"제1장 연구목적 및 방법","pages":[23,30]}]}
```

## 규칙
- `domains`는 다음 6개 식별자 중에서만 1~3개를 고르고 첫 번째를 주 도메인으로 둔다. 세부 주제는 `topics`에 자유롭게 적는다(kb·레지스트리는 `domains`만 본다).
  | 식별자 | 범위 |
  |---|---|
  | spectrum | 주파수 정책·할당·경매·대가·전파관리 |
  | emf_inspection | 전자파·전파환경·측정·검사·인증 |
  | broadcast_media | 방송·미디어·OTT·콘텐츠 시장·규제 |
  | network_5g6g | 5G/6G·특화망(이음5G)·O-RAN·네트워크 산업 |
  | ict_qualification | ICT 자격·인력·교육·시험 |
  | kca_management | 기관 전략·사업·기금·경영 |
- `type_mix`는 유형 7개(F 전망·예측 / M 경제성·계량 / S 실태조사·설문 / P 정책·제도 / T 기술·표준·실험 / B 사례·동향 / G 기관 전략) 중 해당하는 것만 넣고 합이 1.0이 되게 한다. 비중의 기준은 결론·제언 장에서 차지하는 분량이다. `templates/taxonomy.yaml`이 있으면 그 정의를 따른다.
- `research_design.limits`에는 원문이 스스로 밝힌 한계와, 읽으면서 발견한 내부 불일치(표 합계 오류 등)를 page와 함께 적는다.
- 원문에 없는 수치·기관명·연도를 만들지 않는다. 확인이 안 되는 필드는 빈 문자열·빈 배열로 둔다.
- 저장은 UTF-8, `ensure_ascii=False`. 해당 스키마가 `templates/schemas/`에 있으면 `python scripts/validate.py reports/<id>/02_classification.json --schema <name>`으로 확인한다.
- 이 단계는 결론을 뽑지 않는다. 결론·논증 사슬은 `prompts/01_chains.md`의 몫이며, 그 단계는 이미 있는 `02_classification.json`을 읽고 덮어쓰지 않는다(필드 보강만).
