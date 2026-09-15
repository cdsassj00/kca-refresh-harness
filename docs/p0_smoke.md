# P0 스모크 결과

실행 일시: 2026-09-15 15:27

## doctor (실호출)
- openalex: OK (약 868만 건 색인)
- crossref: OK
- semantic_scholar: 한도 초과(429). 키 없는 상태의 정상 동작, 자동 건너뜀
- arxiv: 응답 지연(타임아웃). 자동 건너뜀
- T1~T3 22종: 키 없음 → 건너뜀 (커넥터는 다음 단계)

## papers 실호출: "private 5G network deployment Korea" since 2023-06-01 limit 5

- 결과 10건 (openalex 5, crossref 5), 파일 `kb/evidence\20260915_152708_papers_private_5G_network_deployment_Korea.jsonl`
- 스키마 evidence_record 검증 통과

대표 3건:

- [A] 2023-10-25 The 6G Ecosystem as Support for IoE and Private Networks: Vision, Requirements,  — https://doi.org/10.3390/fi15110348
- [A] 2024-03-15 6G Networks and the AI Revolution—Exploring Technologies, Applications, and Emer — https://doi.org/10.3390/s24061888
- [A] 2024-01-23 Internet of Underwater Things: A Survey on Simulation Tools and 5G-Based Underwa — https://doi.org/10.3390/electronics13030474
